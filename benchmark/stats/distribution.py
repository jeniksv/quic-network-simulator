"""Descriptive statistics of measured samples, defined as in h2load."""
import math

QUANTILES = (("p25", 0.25), ("median", None), ("p75", 0.75), ("p90", 0.9), ("p95", 0.95), ("p99", 0.99))


def nearest_rank(ordered, q):
    """The smallest of the ordered values that at least a fraction q of them do not exceed."""
    return ordered[max(math.ceil(round(q * len(ordered), 9)) - 1, 0)]


def median(ordered):
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def describe(values):
    """Count, extremes, quantiles, mean and sample standard deviation; None without values.

    Quantiles are observed values (nearest rank) and the median of an even
    number of values is the mean of the middle two, as h2load reports them.
    """
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)
    mean = math.fsum(ordered) / count
    summary = {"n": count, "min": ordered[0]}
    for name, q in QUANTILES:
        summary[name] = median(ordered) if q is None else nearest_rank(ordered, q)
    summary["max"] = ordered[-1]
    summary["mean"] = mean
    summary["sd"] = math.sqrt(math.fsum((v - mean) ** 2 for v in ordered) / (count - 1)) if count > 1 else 0.0
    return summary


def median_ci(ordered, confidence=0.95):
    """Distribution-free confidence interval of the median, or None for too few values.

    The interval [x(k), x(n-k+1)] of the ordered values covers the median with
    probability P(k <= B <= n-k) for B ~ Binomial(n, 1/2); the narrowest one that
    reaches the confidence is returned. 95 % needs at least 6 values.
    """
    count = len(ordered)
    best, below = None, 0
    for k in range(1, (count + 1) // 2 + 1):
        below += math.comb(count, k - 1)
        if 1 - 2 * below / 2 ** count < confidence:
            break
        best = k
    if best is None:
        return None
    return ordered[best - 1], ordered[count - best]


def jain(values):
    """Jain's fairness index; None for fewer than two values or when all are zero."""
    if len(values) < 2:
        return None
    squares = math.fsum(v * v for v in values)
    return math.fsum(values) ** 2 / (len(values) * squares) if squares else None
