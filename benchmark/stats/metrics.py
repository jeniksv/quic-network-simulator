from .sample import Sample
from .units import (BIT_RATE, BYTE_RATE, BYTES, CLIENTS, DATAGRAMS, PACKETS, RATE, RATIO, REQUESTS, RESPONSES,
                    SECONDS)


class Metric:
    def __init__(self, name, unit, better, description):
        self.name = name
        self.unit = unit
        self.better = better
        self.description = description
        self.path = name.split(".")

    @property
    def section(self):
        return ".".join(self.path[:2]) if self.path[0] == "sim" else "h2load"

    def metrics(self, percentiles):
        yield self

    def value(self, summary):
        for key in self.path:
            if summary is None:
                return None
            summary = summary.get(key)
        return summary

    def best(self, medians):
        if self.better is None or len(set(medians.values())) < 2:
            return set()
        top = (max if self.better == "higher" else min)(medians.values())
        return {config for config, value in medians.items() if value == top}


class Distribution(Metric):
    def metrics(self, percentiles):
        for statistic in Sample.statistics if percentiles else ("median",):
            better = "lower" if statistic == "sd" and self.better else self.better
            yield Metric(f"{self.name}.{statistic}", self.unit, better, f"{statistic} of {self.description}")


class Datagrams:
    def __init__(self, direction, description):
        self.direction = direction
        self.description = description

    def metrics(self, percentiles):
        name, what = f"sim.{self.direction}", self.description
        for metric in (
            Metric(f"{name}.datagrams", DATAGRAMS, None, f"Datagrams {what} that entered the simulator"),
            Metric(f"{name}.bytes", BYTES, None, f"UDP payload bytes {what} that entered the simulator"),
            Metric(f"{name}.long_header_datagrams", DATAGRAMS, None,
                   f"Datagrams {what} with a long header (handshake)"),
            Metric(f"{name}.dropped", DATAGRAMS, "lower", f"Datagrams {what} dropped in the simulator"),
            Metric(f"{name}.drop_rate", RATIO, "lower", f"Datagrams {what} dropped in the simulator divided by those "
                   f"that entered it, without those in flight at the end"),
            Metric(f"{name}.dropped_random", DATAGRAMS, "lower",
                   f"Datagrams {what} dropped by the loss model of the scenario"),
            Metric(f"{name}.dropped_queue", DATAGRAMS, "lower",
                   f"Datagrams {what} dropped by the full queue of the link"),
            Metric(f"{name}.in_flight_at_end", DATAGRAMS, None,
                   f"Datagrams {what} still in the simulator when it stopped"),
            Distribution(f"{name}.transit_s", SECONDS, "lower",
                         f"the times of the datagrams {what} through the simulator"),
            Distribution(f"{name}.queue_delay_s", SECONDS, "lower",
                         f"the times of the datagrams {what} in the queue of the link"),
            Distribution(f"{name}.datagram_bytes", BYTES, None, f"the UDP payload lengths of the datagrams {what}"),
        ):
            yield from metric.metrics(percentiles)


