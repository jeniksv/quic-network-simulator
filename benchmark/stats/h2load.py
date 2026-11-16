import json

from .sample import Sample

MEASUREMENTS = {"duration", "request_per_second", "bytes_per_second", "requests", "status_codes", "traffic",
                "udp_datagram", "performance"}
IGNORED = {"gro_packets"}
INITIAL_RTT = 0.333


class SampleArray:
    def __init__(self, key, name, sentinel=None, total=False):
        self.key = key
        self.name = name
        self.sentinel = sentinel
        self.total = total

    def connected(self, values, unconnected):
        kept = []
        for value in values:
            if unconnected and abs(value - self.sentinel) < 1e-9:
                unconnected -= 1
            else:
                kept.append(value)
        return kept


class MinRttArray(SampleArray):
    def connected(self, values, unconnected):
        return [value for value in values if value >= 0]


SAMPLE_ARRAYS = (
    SampleArray("request", "request_s"),
    SampleArray("connect", "connect_s"),
    SampleArray("ttfb", "ttfb_s"),
    SampleArray("request_per_second", "client_requests_per_second", sentinel=0.0),
    MinRttArray("min_rtt", "client_min_rtt_s", sentinel=-1e-9),
    SampleArray("smoothed_rtt", "client_smoothed_rtt_s", sentinel=INITIAL_RTT),
    SampleArray("packets_sent", "client_packets_sent", total=True),
    SampleArray("packets_recv", "client_packets_received", total=True),
    SampleArray("packets_lost", "client_packets_lost", total=True),
)


class H2load:
    def __init__(self, path):
        self.path = path
        self.warnings = []

    def exists(self):
        return self.path.exists()

    def summarize(self):
        measurements = json.loads(self.path.read_text())["measurements"]
        performance = measurements["performance"]
        known = {array.key for array in SAMPLE_ARRAYS} | IGNORED
        unknown = sorted(set(measurements) - MEASUREMENTS) + sorted(set(performance) - known)
        self.warnings = [f"unknown measurement {name!r}" for name in unknown]

        clients = len(performance["request_per_second"]["samples"])
        connected = len(performance["connect"]["samples"])
        samples = {array.name: self._connected(array, performance[array.key]["samples"], clients - connected)
                   for array in SAMPLE_ARRAYS}

        requests = measurements["requests"]
        traffic = measurements["traffic"]
        duration = measurements["duration"]
        summary = {
            "duration_s": duration,
            "requests": requests,
            "status_codes": measurements["status_codes"],
            "traffic": traffic,
            "udp_datagram": measurements["udp_datagram"],
            "bytes_per_second": measurements["bytes_per_second"],
            "success_rate": requests["succeeded"] / requests["total"] if requests["total"] else None,
            "goodput_bps": traffic["data"] * 8 / duration if duration else None,
            "requests_per_second": measurements["request_per_second"],
            "clients": clients,
            "connected_clients": connected,
            "client_fairness_jain": Sample(samples["client_requests_per_second"]).jain(),
        }
        for array in SAMPLE_ARRAYS:
            summary[array.name] = Sample(samples[array.name]).describe()
            if array.total:
                summary[array.name]["total"] = sum(samples[array.name])
        return summary

    def _connected(self, array, values, unconnected):
        if array.sentinel is None:
            return values

        kept = array.connected(values, unconnected)
        if len(values) - len(kept) != unconnected:
            self.warnings.append(f"{array.key} has {len(values) - len(kept)} values of unconnected clients, "
                                 f"expected {unconnected}")
        return kept
