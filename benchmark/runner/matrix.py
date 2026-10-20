from pathlib import Path

from .cell import Cell


class Matrix:
    def __init__(self, configs, scenarios, compose, directory):
        self.compose = compose
        self.directory = Path(directory).resolve()
        self.configs = list(configs)
        self.scenarios = list(scenarios)
        self.cells = []
        for config in self.configs:
            row = []
            for scenario in self.scenarios:
                path = self.directory / config.name / scenario.name
                row.append(Cell(config, scenario, path))
            self.cells.append(row)
        if not self.cells or not self.cells[0]:
            raise ValueError("Matrix needs at least one config and one scenario")

    def run(self):
        self.directory.mkdir(parents=True, exist_ok=False)
        total = sum(len(row) for row in self.cells)
        number = 0
        success = True
        for row in self.cells:
            for cell in row:
                number += 1
                print(f"[{number}/{total}] {cell.nginx_conf.name} / {cell.scenario.name}", flush=True)
                if not cell.run(self.compose):
                    success = False
                print(f"  {cell.result['status']}: {cell.directory}", flush=True)
        return success
