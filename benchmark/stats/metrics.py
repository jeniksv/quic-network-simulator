"""Scalar metrics of one run, read from its h2load summary, with the direction of improvement."""

# Statistics of every sample array, as computed by distribution.describe.
STATISTICS = ("min", "p25", "median", "p75", "p90", "p95", "p99", "max", "mean", "sd")


class Metric:
    def __init__(self, name, unit, better, description, extract, statistic=None):
        self.name = name
        self.unit = unit
        self.better = better  # "higher", "lower", or None without a direction
        self.description = description
        self.extract = extract
        self.statistic = statistic  # statistic of a distribution, None for a single value


def _value(key):
    return lambda summary: summary.get(key)


def _nested(group, key):
    return lambda summary: summary[group].get(key)


def _sim(*keys):
    """Value of the summary of the simulator captures; None without them."""
    def extract(summary):
        value = summary.get("sim")
        for key in keys:
            if value is None:
                return None
            value = value.get(key)
        return value
    return extract


def _overhead(summary):
    sent, data = _sim("s2c", "bytes")(summary), summary["traffic"].get("data")
    return sent / data - 1 if sent is not None and data else None


def _distribution(name, unit, better, what, distribution=None):
    """One metric per statistic of a distribution, by default of the h2load sample array of that name.

    A lower spread (sd) is better when the distribution has a direction.
    """
    if distribution is None:
        def distribution(summary):
            return summary["distributions"].get(name)

    def extract(statistic):
        return lambda summary: (distribution(summary) or {}).get(statistic)
    return tuple(Metric(f"{name}.{statistic}", unit, "lower" if statistic == "sd" and better else better,
                        f"{statistic} of {what}", extract(statistic), statistic)
                 for statistic in STATISTICS)


def _direction(direction, what):
    """Metrics of the datagrams of one direction through the simulator."""
    def metric(key, unit, better, description):
        return Metric(f"sim.{direction}.{key}", unit, better, description, _sim(direction, key))
    return (
        metric("datagrams", "datagrams", None, f"Datagrams {what} that entered the simulator"),
        metric("bytes", "bytes", None, f"UDP payload bytes {what} that entered the simulator"),
        metric("long_header_datagrams", "datagrams", None, f"Datagrams {what} with a long header (handshake)"),
        metric("dropped", "datagrams", "lower", f"Datagrams {what} dropped in the simulator"),
        metric("drop_rate", "", "lower", f"Datagrams {what} dropped in the simulator divided by those that "
                                         f"entered it, without those in flight at the end"),
        metric("dropped_random", "datagrams", "lower", f"Datagrams {what} dropped by the loss model of the scenario"),
        metric("dropped_queue", "datagrams", "lower", f"Datagrams {what} dropped by the full queue of the link"),
        metric("in_flight_at_end", "datagrams", None, f"Datagrams {what} still in the simulator when it stopped"),
        *_distribution(f"sim.{direction}.transit_s", "s", "lower", f"the times of the datagrams {what} "
                       f"through the simulator", _sim(direction, "transit_s")),
        *_distribution(f"sim.{direction}.queue_delay_s", "s", "lower", f"the times of the datagrams {what} "
                       f"in the queue of the link", _sim(direction, "queue_delay_s")),
        *_distribution(f"sim.{direction}.datagram_bytes", "bytes", None, f"the UDP payload lengths of the "
                       f"datagrams {what}", _sim(direction, "datagram_bytes")),
    )


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
    *_direction("c2s", "from the client to the server"),
    *_direction("s2c", "from the server to the client"),
    Metric("sim.s2c.egress_bps", "bit/s", "higher", "UDP payload bits per second leaving the simulator toward "
           "the client, from its first to its last datagram", _sim("s2c", "egress_bps")),
    Metric("sim.s2c.utilization", "", "higher", "Bits on the link toward the client divided by its bandwidth and "
           "the time from the first to the last datagram", _sim("s2c", "utilization")),
    Metric("sim.s2c.overhead", "", "lower", "UDP payload bytes the server sent divided by traffic.data, minus 1: "
           "QUIC and HTTP/3 overhead and retransmissions", _overhead),
    *_distribution("sim.s2c.burst_datagrams", "datagrams", "lower", "the bursts of the server: datagrams that "
                   "entered the simulator faster than the link transmits them", _sim("s2c", "burst_datagrams")),
    Metric("sim.s2c.burst_share_10", "", "lower", "Share of the datagrams of the server in bursts of at least 10",
           _sim("s2c", "burst_share_10")),
    *_distribution("sim.conn.drop_rate", "", "lower", "the drop rates of the connections in the simulator, "
                   "both directions", _sim("conn", "drop_rate")),
    *_distribution("sim.conn.queue_delay_s", "s", "lower", "the median queue delays of the connections toward "
                   "the client", _sim("conn", "queue_delay_s")),
    *_distribution("sim.conn.duration_s", "s", "lower", "the durations of the connections on the client side "
                   "of the simulator", _sim("conn", "duration_s")),
)


def select(percentiles):
    """Metrics to report: every statistic of a distribution with percentiles, otherwise only its median."""
    if percentiles:
        return METRICS
    return tuple(metric for metric in METRICS if metric.statistic in (None, "median"))
