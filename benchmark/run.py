#!/usr/bin/env python3

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from runner import DIRECTIVE_TYPES, DockerCompose, Matrix, NginxConf, Scenario


def load_scenarios(path):
    scenarios = []
    names = set()

    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        fields = line.split(None, 1)

        if len(fields) != 2 or fields[0] in names:
            raise ValueError(f"{path}:{number}: expected a unique name and scenario")

        name, parameters = fields
        names.add(name)
        scenarios.append(Scenario(name, parameters))

    return scenarios


def load_configs(path):
    data = json.loads(Path(path).read_text())

    if not isinstance(data, list) or not data:
        raise ValueError(f"{path}: expected a nonempty list of NGINX configurations")

    names = set()
    configs = list()

    for index, config in enumerate(data, 1):
        if not isinstance(config, dict):
            raise ValueError(f"{path}: configuration {index} must be an object")

        name = config.get("name", f"config-{index:03d}")
        if not name:
            raise ValueError(f"{path}: invalid configuration name: {name!r}")

        if name in names:
            raise ValueError(f"{path}: duplicate configuration name: {name!r}")

        names.add(name)

        directives = dict()
        for directive_type in DIRECTIVE_TYPES:
            value = config.get(directive_type.name, directive_type.default)
            if value is not None:
                directives[directive_type.placeholder()] = directive_type(value).render()
            elif directive_type.optional:
                directives[directive_type.placeholder()] = ""
            else:
                raise ValueError(f"{path}: {name}: missing required directive {directive_type.name}")

        configs.append(NginxConf(name, directives))

    return configs


def main():
    benchmark = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Run NGINX configs against simulator scenarios.")
    parser.add_argument("--scenarios", type=Path, default=benchmark / "scenarios.tsv",
                        help="TSV file with simulator scenarios")
    parser.add_argument("--configs", type=Path, default=benchmark / "configs.json",
                        help="JSON array of NGINX configurations (one row per object)")
    parser.add_argument("--defaults", type=Path, default=benchmark / "defaults.env")
    parser.add_argument("--output", type=Path,
                        default=benchmark / "results" / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f"),
                        help="New output directory; existing directories are never overwritten")
    args = parser.parse_args()

    try:
        scenarios = load_scenarios(args.scenarios)
        configs = load_configs(args.configs)
        compose = DockerCompose(benchmark.parent / "docker-compose.yml", args.defaults)
        matrix = Matrix(configs, scenarios, compose, args.output)

        #return 0 if matrix.run() else 1
    except KeyboardInterrupt:
        print("Interrupted; see the output directory for cell logs and results.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
