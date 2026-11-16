from .sample import Sample


class Cell:
    def __init__(self, scenario, workload, config, runs):
        self.scenario = scenario
        self.workload = workload
        self.config = config
        self.runs = runs

    def usable(self):
        return [run for run in self.runs if run.usable]

    def values(self, metric):
        values = [metric.value(run.summary) for run in self.runs]
        return [value for value in values if value is not None]

    def summary(self, metric, confidence):
        sample = Sample(self.values(metric))
        summary = sample.describe()
        if summary:
            summary["ci_low"], summary["ci_high"] = sample.median_ci(confidence)
        return summary