METRICS = (
    Metric("success_rate", RATIO, "higher", "Succeeded requests divided by all requests"),
    Metric("requests.total", REQUESTS, None, "Requests of the workload"),
    Metric("requests.started", REQUESTS, "higher", "Requests h2load started"),
    Metric("requests.done", REQUESTS, "higher", "Requests h2load finished, succeeded or failed"),
    Metric("requests.succeeded", REQUESTS, "higher", "Requests that succeeded"),
    Metric("requests.failed", REQUESTS, "lower", "Requests that failed"),
    Metric("requests.errored", REQUESTS, "lower", "Requests that failed with an error"),
    Metric("requests.timeout", REQUESTS, "lower", "Requests that timed out"),
    Metric("status_codes.2xx", RESPONSES, "higher", "Responses with a 2xx status"),
    Metric("status_codes.3xx", RESPONSES, None, "Responses with a 3xx status"),
    Metric("status_codes.4xx", RESPONSES, "lower", "Responses with a 4xx status"),
    Metric("status_codes.5xx", RESPONSES, "lower", "Responses with a 5xx status"),
    Metric("goodput_bps", BIT_RATE, "higher", "Response data in bits per second of the h2load run"),
    Metric("bytes_per_second", BYTE_RATE, "higher", "Received bytes (traffic.total) per second of the h2load run"),
    Metric("requests_per_second", RATE, "higher", "Succeeded requests per second of the h2load run"),
    Metric("duration_s", SECONDS, "lower", "Duration of the h2load run"),
    Metric("traffic.total", BYTES, None, "Bytes h2load received: headers, data and framing"),
    Metric("traffic.headers", BYTES, None, "Bytes of the compressed response headers"),
    Metric("traffic.headers_decompressed", BYTES, None, "Bytes of the decompressed response headers"),
    Metric("traffic.data", BYTES, None, "Bytes of the response data"),
    Metric("clients", CLIENTS, None, "Clients of the workload"),
    Metric("connected_clients", CLIENTS, "higher", "Clients that connected"),
    Metric("client_fairness_jain", RATIO, "higher", "Jain's fairness index of the request rates of the clients"),
    Distribution("request_s", SECONDS, "lower", "the request latencies of a run"),
    Distribution("ttfb_s", SECONDS, "lower", "the times to first byte of the clients"),
    Distribution("connect_s", SECONDS, "lower", "the connection times of the clients"),
    Distribution("client_requests_per_second", RATE, "higher", "the request rates of the clients"),
    Distribution("client_min_rtt_s", SECONDS, "lower", "the minimum RTTs of the clients"),
    Distribution("client_smoothed_rtt_s", SECONDS, "lower", "the smoothed RTTs of the clients"),
    Metric("udp_datagram.sent", DATAGRAMS, None, "UDP datagrams the clients sent"),
    Metric("udp_datagram.recv", DATAGRAMS, None, "UDP datagrams the clients received"),
    Metric("client_packets_sent.total", PACKETS, None, "Packets the clients sent"),
    Distribution("client_packets_sent", PACKETS, None, "the packets sent by the clients"),
    Metric("client_packets_received.total", PACKETS, None, "Packets the clients received"),
    Distribution("client_packets_received", PACKETS, None, "the packets received by the clients"),
    Metric("client_packets_lost.total", PACKETS, "lower",
           "Packets the clients sent and declared lost, mostly acknowledgments"),
    Distribution("client_packets_lost", PACKETS, "lower",
                 "the packets the clients sent and declared lost, mostly acknowledgments"),
    Datagrams("c2s", "from the client to the server"),
    Datagrams("s2c", "from the server to the client"),
    Metric("sim.s2c.egress_bps", BIT_RATE, "higher", "UDP payload bits per second leaving the simulator toward "
           "the client, from its first to its last datagram"),
    Metric("sim.s2c.utilization", RATIO, "higher", "Bits on the link toward the client divided by its bandwidth and "
           "the time from the first to the last datagram"),
    Metric("sim.s2c.overhead", RATIO, "lower", "UDP payload bytes the server sent divided by traffic.data, minus 1: "
           "QUIC and HTTP/3 overhead and retransmissions"),
    Distribution("sim.s2c.burst_datagrams", DATAGRAMS, "lower", "the bursts of the server: datagrams that "
                 "entered the simulator faster than the link transmits them"),
    Metric("sim.s2c.burst_share_10", RATIO, "lower", "Share of the datagrams of the server in bursts of at least 10"),
    Distribution("sim.conn.drop_rate", RATIO, "lower", "the drop rates of the connections in the simulator, "
                 "both directions"),
    Distribution("sim.conn.queue_delay_s", SECONDS, "lower", "the median queue delays of the connections toward "
                 "the client"),
    Distribution("sim.conn.duration_s", SECONDS, "lower", "the durations of the connections on the client side "
                 "of the simulator"),
)
