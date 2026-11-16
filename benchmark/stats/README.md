# Parsing benchmark results

`parse.py` evaluates the output directories of `run.py` separately from the
runner. It reads `client/h2load.json` of every finished run, gathers the runs
of each cell (scenario, workload, configuration) across repetitions, and
writes tables and a report that compares the configurations. It only reads
the run directories and uses only the Python standard library.

```sh
python3 benchmark/parse.py benchmark/results/<directory>
```

A run is a `<config>/<scenario>/<workload>/r<N>` directory with a
`result.json`; the identity of the run comes from the path, and `result.json`
only marks that the run has finished. Unfinished runs are skipped, so a matrix
can be parsed while it runs; pin the parser to CPUs that the containers do not
use, such as with `taskset -c 0,1`. Runs of all given directories are gathered
together, so repetitions from several output directories can be combined.

A run without a usable `client/h2load.json` (the client failed or was killed,
for example after the simulator aborted) is listed with the reason and left
out of the measurements. Runs where some requests failed are kept; their
`success_rate` is below 1 and their latencies describe only the successful
requests.

## Output

The output goes to `<path>/summary` for one path, or to `--output`.

| File | Contents |
| --- | --- |
| `runs.csv` | One row per run: scenario, workload, configuration, repetition, error, and every metric |
| `cells.csv` | One row per cell and metric: runs, usable runs, and the distribution over the runs: `n`, `median` with a distribution-free confidence interval (`ci_low`, `ci_high`; 95 % needs at least 6 runs, `--confidence`), `p25`, `p75`, `min`, `max`, `mean`, `sd` |
| `report.html` | Runs per configuration and the failed runs, then for every scenario and workload a table of the medians with one row per metric and one column per configuration, with the best configuration in bold where the metric has a direction and the confidence interval on hover |

## h2load.json

Every metric has one value per run. The sample arrays of h2load are reduced to
their distribution: `min`, `p25`, `median`, `p75`, `p90`, `p95`, `p99`, `max`,
`mean`, `sd`. Quantiles are observed values (nearest rank) and the median of an
even count is the mean of the middle two, as h2load reports them. h2load sorts
every array on its own, so arrays cannot be matched by client.

Left out are `gro_packets`, one sample per received datagram, and the values
that h2load stores for clients that never connected: a minimum RTT of -1 ns, a
smoothed RTT of 333 ms (the initial RTT) and a request rate of 0. Their number
is the number of clients minus the number of `connect` samples; another number
of such values is printed as a warning, as is a measurement that the parser
does not know.

## Metrics

| Metric | Better | Contents |
| --- | --- | --- |
| `success_rate` | higher | Succeeded requests divided by all requests |
| `requests.total` | none | Requests of the workload |
| `requests.{started,done,succeeded}` | higher | Requests h2load started, finished (succeeded or failed), and that succeeded |
| `requests.{failed,errored,timeout}` | lower | Requests that failed, failed with an error, and timed out |
| `status_codes.2xx` | higher | Responses with a 2xx status |
| `status_codes.3xx` | none | Responses with a 3xx status |
| `status_codes.{4xx,5xx}` | lower | Responses with a 4xx or 5xx status |
| `goodput_bps` | higher | Response data in bits per second of the h2load run |
| `bytes_per_second` | higher | Received bytes (`traffic.total`) per second of the h2load run |
| `requests_per_second` | higher | Succeeded requests per second |
| `duration_s` | lower | Duration of the h2load run |
| `traffic.{total,headers,headers_decompressed,data}` | none | Bytes h2load received: in total, of compressed and decompressed response headers, and of response data |
| `clients` | none | Clients of the workload |
| `connected_clients` | higher | Clients that connected |
| `client_fairness_jain` | higher | Jain's index of the request rates of the connected clients; n/a for one client |
| `request_s.<statistic>` | lower | Request latencies of the run |
| `ttfb_s.<statistic>` | lower | Times to first byte of the clients |
| `connect_s.<statistic>` | lower | Connection times of the clients |
| `client_requests_per_second.<statistic>` | higher | Request rates of the clients |
| `client_min_rtt_s.<statistic>`, `client_smoothed_rtt_s.<statistic>` | lower | RTT estimates of the clients |
| `udp_datagram.{sent,recv}` | none | UDP datagrams the clients sent and received |
| `client_packets_sent.{total,<statistic>}`, `client_packets_received.{total,<statistic>}` | none | Packets the clients sent and received |
| `client_packets_lost.{total,<statistic>}` | lower | Packets the clients sent and declared lost, mostly acknowledgments, not lost response data |

`<statistic>` is each of `min`, `p25`, `median`, `p75`, `p90`, `p95`, `p99`,
`max`, `mean` and `sd` of the samples of the run (see above); `sd` is better
lower for every array with a direction. Metrics without a direction are never
marked as the best in the report.

New metrics are added to `METRICS` in `metrics.py`.
