"""Measurements from the JSON output of h2load (--output-file, format v1)."""
import json

from .distribution import describe, jain

# Measurements of a whole h2load run; performance holds the sample arrays.
MEASUREMENTS = {"duration", "request_per_second", "bytes_per_second", "requests", "status_codes", "traffic",
                "udp_datagram", "performance"}
# Sample arrays of h2load and their names in the summary.
SAMPLES = {
    "request": "request_s",
    "connect": "connect_s",
    "ttfb": "ttfb_s",
    "request_per_second": "client_requests_per_second",
    "min_rtt": "client_min_rtt_s",
    "smoothed_rtt": "client_smoothed_rtt_s",
    "packets_sent": "client_packets_sent",
    "packets_recv": "client_packets_received",
    "packets_lost": "client_packets_lost",
}
# One sample per received datagram, so the largest part of the file.
IGNORED = {"gro_packets"}
# Removal of the values h2load stores for the clients that never connected, given their number.
UNCONNECTED = {
    "min_rtt": lambda values, count: [value for value in values if value >= 0],  # -1 ns
    "request_per_second": lambda values, count: _without(values, 0.0, count),
    "smoothed_rtt": lambda values, count: _without(values, 0.333, count),  # the initial RTT
}


def summarize(path):
    """Return the summary of an h2load.json file and warnings about it."""
    data = json.loads(path.read_text())
    measurements = data["measurements"]
    performance = measurements["performance"]
    warnings = [f"unknown measurement {name!r}" for name in sorted(set(measurements) - MEASUREMENTS)]
    warnings += [f"unknown measurement {name!r}" for name in sorted(set(performance) - set(SAMPLES) - IGNORED)]

    # connect samples cover the connected clients, request_per_second all of them.
    clients = len(performance["request_per_second"]["samples"])
    connected = len(performance["connect"]["samples"])
    unconnected = clients - connected
    samples = {}
    for key, name in SAMPLES.items():
        values = performance[key]["samples"]
        remove = UNCONNECTED.get(key)
        kept = remove(values, unconnected) if remove else values
        if remove and len(values) - len(kept) != unconnected:
            warnings.append(f"{key} has {len(values) - len(kept)} values of unconnected clients, "
                            f"expected {unconnected}")
        samples[name] = kept

    requests = measurements["requests"]
    traffic = measurements["traffic"]
    duration = measurements["duration"]
    return {
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
        "client_fairness_jain": jain(samples["client_requests_per_second"]),
        "client_packets_sent_total": sum(samples["client_packets_sent"]),
        "client_packets_received_total": sum(samples["client_packets_received"]),
        "client_packets_lost_total": sum(samples["client_packets_lost"]),
        **{name: describe(values) for name, values in samples.items()},  # distributions of the sample arrays
    }, warnings


def _without(values, sentinel, count):
    """Remove up to count values equal to the sentinel."""
    kept = []
    for value in values:
        if count and abs(value - sentinel) < 1e-9:
            count -= 1
        else:
            kept.append(value)
    return kept
