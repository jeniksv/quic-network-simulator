# NGINX native-QUIC vs quiche benchmark

A benchmark layer on top of the upstream quic-network-simulator (base commit
`e557a54510e3`). It reuses this repository's ns-3 simulator and dual-network
topology directly — the root `docker-compose.yml` is **extended** in place (no
overlay), and both endpoints are built from the single root `endpoint/` image.

The server is **your patched NGINX binary** that understands both
`listen 443 quic=nginx reuseport;` and `listen 443 quic=quiche reuseport;`.
The same binary serves both backends; the QUIC backend is selected in the NGINX
configuration. This benchmark does not build or supply that binary.

The client is **h2load** (nghttp2, HTTP/3), built from pinned sources in the
endpoint image. One image serves both the client and server roles.

## Layout

| Path | Purpose |
| --- | --- |
| `defaults.env` | Image names and default settings for `docker compose --env-file` |
| `conf/nginx.conf.template` | NGINX config template for either QUIC backend |
| `bin/nginx` | Optional location of **your** patched binary; git-ignored |
| `certs/`, `www/` | Certificate and payloads; git-ignored |
| `manual/` | Simulator captures, server config/logs and client output for a manual run |

The simulator/server/client services live in the repository-root
`docker-compose.yml`; the endpoint image is built from `../endpoint/`.

## Requirements

- Linux, OpenSSL CLI, local Docker Engine + Compose.
- Your patched NGINX binary, compatible with Ubuntu 24.04 and the host arch.
  If it is dynamically linked against non-system libraries, link it statically —
  the endpoint image only ships PCRE, PCRE2 and zlib.

Run one experiment at a time on a dedicated host. Upstream uses fixed subnets
`193.167.0.0/24` and `193.167.100.0/24` (and IPv6 equivalents).

## Build and prepare a manual run

Run all commands from the repository root. Build the shared endpoint image and
pull the simulator:

```bash
docker compose --env-file benchmark/defaults.env -f docker-compose.yml build server
docker compose --env-file benchmark/defaults.env -f docker-compose.yml pull sim
```

Create the log directories, a self-signed certificate, and a 10 MiB payload:

```bash
mkdir -p benchmark/certs benchmark/www benchmark/manual/{sim,server,client}
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj /CN=server \
  -keyout benchmark/certs/cert.key -out benchmark/certs/cert.crt
chmod 600 benchmark/certs/cert.key
dd if=/dev/zero of=benchmark/www/10M.bin bs=1048576 count=10
chmod 755 benchmark/www
chmod 644 benchmark/www/10M.bin
```

Render a config for the native NGINX QUIC backend with CUBIC, one worker and a
4 MiB stream buffer. To use quiche, change the replacement for `__BACKEND__` to
`quiche`:

```bash
sed -e 's/__BACKEND__/nginx/g' \
    -e 's/__CC__/cubic/g' \
    -e 's/__WORKERS__/1/g' \
    -e 's/__BUFFER__/4m/g' \
    benchmark/conf/nginx.conf.template > benchmark/manual/server/nginx.conf
```

The patched binary is bind-mounted into the server at runtime. Override
`NGINX_BIN` with its absolute host path, then start a run of 30 sequential
requests:

```bash
NGINX_BIN=/path/to/your/nginx \
docker compose --env-file benchmark/defaults.env -f docker-compose.yml \
  up --no-build --abort-on-container-exit --exit-code-from client
```

The client waits for the server's UDP listener and the simulator's startup
socket. Its text report is printed to the terminal; its JSON output is written
to `benchmark/manual/client/h2load.json`. A successful client process exit alone
does not guarantee successful requests: check the request counts and status
codes in the report. Server logs and simulator captures are stored in the
corresponding directories under `benchmark/manual/`.

Stop and remove the containers after the run:

```bash
docker compose --env-file benchmark/defaults.env -f docker-compose.yml down
```

## Simulator image

After changing `sim/`, build a local simulator image and select it explicitly:

```bash
docker build -t quic-network-simulator-local sim
NGINX_BIN=/path/to/your/nginx SIM_IMAGE=quic-network-simulator-local \
docker compose --env-file benchmark/defaults.env -f docker-compose.yml \
  up --no-build --abort-on-container-exit --exit-code-from client
```

The default simulator image is prebuilt and does not include local source
changes.

## Server configuration

The server's `SERVER_PARAMS` is a whitespace-separated list of NGINX command-line
arguments; paths must not contain spaces. The endpoint only executes NGINX with
these arguments. The default is `-c /logs/nginx.conf`; the server log directory
is mounted as `/logs`.

The supplied config contains `daemon off;` and `error_log /logs/error.log warn;`,
with absolute PID, lock and temporary paths under `/tmp`. The temporary paths
cover the standard HTTP modules (proxy, FastCGI, uWSGI and SCGI); if a module is
compiled out of your binary, remove its matching directive from the template.
