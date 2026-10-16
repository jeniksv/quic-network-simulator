# NGINX native-QUIC vs quiche benchmark

A benchmark layer on top of the upstream quic-network-simulator (base commit
`e557a54510e3`). It reuses this repository's ns-3 simulator and dual-network
topology directly — the root `docker-compose.yml` is **extended** in place (no
overlay), and both endpoints are built from the single root `endpoint/` image.

The server is **your patched NGINX binary** that understands both
`listen 443 quic=nginx reuseport;` and `listen 443 quic=quiche reuseport;`.
The same binary serves both backends; the QUIC backend is selected per trial.
This benchmark does not build or supply that binary.

The client is **h2load** (nghttp2, HTTP/3), built from pinned sources in the
endpoint image. The current harness measures **performance only** (goodput,
request latency, request rate); server CPU/memory metrics are not collected yet.

## Layout

| Path | Purpose |
| --- | --- |
| `run.py` | CLI entry point; selects build, dry-run or experiment execution |
| `runner/matrix.py` | `Workload`, `BenchmarkCase`, `Matrix`: workload definitions and the ordered benchmark plan |
| `runner/compose.py` | `DockerComposeSettings`, `DockerCompose`: Compose environment, image builds and stack startup/shutdown |
| `runner/nginx.py` | `NginxDirective`, `NginxConfig`: validated directives and per-case NGINX configuration |
| `runner/experiment.py` | `Experiment`, `CaseRunner`: inputs, provenance, case directories and results |
| `runner/metrics.py` | Parses h2load's `--output-file` JSON (schema v1) |
| `scenarios.tsv` | Named network presets → ns-3 `SCENARIO` strings |
| `defaults.env` | Docker Compose defaults, loaded by the runner and `docker compose --env-file` |
| `conf/nginx.conf.template` | NGINX config template rendered by `run.py` per trial |
| `bin/nginx` | Default location of **your** patched binary (or pass `--nginx PATH`); git-ignored |
| `certs/`, `www/` | Generated certificate and payloads (git-ignored) |
| `results/<experiment>/` | `metadata.json`, `results.csv`, one dir per trial |

The simulator/server/client services live in the repository-root
`docker-compose.yml`; the endpoint image is built from `../endpoint/`.

## Requirements

- Linux, Python 3.10+ (standard library only for the runner), OpenSSL CLI.
- Local Docker Engine + Compose v2 (bind mounts refer to the daemon host).
- Your patched NGINX binary, compatible with Ubuntu 24.04 and the host arch.
  If it is dynamically linked against non-system libraries, link it statically —
  the endpoint image only ships PCRE, PCRE2 and zlib.

Run one experiment at a time on a dedicated host. Upstream uses fixed subnets
`193.167.0.0/24` and `193.167.100.0/24` (and IPv6 equivalents).

## Quick start

From the repository root:

```bash
python3 benchmark/run.py --build                              # build endpoint image + pull sim
python3 benchmark/run.py --quick --nginx /path/to/your/nginx  # cert + payloads auto-generated
```

The patched binary is bind-mounted into the server at runtime: pass `--nginx PATH`
or drop it at `benchmark/bin/nginx` (the `NGINX_BIN` default). The certificate and
the payloads the plan needs are generated on first run (never overwritten).

`--build` builds the endpoint image (compiles h2load's TLS/QUIC stack — slow the
first time) and pulls the simulator image. Later runs reuse these images; rebuild
after changing `endpoint/` or the Dockerfile.

After changing `sim/`, build a local simulator image and select it explicitly:

```bash
docker build -t quic-network-simulator-local sim
SIM_IMAGE=quic-network-simulator-local python3 benchmark/run.py --quick
```

For a manual Compose run, set `SIM_IMAGE=quic-network-simulator-local` on the
`docker compose` command instead. The default simulator image is prebuilt and
does not include local source changes.

## Running

```bash
python3 benchmark/run.py --dry-run                         # print the matrix, no Docker
python3 benchmark/run.py                                   # full matrix (6 scenarios x 4 workloads x 2 backends x 3 repeats)
python3 benchmark/run.py --scenario broadband --workload bulk-10M --repeats 5
python3 benchmark/run.py --quick --backend quiche --quiche-cc cubic
python3 benchmark/run.py --output /abs/path/to/experiment  # must not exist
```

`--timeout` bounds each measured client run (default 3600 s). Backend order is
shuffled within each scenario/workload/repetition pair using `--seed` (default 0).
Edit `WORKLOADS` in `runner/matrix.py` and `scenarios.tsv` to change the matrix.

Docker Compose settings come from `defaults.env` and can be overridden via the
environment. The runner overrides `RUN_DIR`, `SCENARIO`, `SERVER_PARAMS` and
`CLIENT_PARAMS` for each trial; their file defaults are for manual Compose runs.
NGINX directives are configured in `conf/nginx.conf.template`, independently of
the Compose environment.

