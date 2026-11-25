#!/usr/bin/env python3

import argparse
from pathlib import Path
import sys

from stats import Matrix, Report, Sample


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
                        help=f"Report every statistic of the distributions of a run "
                             f"({', '.join(Sample.statistics)}); by default only the median")
    args = parser.parse_args()
    output = args.output or args.path / "summary"

    try:
        matrix = Matrix(args.path)
        matrix.read()
        Report(matrix, args.percentiles, args.confidence).write(output)
        matrix.print_summary()
        print(f"\nWritten to {output}: report.html, runs.csv, cells.csv")
        return 0
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
