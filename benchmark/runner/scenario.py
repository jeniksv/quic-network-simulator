from pathlib import Path


class Scenario:
    def __init__(self, name, parameters):
        self.name = name
        self.parameters = parameters


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
