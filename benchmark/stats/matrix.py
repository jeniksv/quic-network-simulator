from collections import Counter
from itertools import groupby
from operator import attrgetter
from pathlib import Path
import re
import sys

from .cell import Cell
from .run import Run

REPETITION = re.compile(r"r\d+")


class Matrix:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.runs = [Run(directory) for directory in self._directories()]
        if not self.runs:
            raise ValueError(f"No finished runs: no result.json under {self.directory}.")

        identity = attrgetter("scenario", "workload", "config")
        self.cells = [Cell(*key, list(runs)) for key, runs in groupby(sorted(self.runs, key=identity), identity)]
        self.groups = {key: list(cells) for key, cells in groupby(self.cells, attrgetter("scenario", "workload"))}

    def read(self):
        for run in self.runs:
            run.read()
            for warning in run.warnings:
                print(f"{run.name}: warning: {warning}", file=sys.stderr)

    def configurations(self):
        total = Counter(run.config for run in self.runs)
        usable = Counter(run.config for run in self.runs if run.usable)
        return [(config, total[config], usable[config]) for config in sorted(total)]

    def failed(self):
        return [run for run in self.runs if not run.usable]

    def print_summary(self):
        configurations = self.configurations()
        width = max(len("configuration"), *(len(config) for config, _, _ in configurations))
        print(f"Runs: {len(self.runs)}; {len(self.groups)} scenario/workload groups, "
              f"{len(configurations)} configurations\n")
        print("configuration".ljust(width) + "".join(f"{column:>10}" for column in ("runs", "usable", "failed")))
        for config, total, usable in configurations:
            print(config.ljust(width) + f"{total:>10}{usable:>10}{total - usable:>10}")

        failed = self.failed()
        if failed:
            print("\nRuns without a usable h2load.json:")
            for run in failed:
                print(f"  {run.name}: {run.error}")

    def _directories(self):
        if (self.directory / "result.json").is_file():
            directories = [self.directory]
        elif self.directory.is_dir():
            directories = sorted(result.parent for result in self.directory.rglob("result.json"))
        else:
            raise ValueError(f"{self.directory}: not a directory")

        for directory in directories:
            parts = (directory.parts[-4:] if directory == self.directory
                     else directory.relative_to(self.directory).parts)
            if len(parts) != 4 or not REPETITION.fullmatch(directory.name):
                raise ValueError(f"{self.directory}: not an output directory of run.py or a run: {directory} is "
                                 f"not <config>/<scenario>/<workload>/r<N> under it")
        return directories
