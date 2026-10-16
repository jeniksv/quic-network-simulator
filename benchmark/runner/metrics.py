"""Read h2load's --output-file JSON (schema v1). Times are in seconds; traffic is
in bytes. Goodput uses decimal 1,000,000 B = 1 MB. h2load computes the request
percentiles itself (nearest-rank)."""
import json
from pathlib import Path


def parse_output(path):
    m = json.loads(Path(path).read_text())["measurements"]
    req, status = m["requests"], m["status_codes"]
    traffic, perf = m["traffic"], m["performance"]
    duration_s = float(m["duration"])
    if duration_s <= 0:
        raise ValueError("Non-positive h2load duration")
    body_bytes = int(traffic["data"])
    return {
        "duration_s": duration_s,
        "requests_total": int(req["total"]),
        "started": int(req["started"]),
        "done": int(req["done"]),
        "succeeded": int(req["succeeded"]),
        "failed": int(req["failed"]),
        "errored": int(req["errored"]),
        "timeouts": int(req["timeout"]),
        "status_2xx": int(status["2xx"]),
        "status_3xx": int(status["3xx"]),
        "status_4xx": int(status["4xx"]),
        "status_5xx": int(status["5xx"]),
        "h3_bytes": int(traffic["total"]),
        "header_bytes": int(traffic["headers"]),
        "body_bytes": body_bytes,
        # udp_datagram is emitted only for QUIC/HTTP3 runs.
        "is_quic": "udp_datagram" in m,
        "body_goodput_MBps": body_bytes / duration_s / 1e6,
        "successful_req_per_s": float(m["request_per_second"]),
        # performance.* SDStat values are seconds -> expose milliseconds.
        "request_mean_ms": perf["request"]["mean"] * 1e3,
        "request_p50_ms": perf["request"]["median"] * 1e3,
        "request_p95_ms": perf["request"]["p95"] * 1e3,
        "request_p99_ms": perf["request"]["p99"] * 1e3,
        "connection_ttfb_mean_ms": perf["ttfb"]["mean"] * 1e3,
    }


def validate(result, expected_requests, expected_body_bytes):
    errors = []
    if not result["is_quic"]:
        errors.append("no QUIC/HTTP3 datagrams (not an h3 run)")
    for key in ("requests_total", "started", "done", "succeeded", "status_2xx"):
        if result[key] != expected_requests:
            errors.append(f"{key}={result[key]}, expected {expected_requests}")
    for key in ("failed", "errored", "timeouts", "status_3xx", "status_4xx", "status_5xx"):
        if result[key]:
            errors.append(f"{key}={result[key]}")
    if result["body_bytes"] != expected_body_bytes:
        errors.append(f"body_bytes={result['body_bytes']}, expected {expected_body_bytes}")
    return errors
