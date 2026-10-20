# Python benchmark runner

The runner uses Python's standard library and the existing `docker-compose.yml`.
The matrix has three dimensions: NGINX configurations from `configs.json`,
network scenarios from `scenarios.json` and h2load workloads from `workloads.json`.
Every combination is one cell, and every cell is one run.

## Preparation

Use Docker Compose v2 with support for the `interface_name` setting in the
existing Compose file. Run one simulator stack at a time: its container names
and network subnets are fixed.

Build the images before running the matrix:

```sh
docker build -f endpoint/DockerfileH2load -t h2load:local endpoint
docker build -f endpoint/DockerfileNginx -t nginx-build:local endpoint
docker compose --env-file benchmark/defaults.env build
```

The Compose file expects certificates in `benchmark/certs` and files to serve in
`benchmark/www`. For the default workload, prepare a self-signed test certificate
and a 10 MiB file, unless they already exist:

```sh
mkdir -p benchmark/certs benchmark/www
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
    -keyout benchmark/certs/cert.key -out benchmark/certs/cert.crt \
    -subj /CN=server4 -addext subjectAltName=DNS:server4,DNS:server46
truncate -s 10M benchmark/www/10M.bin
```

## Run

Pass JSON files with scenarios, NGINX configurations and workloads:

```sh
python3 benchmark/run.py \
    --scenarios benchmark/scenarios.json \
    --configs benchmark/configs.json \
    --workloads benchmark/workloads.json
```

`scenarios.json` is a JSON array of named scenarios. `configs.json` is a JSON
array where each object describes **one NGINX configuration** (one matrix row):

```json
[
  {"name": "cubic-1", "worker_processes": 1, "quic_congestion_control": "cubic"},
  {"name": "bbr2-1", "worker_processes": 1, "quic_congestion_control": "bbr2"},
  {"name": "bbr2-4", "worker_processes": 4, "quic_congestion_control": "bbr2"}
]
```

Every configuration runs against **every scenario and every workload**. In
this example, three configurations, six scenarios and two workloads produce 36
sequential runs. To run one row,
provide a JSON file with one object. No combinations of directive values are
created, and `run.py` does not accept directives or scenarios as CLI arguments.

NGINX directive names are JSON keys. Missing values use the defaults in
`runner/directives.py` (one worker, CUBIC, a 4 MiB stream buffer, both QUIC
listeners, and `daemon off`). The optional `quic_pkts_between_probes` directive
is omitted by default. `listen` can be a JSON array to emit multiple listen
directives **within the same configuration**; arrays are not matrix axes.
Unknown directive names are errors. NGINX validates the generated configuration.

`scenarios.json` only describes the simulated network. `parameters` is passed
to the simulator as `SCENARIO`; `--delay` is one-way and `--queue` is measured
in packets:

```json
[
  {"name": "lan", "parameters": "simple-p2p --delay=1ms --bandwidth=1000Mbps --queue=200"},
  {"name": "crosstraffic", "parameters": "tcp-cross-traffic --delay=25ms --bandwidth=100Mbps --queue=30"}
]
```

The h2load client is described by `workloads.json`, a JSON array of named
h2load argument strings:

```json
[
  {"name": "bulk-10M", "client_params": "-n30 -c1 -m1 --alpn-list=h3 https://server4/10M.bin"},
  {"name": "web-100k", "client_params": "-n300 -c8 -m10 --alpn-list=h3 https://server4/100k.bin"}
]
```

`client_params` is passed to the client as `CLIENT_PARAMS` and overrides the
value in the Compose environment file. The runner checks fixed-count workloads
(`-n`), requiring every request to complete successfully.

`--defaults` selects the Compose environment file (default:
`benchmark/defaults.env`). The `--scenarios`, `--configs` and `--workloads`
options default to the files in `benchmark/`.

`--output` specifies a new directory; otherwise a timestamped directory is
created under `benchmark/results`. Existing output directories are never reused.
Each cell has its own `<config>/<scenario>/<workload>` directory, named after
the entries in the input files, containing:

| Path | Contents |
| --- | --- |
| `conf/nginx.conf` | Configuration used for this run |
| `client/console.log` | Client stdout and stderr |
| `client/h2load.json` | Original h2load measurements, if produced |
| `sim/console.log` | Simulator stdout and stderr |
| `sim/*.pcap` | Simulator packet captures |
| `server/console.log` | Server stdout and stderr |
| `server/access.log`, `server/error.log` | NGINX logs |
| `nginx-test.log` | Configuration validation output |
| `compose.log` | Compose startup and shutdown output |
| `result.json` | Configuration/scenario/workload names, status, errors, elapsed time and measurements |

Each cell validates its configuration with `nginx -t` in the server image, then
runs Compose until the client finishes. A zero process exit code alone is not
enough: the runner also checks the request counters in `h2load.json`.
Every response must have a 2xx status; redirects do not count as a successful
payload benchmark.
The runner stops
the services, collects their logs, and removes the stack even after failure
or Ctrl-C. A workload failure does not stop subsequent cells; a cleanup
failure does, to avoid starting another run over a leftover stack.

The CLI exits with 0 when all cells succeed, 1 on failure, or 130 on Ctrl-C.

## Package

`runner` is an ordinary Python package in `benchmark/runner`. `run.py` parses
the input files, creates `NginxConf`, `Scenario` and `Workload` objects, and
passes them to `Matrix`. `Matrix.run()` invokes `Cell.run(compose)` for each cell; results
remain in `cell.result`. `DockerCompose` wraps the Compose CLI.

`NginxConf` fills individual directive placeholders in the unchanged
`conf/nginx.conf.template`; directive classes do not know about NGINX blocks.
To add a directive, subclass `NginxDirective`, set `name` and optionally
`default` and `placeholder`, add the class to `DIRECTIVE_TYPES`, and add its
placeholder to the template. By default, the placeholder name is the upper-case
directive name. All configuration keys are handled generically by `run.py`.
