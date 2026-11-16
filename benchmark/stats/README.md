# Parsing benchmark results

`parse.py` evaluates one output directory of `run.py` separately from the
runner. It reads `client/h2load.json` of every finished run and, when the run
was captured (`CAPTURE=1`), the packet captures of the simulator, gathers the
runs of each cell (scenario, workload, configuration) across repetitions, and
writes tables and a report that compares the configurations. It only reads
the run directories and uses only the Python standard library.

```sh
python3 benchmark/parse.py benchmark/results/<directory>
```

A distribution of a run is reported by its median; `--percentiles` reports
every statistic of it (see [Metrics](#metrics)).

A run is a `<config>/<scenario>/<workload>/r<N>` directory with a
`result.json`; the identity of the run comes from the path, and `result.json`
marks that the run has finished and gives the scenario parameters to the
captures. Unfinished runs are skipped, so a matrix
can be parsed while it runs; pin the parser to CPUs that the containers do not
use, such as with `taskset -c 0,1`. The path can also be the directory of one
run; a directory that holds several output directories is refused.

A run without a usable `client/h2load.json` (the client failed or was killed,
for example after the simulator aborted) is listed with the reason and left
out of the measurements. Runs where some requests failed are kept; their
`success_rate` is below 1 and their latencies describe only the successful
requests.

## Output

The output goes to `<path>/summary`, or to `--output`.

| File | Contents |
| --- | --- |
| `runs.csv` | One row per run: scenario, workload, configuration, repetition, error, and every metric |
| `cells.csv` | One row per cell and metric: runs, usable runs, and the distribution over the runs: `n`, `median` with a distribution-free confidence interval (`ci_low`, `ci_high`; 95 % needs at least 6 runs, `--confidence`), `p25`, `p75`, `min`, `max`, `mean`, `sd` |
| `report.html` | Runs per configuration and the failed runs, then for every scenario and workload a table of the medians with one row per metric and one column per configuration, with the best configuration in bold where the metric has a direction and the confidence interval on hover; the table is split into sections `h2load`, `sim.c2s`, `sim.s2c` and `sim.conn`, all collapsed, and sections without any value are left out |

## h2load.json

Every metric has one value per run. The sample arrays of h2load are reduced to
their distribution: `min`, `p25`, `median`, `p75`, `p90`, `p95`, `p99`, `max`,
`mean`, `sd`. Quantiles are observed values by the nearest-rank method (the
value at rank ⌈q·n⌉ of the sorted samples), the median of an even count is the
mean of the middle two, and `sd` is the sample standard deviation. The fields
that h2load computes itself are not used, because they include the values of
clients that never connected (see below); they also differ in two cases: its
`p95` and `p99` are the value at rank ⌊q·n⌋ + 1, one higher when q·n is an
integer (its `p99` of 100 samples is the maximum), and it truncates the median
of the packet counts to an integer. h2load sorts every array on its own, so
arrays cannot be matched by client.

Left out are `gro_packets`, one sample per received datagram, and the values
that h2load stores for clients that never connected: a minimum RTT of -1 ns, a
smoothed RTT of 333 ms (the initial RTT) and a request rate of 0. Their number
is the number of clients minus the number of `connect` samples; another number
of such values is printed as a warning, as is a measurement that the parser
does not know.

## Simulator captures

The simulator captures its client-side interface (`sim/trace_node_left.pcap`)
and its server-side interface (`sim/trace_node_right.pcap`), so every QUIC
datagram appears twice: when it enters the simulator and when it leaves it.
The UDP payload does not change on the way, so a datagram is matched across
the captures by its client address and port, its length and a hash of its
first 64 bytes. Both captures are read at once in time order and only the
datagrams in the simulator are kept, so even a 1 GB transfer needed about
130 MiB besides the mapped files, and 41 GB of captures of 52 runs took about
two minutes.
QUIC is encrypted: the captures show datagrams, not requests or
retransmissions.

A datagram that has not left the simulator twice its longest possible transit
(delay and full queue, from `scenario_parameters` of `result.json`) plus one
second after it entered is dropped. A datagram that entered shortly before the
last one of its direction left, within the longest measured transit, was still
in flight when the simulator stopped and is counted in neither. The cause of a
drop is known in some scenarios: in `simple-p2p`, `tcp-cross-traffic` and
`udp-cross-traffic` only the queue of the link drops; `drop-rate` logs its
decision about every datagram that passed the queue to `sim/console.log`, so
its `Dropping` lines are the random drops and the rest are queue overflows.

The queue delay of a datagram is its transit minus the delay of the link and
the transmission of the datagram with its PPP header at the bandwidth of the
link. A connection is a client address and port; its duration runs from its
first to its last datagram on the client side.

Warnings are printed for a datagram that left without entering, a truncated
capture or one that dropped packets, a `drop-rate` log that does not match the
captures, and when the datagrams that entered from the client or the
connections differ from `udp_datagram.sent` or the clients of h2load.

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

Metrics of the simulator captures, n/a for a run without them; `<d>` is `c2s`
(from the client to the server) or `s2c`:

| Metric | Better | Contents |
| --- | --- | --- |
| `sim.<d>.datagrams`, `sim.<d>.bytes` | none | Datagrams and their UDP payload bytes that entered the simulator |
| `sim.<d>.long_header_datagrams` | none | Datagrams with a long header (handshake) |
| `sim.<d>.dropped`, `sim.<d>.drop_rate` | lower | Datagrams dropped in the simulator, and divided by those that entered it without those in flight at the end |
| `sim.<d>.dropped_random`, `sim.<d>.dropped_queue` | lower | Drops by the loss model of the scenario and by the full queue; n/a where the cause is not known |
| `sim.<d>.in_flight_at_end` | none | Datagrams still in the simulator when it stopped |
| `sim.<d>.transit_s.<statistic>` | lower | Times of the datagrams through the simulator |
| `sim.<d>.queue_delay_s.<statistic>` | lower | Times of the datagrams in the queue of the link |
| `sim.<d>.datagram_bytes.<statistic>` | none | UDP payload lengths of the datagrams |
| `sim.s2c.egress_bps` | higher | UDP payload bits per second toward the client, from its first to its last datagram |
| `sim.s2c.utilization` | higher | Bits on the link toward the client divided by its bandwidth and the same time |
| `sim.s2c.overhead` | lower | UDP payload bytes the server sent divided by `traffic.data`, minus 1: QUIC and HTTP/3 overhead and retransmissions |
| `sim.s2c.burst_datagrams.<statistic>` | lower | Bursts of the server: consecutive datagrams, of all connections, that came within half of the time the link transmits the previous one |
| `sim.s2c.burst_share_10` | lower | Share of the datagrams of the server in bursts of at least 10 |
| `sim.conn.drop_rate.<statistic>` | lower | Drop rates of the connections, both directions |
| `sim.conn.queue_delay_s.<statistic>` | lower | Median queue delays of the connections toward the client |
| `sim.conn.duration_s.<statistic>` | lower | Durations of the connections |

`<statistic>` is `median`, and with `--percentiles` each of `min`, `p25`,
`median`, `p75`, `p90`, `p95`, `p99`, `max`, `mean` and `sd` of the samples of
the run (see above); `sd` is better lower for every distribution with a
direction. Metrics without a direction are never
marked as the best in the report.

New metrics are added to `METRICS` in `metrics.py`.