A prepared NGINX config can also be run by hand. Its certificate and payload
paths must refer to `/certs` and `/www` inside the container. Include `daemon off;`
and `error_log /logs/error.log warn;` in the config. Use absolute PID, lock and
temporary paths as shown in `conf/nginx.conf.template`:

```bash
mkdir -p benchmark/manual/{sim,server,client}
cp /path/to/nginx.conf benchmark/manual/server/nginx.conf
RUN_DIR=./benchmark/manual SERVER_PARAMS="-c /logs/nginx.conf" NGINX_BIN=benchmark/bin/nginx \
SCENARIO="simple-p2p --delay=25ms --bandwidth=100Mbps --queue=30" \
CLIENT_PARAMS="-n30 -c1 -m1 --alpn-list=h3 https://server46/10M.bin" \
docker compose --env-file benchmark/defaults.env -f docker-compose.yml \
  up --build --abort-on-container-exit --exit-code-from client
```

## Server configuration

Each `BenchmarkCase` represents one matrix cell and repetition and owns an
immutable `NginxConfig`. `CaseRunner` creates its directory and asks that config
to render `conf/nginx.conf.template` into `server/nginx.conf` before starting
Compose. The configuration has no reference back to the case.

`NginxDirective(name, value)` represents one configurable directive. Its
`validate()` method runs at construction, checking the benchmark's supported
`listen` forms and congestion-control values. These checks cover the directives
generated by the benchmark; they do not replace NGINX's own config validation.
The template has standalone placeholders named after directives, such as
`__LISTEN__` and `__QUIC_CONGESTION_CONTROL__`. Repeated `listen` directives
expand into separate lines with the template's indentation. Rendering rejects
missing or unused placeholders and duplicate congestion-control directives.

The case selects `listen 443 quic=<backend>` and
`quic_congestion_control <value>;` (default cubic). All other directives are fixed
in the template, including **1** worker and a **4m** stream buffer. Edit the
template to change them; `NGINX_WORKERS` and `HTTP3_STREAM_BUFFER_SIZE` environment
variables are no longer used. Verify what the buffer controls in each backend
of your binary. The rendered config is saved with each trial, and the template's
SHA-256 is recorded in the experiment metadata.

The server's `SERVER_PARAMS` is a whitespace-separated list of NGINX command-line
arguments; paths must not contain spaces. The endpoint only executes NGINX with
these arguments. The runner supplies only `-c /logs/nginx.conf`. The generated
config contains `daemon off;` and `error_log /logs/error.log warn;`, with absolute
PID, lock and temporary paths under `/tmp`. The temporary paths cover the standard
HTTP modules (proxy, FastCGI, uWSGI and SCGI); if a module is compiled out of your
binary, remove its matching directive from the template.
Each trial's `server/` directory is mounted as `/logs`, so its `nginx.conf` and
`error.log` belong only to that trial, including its repetition.

Before NGINX reads the config, its initial logging still uses the build-time
default error-log path. The config cannot change this early initialization; if
that file cannot be opened, NGINX reports the issue on stderr (`compose.log`).

The certificate is self-signed with no SAN — h2load does not verify the peer
certificate, so do not infer TLS authentication correctness from a run.

## Results and metric definitions

Each experiment directory has `metadata.json` (matrix, host/Docker info, base and
checked-out commit, image IDs, SHA-256 of the binary/certificate/template/payloads) and an
atomically written `results.csv`. Every trial gets its own directory with
`result.json`, `compose.log`, `cleanup.log`, the client's `h2load.json`, the server
config/error log, and the simulator capture. Text output from the client
is captured in `compose.log`.

Metrics come from h2load's `--output-file` JSON. All MB values are decimal
(1,000,000 B). A trial is `ok` only after h2load negotiates QUIC/HTTP3 and reports
exactly N successful 2xx responses with the expected body byte count.

| Column | Definition |
| --- | --- |
| `status` | `ok` or `failed` (with `error`) |
| `duration_s` | h2load's reported elapsed time (seconds) |
| `body_bytes` | Response body bytes (`traffic.data`) |
| `body_goodput_MBps` | `body_bytes / duration_s / 1,000,000`; excludes HTTP/3 and transport overhead |
| `successful_req_per_s` | Successful requests per second (from h2load) |
| `request_mean_ms`, `request_p50_ms`, `request_p95_ms`, `request_p99_ms` | Per-request completion latency (h2load, nearest-rank percentiles) |
| `connection_ttfb_mean_ms` | h2load's mean time-to-first-byte, per connection |

Server CPU and memory metrics are not collected in this version.

## Runner tests

```bash
python3 -m unittest discover -s benchmark/tests
```

The tests use a fake Docker command and a fake NGINX binary. They check the
runner's lifecycle, config/log isolation, result validation and argument
forwarding without requiring Docker or a patched NGINX build.
