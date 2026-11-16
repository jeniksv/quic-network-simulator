"""Scalar metrics of one run, read from its h2load summary, with the direction of improvement."""

# Statistics of every sample array, as computed by distribution.describe.
STATISTICS = ("min", "p25", "median", "p75", "p90", "p95", "p99", "max", "mean", "sd")


class Metric:
    def __init__(self, name, unit, better, description, extract):
        self.name = name
        self.unit = unit
        self.better = better  # "higher", "lower", or None without a direction
        self.description = description
        self.extract = extract


def _value(key):
    return lambda summary: summary.get(key)


def _nested(group, key):
    return lambda summary: summary[group].get(key)


def _distribution(array, unit, better, what):
    """One metric per statistic of a sample array; a lower spread (sd) is better when the array has a direction."""
    def extract(statistic):
        return lambda summary: (summary["distributions"].get(array) or {}).get(statistic)
    return tuple(Metric(f"{array}.{statistic}", unit, "lower" if statistic == "sd" and better else better,
                        f"{statistic} of {what}", extract(statistic))
                 for statistic in STATISTICS)


METRICS = (
    Metric("success_rate", "", "higher", "Succeeded requests divided by all requests", _value("success_rate")),
    Metric("requests.total", "requests", None, "Requests of the workload", _nested("requests", "total")),
    Metric("requests.started", "requests", "higher", "Requests h2load started", _nested("requests", "started")),
    Metric("requests.done", "requests", "higher", "Requests h2load finished, succeeded or failed",
           _nested("requests", "done")),
    Metric("requests.succeeded", "requests", "higher", "Requests that succeeded", _nested("requests", "succeeded")),
    Metric("requests.failed", "requests", "lower", "Requests that failed", _nested("requests", "failed")),
    Metric("requests.errored", "requests", "lower", "Requests that failed with an error",
           _nested("requests", "errored")),
    Metric("requests.timeout", "requests", "lower", "Requests that timed out", _nested("requests", "timeout")),
    Metric("status_codes.2xx", "responses", "higher", "Responses with a 2xx status", _nested("status_codes", "2xx")),
    Metric("status_codes.3xx", "responses", None, "Responses with a 3xx status", _nested("status_codes", "3xx")),
    Metric("status_codes.4xx", "responses", "lower", "Responses with a 4xx status", _nested("status_codes", "4xx")),
    Metric("status_codes.5xx", "responses", "lower", "Responses with a 5xx status", _nested("status_codes", "5xx")),
    Metric("goodput_bps", "bit/s", "higher", "Response data in bits per second of the h2load run",
           _value("goodput_bps")),
    Metric("bytes_per_second", "B/s", "higher", "Received bytes (traffic.total) per second of the h2load run",
           _value("bytes_per_second")),
    Metric("requests_per_second", "1/s", "higher", "Succeeded requests per second of the h2load run",
           _value("requests_per_second")),
    Metric("duration_s", "s", "lower", "Duration of the h2load run", _value("duration_s")),
    Metric("traffic.total", "bytes", None, "Bytes h2load received: headers, data and framing",
           _nested("traffic", "total")),
    Metric("traffic.headers", "bytes", None, "Bytes of the compressed response headers",
           _nested("traffic", "headers")),
    Metric("traffic.headers_decompressed", "bytes", None, "Bytes of the decompressed response headers",
           _nested("traffic", "headers_decompressed")),
    Metric("traffic.data", "bytes", None, "Bytes of the response data", _nested("traffic", "data")),
    Metric("clients", "clients", None, "Clients of the workload", _value("clients")),
    Metric("connected_clients", "clients", "higher", "Clients that connected", _value("connected_clients")),
    Metric("client_fairness_jain", "", "higher", "Jain's fairness index of the request rates of the clients",
           _value("client_fairness_jain")),
    *_distribution("request_s", "s", "lower", "the request latencies of a run"),
    *_distribution("ttfb_s", "s", "lower", "the times to first byte of the clients"),
    *_distribution("connect_s", "s", "lower", "the connection times of the clients"),
    *_distribution("client_requests_per_second", "1/s", "higher", "the request rates of the clients"),
    *_distribution("client_min_rtt_s", "s", "lower", "the minimum RTTs of the clients"),
    *_distribution("client_smoothed_rtt_s", "s", "lower", "the smoothed RTTs of the clients"),
    Metric("udp_datagram.sent", "datagrams", None, "UDP datagrams the clients sent",
           _nested("udp_datagram", "sent")),
    Metric("udp_datagram.recv", "datagrams", None, "UDP datagrams the clients received",
           _nested("udp_datagram", "recv")),
    Metric("client_packets_sent.total", "packets", None, "Packets the clients sent",
           _value("client_packets_sent_total")),
    *_distribution("client_packets_sent", "packets", None, "the packets sent by the clients"),
    Metric("client_packets_received.total", "packets", None, "Packets the clients received",
           _value("client_packets_received_total")),
    *_distribution("client_packets_received", "packets", None, "the packets received by the clients"),
    Metric("client_packets_lost.total", "packets", "lower",
           "Packets the clients sent and declared lost, mostly acknowledgments", _value("client_packets_lost_total")),
    *_distribution("client_packets_lost", "packets", "lower",
                   "the packets the clients sent and declared lost, mostly acknowledgments"),
)
