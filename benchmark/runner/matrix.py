from itertools import product
from pathlib import Path

from .cell import Cell


class Matrix:
    def __init__(self, configs, scenarios, workloads, compose, directory):
        self.compose = compose
        self.directory = Path(directory).resolve()
        self.configs = list(configs)
        self.scenarios = list(scenarios)
        self.workloads = list(workloads)
        self.cells = list()

        for config, scenario, workload in product(self.configs, self.scenarios, self.workloads):
            path = self.directory / config.name / scenario.name / workload.name
            self.cells.append(Cell(config, scenario, workload, path))

        if not self.cells:
            raise ValueError("Matrix needs at least one config, one scenario and one workload")

    def run(self):
        self.directory.mkdir(parents=True, exist_ok=False)
        success = True

        for number, cell in enumerate(self.cells, 1):
            print(f"[{number}/{len(self.cells)}] {cell.nginx_conf.name} / {cell.scenario.name} / {cell.workload.name}",
                  flush=True)
            if not cell.run(self.compose):
                success = False
            print(f"  {cell.result['status']}: {cell.directory}", flush=True)

       return success
