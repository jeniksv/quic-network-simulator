#!/usr/bin/env python3

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from runner import DockerCompose, Matrix, NginxConf, Scenario, Workload


def load(path, kind, field=None, default_name=None):
    data = json.loads(Path(path).read_text())

    if not isinstance(data, list) or not data:
        raise ValueError(f"{path}: expected a nonempty list of {kind}s")

    names = set()
    entries = list()

    for index, entry in enumerate(data, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: {kind} {index} must be an object")

        name = entry.get("name", f"{default_name}-{index}" if default_name else None)
        if not name:
            raise ValueError(f"{path}: {kind} {index}: invalid name: {name!r}")

        if name in names:
            raise ValueError(f"{path}: duplicate {kind} name: {name!r}")

        names.add(name)

        if field and not entry.get(field):
            raise ValueError(f"{path}: {name}: missing {field}")

        entries.append((name, entry))

    return entries


def main():
    benchmark = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Run NGINX configs against simulator scenarios and workloads.")
    parser.add_argument("--scenarios", type=Path, default=benchmark / "scenarios.json",
                        help="JSON array of simulator scenarios")
    parser.add_argument("--configs", type=Path, default=benchmark / "configs.json",
                        help="JSON array of NGINX configurations (one row per object)")
    parser.add_argument("--workloads", type=Path, default=benchmark / "workloads.json",
                        help="JSON array of h2load workloads")
    parser.add_argument("--defaults", type=Path, default=benchmark / "defaults.env")
    parser.add_argument("--output", type=Path,
                        default=benchmark / "results" / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f"),
                        help="New output directory; existing directories are never overwritten")
    args = parser.parse_args()

    try:
        scenarios = [Scenario(name, entry["parameters"])
                     for name, entry in load(args.scenarios, "scenario", "parameters")]
        configs = [NginxConf(name, entry)
                   for name, entry in load(args.configs, "configuration", default_name="config")]
        workloads = [Workload(name, entry["client_params"])
                     for name, entry in load(args.workloads, "workload", "client_params")]
        compose = DockerCompose(benchmark.parent / "docker-compose.yml", args.defaults)
        matrix = Matrix(configs, scenarios, workloads, compose, args.output)

        return 0 if matrix.run() else 1
    except KeyboardInterrupt:
        print("Interrupted; see the output directory for cell logs and results.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
