from itertools import product
from pathlib import Path

from .cell import Cell


class Matrix:
    def __init__(self, configs, scenarios, workloads, compose, directory, repetitions=1):
        if repetitions < 1:
            raise ValueError(f"Number of repetitions must be at least 1, got {repetitions}")

        self.compose = compose
        self.directory = Path(directory).resolve()
        combinations = list(product(configs, scenarios, workloads))
        self.cells = [
            Cell(config, scenario, workload, repetition,
                 self.directory / config.name / scenario.name / workload.name / f"r{repetition}")
            for repetition in range(1, repetitions + 1)
            for config, scenario, workload in combinations
        ]

    def run(self):
        self.directory.mkdir(parents=True, exist_ok=False)
        success = True

        for number, cell in enumerate(self.cells, 1):
            print(f"[{number}/{len(self.cells)}] {cell.nginx_conf.name} / {cell.scenario.name} / "
                  f"{cell.workload.name} / r{cell.repetition}", flush=True)
            if not cell.run(self.compose):
                success = False
            print(f"  {cell.result['status']}: {cell.directory}", flush=True)

        return success
