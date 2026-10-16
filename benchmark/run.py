#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import subprocess
import sys

from runner.compose import DockerCompose, DockerComposeSettings
from runner.experiment import Experiment
from runner.matrix import Matrix


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="2 workloads, broadband, 1 repeat")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    parser.add_argument("--build", action="store_true", help="build/pull images and exit")
    parser.add_argument("--backend", choices=("nginx", "quiche"), action="append")
    parser.add_argument("--quiche-cc", choices=("cubic", "reno", "bbr", "bbr2"), default="")
    parser.add_argument("--scenario", action="append")
    parser.add_argument("--workload", action="append")
    parser.add_argument("--repeats", type=int)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=3600, help="measured-run deadline, seconds")
    parser.add_argument("--output", type=Path, help="experiment directory; must not already exist")
    parser.add_argument("--nginx", type=Path, help="path to the patched nginx binary (overrides NGINX_BIN)")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    settings = DockerComposeSettings.load(Path(__file__).resolve().parent, nginx=args.nginx)
    matrix = Matrix.from_args(args, settings.benchmark / "scenarios.tsv")

    if args.dry_run:
        print(json.dumps(matrix.to_list(), indent=2))
        return 0

    compose = DockerCompose(settings)
    if args.build:
        compose.build()
        return 0

    return Experiment(settings, matrix, compose).run(
        output=args.output,
        seed=args.seed,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
