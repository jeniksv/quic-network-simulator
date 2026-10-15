from pathlib import Path

from .cell import Cell


class Matrix:
    def __init__(self, configs, scenarios, compose, directory):
        self.compose = compose
        self.directory = Path(directory).resolve()
        self.configs = list(configs)
        self.scenarios = list(scenarios)
        self.cells = []
        for row_number, config in enumerate(self.configs, 1):
            row = []
            for column_number, scenario in enumerate(self.scenarios, 1):
                path = self.directory / f"config-{row_number:03d}" / f"scenario-{column_number:03d}"
                row.append(Cell(config, scenario, path))
            self.cells.append(row)
        if not self.cells or not self.cells[0]:
            raise ValueError("Matrix needs at least one config and one scenario")

    def run(self, timeout=300):
        self.directory.mkdir(parents=True, exist_ok=False)
        total = sum(len(row) for row in self.cells)
        number = 0
        success = True
        for row in self.cells:
            for cell in row:
                number += 1
                print(f"[{number}/{total}] {cell.nginx_conf.name} / {cell.scenario.name}", flush=True)
                if not cell.run(self.compose, timeout):
                    success = False
                print(f"  {cell.result['status']}: {cell.directory}", flush=True)
        return success
