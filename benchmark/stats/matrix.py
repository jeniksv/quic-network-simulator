"""Runs of a matrix gathered into cells (scenario, workload, configuration) across repetitions."""
from collections import Counter, defaultdict

from .distribution import describe, median_ci


class Cell:
    """All runs of one configuration in one scenario and workload."""

    def __init__(self):
        self.runs = []

    def usable(self):
        """Runs with a parsed h2load.json."""
        return [run for run in self.runs if run.metrics is not None]

    def values(self, metric):
        """Values of the metric, one per usable run that has it."""
        return [run.metrics[metric.name] for run in self.usable() if run.metrics[metric.name] is not None]

    def summary(self, metric, confidence):
        """Distribution of the metric over the runs and a confidence interval of its median."""
        values = self.values(metric)
        summary = describe(values)
        if summary is not None:
            interval = median_ci(sorted(values), confidence)
            summary["ci_low"], summary["ci_high"] = interval if interval else (None, None)
        return summary


def gather(runs):
    """Group runs into cells keyed by (scenario, workload, config)."""
    cells = defaultdict(Cell)
    for run in runs:
        cells[run.scenario, run.workload, run.config].runs.append(run)
    return dict(cells)


def configurations(runs):
    """(configuration, runs, usable runs) of every configuration, in name order."""
    total = Counter(run.config for run in runs)
    usable = Counter(run.config for run in runs if run.metrics is not None)
    return [(config, total[config], usable[config]) for config in sorted(total)]
