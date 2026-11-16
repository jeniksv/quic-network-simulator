"""Measurements of benchmark runs, read from their client/h2load.json."""
from pathlib import Path
import re

from . import h2load
from .metrics import METRICS

H2LOAD = "client/h2load.json"
REPETITION = re.compile(r"r(\d+)")


class Run:
    """One run, identified by its <config>/<scenario>/<workload>/r<N> directory."""

    def __init__(self, root, directory):
        self.directory = directory
        # Named relative to the given output directory, or by its last four parts.
        self.name = directory.relative_to(root.parent) if directory != root else Path(*directory.parts[-4:])
        self.config, self.scenario, self.workload, repetition = directory.parts[-4:]
        self.repetition = int(REPETITION.fullmatch(repetition).group(1))
        self.metrics = None  # metric name -> value; None without a usable h2load.json
        self.warnings = []
        self.error = None

    def read(self):
        """Parse client/h2load.json of the run and extract the metrics."""
        path = self.directory / H2LOAD
        if not path.exists():
            self.error = f"no {H2LOAD}"
            return
        try:
            summary, self.warnings = h2load.summarize(path)
        except (OSError, ValueError, LookupError, TypeError, AttributeError) as error:
            self.error = f"{H2LOAD}: {error!r}"
            return
        self.metrics = {metric.name: metric.extract(summary) for metric in METRICS}


def find_runs(paths):
    """Finished runs (directories with result.json) under the paths, in name order."""
    runs = []
    for root in paths:
        root = Path(root)
        if (root / "result.json").is_file():
            directories = [root]
        elif root.is_dir():
            directories = sorted(result.parent for result in root.rglob("result.json"))
        else:
            raise ValueError(f"{root}: not a directory")
        for directory in directories:
            if len(directory.parts) < 4 or not REPETITION.fullmatch(directory.name):
                raise ValueError(f"{directory}: not a <config>/<scenario>/<workload>/r<N> run directory")
            runs.append(Run(root, directory))
    return runs
