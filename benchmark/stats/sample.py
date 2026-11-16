import math
import statistics

QUANTILES = (("p25", 0.25), ("median", None), ("p75", 0.75), ("p90", 0.9), ("p95", 0.95), ("p99", 0.99))
STATISTICS = ("min", *(name for name, _ in QUANTILES), "max", "mean", "sd")


class Sample:
    def __init__(self, values):
        self.values = sorted(values)

    def quantile(self, q):
        return self.values[max(math.ceil(round(q * len(self.values), 9)) - 1, 0)]

    def median(self):
        middle = len(self.values) // 2
        if len(self.values) % 2:
            return self.values[middle]
        return (self.values[middle - 1] + self.values[middle]) / 2

    def describe(self):
        if not self.values:
            return {}

        count = len(self.values)
        mean = statistics.fmean(self.values)
        summary = {"n": count, "min": self.values[0]}
        for name, q in QUANTILES:
            summary[name] = self.median() if q is None else self.quantile(q)
        summary["max"] = self.values[-1]
        summary["mean"] = mean
        squares = math.fsum((value - mean) ** 2 for value in self.values)
        summary["sd"] = math.sqrt(squares / (count - 1)) if count > 1 else 0.0
        return summary

    def median_ci(self, confidence):
        count = len(self.values)
        best, below = None, 0
        for k in range(1, (count + 1) // 2 + 1):
            below += math.comb(count, k - 1)
            if 1 - 2 * below / 2 ** count < confidence:
                break
            best = k

        if best is None:
            return None, None
        return self.values[best - 1], self.values[count - best]

    def jain(self):
        if len(self.values) < 2:
            return None
        squares = math.fsum(value * value for value in self.values)
        return math.fsum(self.values) ** 2 / (len(self.values) * squares) if squares else None
