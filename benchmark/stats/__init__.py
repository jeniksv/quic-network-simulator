"""Measurements of benchmark runs, read from their client/h2load.json and simulator captures."""
import json
from pathlib import Path
import re
import struct

from . import capture, h2load
from .metrics import METRICS

H2LOAD = "client/h2load.json"
REPETITION = re.compile(r"r(\d+)")


class Run:
    """One run, identified by its <config>/<scenario>/<workload>/r<N> directory."""

    def __init__(self, directory):
        self.directory = directory
        self.name = Path(*directory.parts[-4:])
        self.config, self.scenario, self.workload, repetition = directory.parts[-4:]
        self.repetition = int(REPETITION.fullmatch(repetition).group(1))
        self.metrics = None  # metric name -> value; None without a usable h2load.json
        self.warnings = []
        self.error = None

    def read(self):
        """Parse client/h2load.json and the simulator captures of the run and extract the metrics."""
        path = self.directory / H2LOAD
        if not path.exists():
            self.error = f"no {H2LOAD}"
            return
        try:
            summary, self.warnings = h2load.summarize(path)
        except (OSError, ValueError, LookupError, TypeError, AttributeError) as error:
            self.error = f"{H2LOAD}: {error!r}"
            return
        summary["sim"] = self._read_captures(summary)
        self.metrics = {metric.name: metric.extract(summary) for metric in METRICS}

    def _read_captures(self, summary):
        """Summary of the simulator captures, or None without them."""
        sim = self.directory / "sim"
        if not capture.captured(sim):
            return None
        try:
            parameters = json.loads((self.directory / "result.json").read_text()).get("scenario_parameters")
            measured, warnings = capture.summarize(sim, parameters)
        except (OSError, ValueError, LookupError, struct.error) as error:
            self.warnings.append(f"sim captures: {error!r}")
            return None
        self.warnings += warnings
        sent = summary["udp_datagram"].get("sent")
        if measured["c2s"]["datagrams"] != sent:
            self.warnings.append(f"the client sent {sent} datagrams, {measured['c2s']['datagrams']} entered "
                                 f"the simulator")
        if measured["connections"] != summary["clients"]:
            self.warnings.append(f"{summary['clients']} clients, {measured['connections']} connections "
                                 f"in the captures")
        return measured


def find_runs(root):
    """Finished runs (directories with result.json) of one output directory of run.py, or one run, in name order."""
    root = Path(root)
    if (root / "result.json").is_file():
        directories = [root]
    elif root.is_dir():
        directories = sorted(result.parent for result in root.rglob("result.json"))
    else:
        raise ValueError(f"{root}: not a directory")
    runs = []
    for directory in directories:
        # Runs of one output directory only: <root>/<config>/<scenario>/<workload>/r<N>.
        parts = directory.parts[-4:] if directory == root else directory.relative_to(root).parts
        if len(parts) != 4 or not REPETITION.fullmatch(directory.name):
            raise ValueError(f"{root}: not an output directory of run.py or a run: {directory} is not "
                             f"<config>/<scenario>/<workload>/r<N> under it")
        runs.append(Run(directory))
    return runs
