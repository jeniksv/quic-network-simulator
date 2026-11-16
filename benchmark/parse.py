#!/usr/bin/env python3

import argparse
from datetime import datetime
from pathlib import Path
import sys

from stats import find_runs
from stats.distribution import STATISTICS
from stats.matrix import configurations, gather
from stats.metrics import select
from stats.report import write_cells_csv, write_html, write_runs_csv


def main():
    parser = argparse.ArgumentParser(
        description="Read client/h2load.json and the simulator captures of every finished run, gather the "
                    "runs of each cell across repetitions and write tables and a report comparing the "
                    "configurations.")
    parser.add_argument("path", type=Path, help="Output directory of run.py, or the directory of one run")
    parser.add_argument("--output", type=Path,
                        help="Directory for runs.csv, cells.csv and report.html (default: <path>/summary)")
    parser.add_argument("--confidence", type=float, default=0.95,
                        help="Confidence of the interval of a median (default: 0.95)")
    parser.add_argument("--percentiles", action="store_true",
                        help=f"Report every statistic of the distributions of a run ({', '.join(STATISTICS)}); "
                             f"by default only the median")
    args = parser.parse_args()
    metrics = select(args.percentiles)

    if args.output is None:
        args.output = args.path / "summary"

    try:
        runs = find_runs(args.path)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    if not runs:
        print(f"No finished runs: no result.json under {args.path}.", file=sys.stderr)
        return 1

    for run in runs:
        run.read()
        for warning in run.warnings:
            print(f"{run.name}: warning: {warning}", file=sys.stderr)

    cells = gather(runs)
    groups = {key[:2] for key in cells}
    configs = configurations(runs)  # (configuration, runs, usable runs)
    args.output.mkdir(parents=True, exist_ok=True)
    write_runs_csv(args.output / "runs.csv", runs, metrics)
    write_cells_csv(args.output / "cells.csv", cells, metrics, args.confidence)
    info = [f"Runs: {len(runs)} from {args.path}",
            f"{len(groups)} scenario/workload groups, {len(configs)} configurations, {len(cells)} cells",
            "Distributions of a run: " + ("every statistic" if args.percentiles else
                                          "median only (every statistic with --percentiles)"),
            f"Generated {datetime.now().isoformat(timespec='seconds')}"]
    write_html(args.output / "report.html", "Benchmark results", info, runs, cells, metrics, args.confidence)

    width = max(len("configuration"), *(len(config) for config, _, _ in configs))
    print(f"Runs: {len(runs)}; {len(groups)} scenario/workload groups, {len(configs)} configurations\n")
    print("configuration".ljust(width) + "".join(f"{c:>10}" for c in ("runs", "usable", "failed")))
    for config, total, usable in configs:
        print(config.ljust(width) + f"{total:>10}{usable:>10}{total - usable:>10}")
    failed = [run for run in runs if run.metrics is None]
    if failed:
        print("\nRuns without a usable h2load.json:")
        for run in failed:
            print(f"  {run.name}: {run.error}")
    print(f"\nWritten to {args.output}: report.html, runs.csv, cells.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
