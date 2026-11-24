#!/usr/bin/env python3

import argparse
from pathlib import Path
import sys

from stats import Matrix, Report
from stats.sample import STATISTICS


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

    if args.output is None:
        args.output = args.path / "summary"

    try:
        matrix = Matrix(args.path)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    if not matrix.runs:
        print(f"No finished runs: no result.json under {args.path}.", file=sys.stderr)
        return 1

    matrix.read()
    Report(matrix, args.percentiles, args.confidence).write(args.output)
    matrix.print_summary()
    print(f"\nWritten to {args.output}: report.html, runs.csv, cells.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
