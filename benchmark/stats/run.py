import json
from pathlib import Path
import struct

from .capture import Captures
from .h2load import H2load

H2LOAD = "client/h2load.json"


class Run:
    def __init__(self, directory):
        self.directory = directory
        self.name = Path(*directory.parts[-4:])
        self.config, self.scenario, self.workload, repetition = self.name.parts
        self.repetition = int(repetition[1:])
        self.summary = None
        self.warnings = []
        self.error = None

    @property
    def usable(self):
        return self.summary is not None

    def read(self):
        h2load = H2load(self.directory / H2LOAD, self.warnings)
        if not h2load.exists():
            self.error = f"no {H2LOAD}"
            return

        try:
            summary = h2load.summarize()
        except (OSError, ValueError, LookupError, TypeError, AttributeError) as error:
            self.error = f"{H2LOAD}: {error!r}"
            return

        summary["sim"] = self._read_captures(summary)
        self.summary = summary

    def _read_captures(self, summary):
        captures = Captures(self.directory / "sim", self.warnings)
        if not captures.exists():
            return None

        try:
            parameters = json.loads((self.directory / "result.json").read_text()).get("scenario_parameters")
            measured = captures.summarize(parameters)
        except (OSError, ValueError, LookupError, struct.error) as error:
            self.warnings.append(f"sim captures: {error!r}")
            return None

        sent =summary["udp_datagram"].get("sent")
        if measured["c2s"]["datagrams"] != sent:
            self.warnings.append(f"the client sent {sent} datagrams, {measured['c2s']['datagrams']} entered "
                                 f"the simulator")
        if measured["connections"] != summary["clients"]:
            self.warnings.append(f"{summary['clients']} clients, {measured['connections']} connections "
                                 f"in the captures")
        data = summary["traffic"].get("data")
        measured["s2c"]["overhead"] = measured["s2c"]["bytes"] / data - 1 if data else None
        return measured
