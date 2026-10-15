from dataclasses import asdict, dataclass
from pathlib import Path
import random


@dataclass(frozen=True)
class Workload:
    n: int
    c: int
    m: int
    payload: str


WORKLOADS = {
    "bulk-10M": Workload(200, 1, 1, "10M.bin"),
    "bulk-100M": Workload(20, 1, 1, "100M.bin"),
    "web-100k": Workload(5000, 50, 10, "100k.bin"),
    "tiny-1k": Workload(20000, 100, 10, "1k.bin"),
}
QUICK_WORKLOADS = {
    "q-bulk-10M": Workload(30, 1, 1, "10M.bin"),
    "q-web-100k": Workload(1500, 20, 10, "100k.bin"),
}
PAYLOAD_SIZES = {"1k.bin": 1024, "100k.bin": 100 * 1024,
                 "10M.bin": 10 * 1024**2, "100M.bin": 100 * 1024**2}


@dataclass(frozen=True)
class Trial:
    backend: str
    cc: str
    scenario: str
    scenario_params: str
    workload: str
    repetition: int
    n: int
    c: int
    m: int
    payload: str

    def to_dict(self) -> dict:
        return asdict(self)

    def label(self, index: int) -> str:
        return f"{index:04d}-{self.backend}-{self.scenario}-{self.workload}-r{self.repetition}"

    @property
    def client_params(self) -> str:
        return (f"-n{self.n} -c{self.c} -m{self.m} "
                f"--alpn-list=h3 https://server46/{self.payload}")


@dataclass(frozen=True)
class Matrix:
    trials: tuple[Trial, ...]

    @classmethod
    def from_args(cls, args, scenarios_file: Path):
        scenarios = {}
        for line in scenarios_file.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                name, scenario = line.split(None, 1)
                scenarios[name] = scenario.strip()
        workloads = QUICK_WORKLOADS if args.quick else WORKLOADS
        selected_scenarios = args.scenario or (["broadband"] if args.quick else list(scenarios))
        selected_workloads = args.workload or list(workloads)
        for label, selected, available in (("scenario", selected_scenarios, scenarios),
                                           ("workload", selected_workloads, workloads)):
            unknown = set(selected) - available.keys()
            if unknown:
                raise ValueError(f"Unknown {label}(s): {', '.join(sorted(unknown))}; "
                                 f"choose from {', '.join(available)}")
        repeats = args.repeats if args.repeats is not None else (1 if args.quick else 3)
        if repeats < 1:
            raise ValueError("--repeats must be positive")
        rng, trials = random.Random(args.seed), []
        for repetition in range(1, repeats + 1):
            for scenario in selected_scenarios:
                for workload in selected_workloads:
                    backends = list(dict.fromkeys(args.backend or ["nginx", "quiche"]))
                    rng.shuffle(backends)
                    for backend in backends:
                        trials.append(Trial(
                            backend=backend,
                            cc=(args.quiche_cc or "cubic") if backend == "quiche" else "cubic",
                            scenario=scenario, scenario_params=scenarios[scenario],
                            workload=workload, repetition=repetition,
                            **asdict(workloads[workload])))
        return cls(tuple(trials))

    def to_list(self) -> list[dict]:
        return [trial.to_dict() for trial in self.trials]
