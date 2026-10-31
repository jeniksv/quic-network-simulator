from itertools import product
from pathlib import Path
from random import Random
import secrets

from .cell import Cell


class Matrix:
    def __init__(self, configs, scenarios, workloads, compose, directory, repetitions=1, seed=None):
        if repetitions < 1:
            raise ValueError(f"Number of repetitions must be at least 1, got {repetitions}")

        self.compose = compose
        self.directory = Path(directory).resolve()
        self.seed = secrets.randbits(32) if seed is None else seed
        rng = Random(self.seed)
        configs = list(configs)
        combinations = list(product(scenarios, workloads))
        runs = [
            (config, scenario, workload, repetition)
            for repetition in range(1, repetitions + 1)
            for scenario, workload in combinations
            for config in rng.sample(configs, len(configs))
        ]
        self.cells = [
            Cell(config, scenario, workload, repetition, run_order, self.seed,
                 self.directory / config.name / scenario.name / workload.name / f"r{repetition}")
            for run_order, (config, scenario, workload, repetition) in enumerate(runs, 1)
        ]

    def run(self):
        self.directory.mkdir(parents=True, exist_ok=False)
        print(f"Seed: {self.seed}", flush=True)
        success = True

        for number, cell in enumerate(self.cells, 1):
            print(f"[{number}/{len(self.cells)}] {cell.nginx_conf.name} / {cell.scenario.name} / "
                  f"{cell.workload.name} / r{cell.repetition}", flush=True)
            if not cell.run(self.compose):
                success = False
            print(f"  {cell.result['status']}: {cell.directory}", flush=True)

        return success
