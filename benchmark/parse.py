#!/usr/bin/env python3

import argparse
from datetime import datetime
from pathlib import Path
import sys

from stats import find_runs
from stats.matrix import gather
from stats.metrics import METRICS
from stats.report import write_cells_csv, write_html, write_runs_csv


def main():
    parser = argparse.ArgumentParser(
        description="Read client/h2load.json of every finished run, gather the runs of each cell "
                    "across repetitions and write tables and a report comparing the configurations.")
    parser.add_argument("paths", nargs="+", type=Path,
                        help="Output directories of run.py; runs of all of them are gathered together")
    parser.add_argument("--output", type=Path,
                        help="Directory for runs.csv, cells.csv and report.html "
                             "(default: <path>/summary for one path)")
    parser.add_argument("--confidence", type=float, default=0.95,
                        help="Confidence of the interval of a median (default: 0.95)")
    args = parser.parse_args()

    if args.output is None:
        if len(args.paths) != 1:
            parser.error("--output is required with more than one path")
        args.output = args.paths[0] / "summary"

    try:
        runs = find_runs(args.paths)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    if not runs:
        print("No finished runs: no result.json under the given paths.", file=sys.stderr)
        return 1

    for run in runs:
        run.read()
        for warning in run.warnings:
            print(f"{run.name}: warning: {warning}", file=sys.stderr)

    cells = gather(runs)
    groups = sorted({cell.group for cell in cells.values()})
    configs = sorted({run.config for run in runs})
    args.output.mkdir(parents=True, exist_ok=True)
    write_runs_csv(args.output / "runs.csv", runs, METRICS)
    write_cells_csv(args.output / "cells.csv", cells, METRICS, args.confidence)
    info = [f"Runs: {len(runs)} from {', '.join(str(path) for path in args.paths)}",
            f"{len(groups)} scenario/workload groups, {len(configs)} configurations, {len(cells)} cells",
            f"Generated {datetime.now().isoformat(timespec='seconds')}"]
    write_html(args.output / "report.html", "Benchmark results", info, runs, cells, METRICS, args.confidence)

    width = max(len("configuration"), *(len(config) for config in configs))
    print(f"Runs: {len(runs)}; {len(groups)} scenario/workload groups, {len(configs)} configurations\n")
    print("configuration".ljust(width) + "".join(f"{c:>10}" for c in ("runs", "usable", "failed")))
    for config in configs:
        own = [run for run in runs if run.config == config]
        usable = sum(run.metrics is not None for run in own)
        print(config.ljust(width) + f"{len(own):>10}{usable:>10}{len(own) - usable:>10}")
    failed = [run for run in runs if run.metrics is None]
    if failed:
        print("\nRuns without a usable h2load.json:")
        for run in failed:
            print(f"  {run.name}: {run.error}")
    print(f"\nWritten to {args.output}: report.html, runs.csv, cells.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
