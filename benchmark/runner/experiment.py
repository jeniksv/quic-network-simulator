import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import random
import subprocess
import uuid

from .compose import DockerCompose
from .config import NginxConfig, Settings
from .matrix import Matrix, PAYLOAD_SIZES, Trial
from .metrics import parse_output, validate


def write_json(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class TrialRunner:
    def __init__(self, settings: Settings, compose: DockerCompose, timeout: float):
        self.settings, self.compose, self.timeout = settings, compose, timeout
        self.config = NginxConfig(settings)

    def run(self, index: int, trial: Trial, directory: Path) -> dict:
        directory.mkdir()
        for name in ("sim", "server", "client"):
            (directory / name).mkdir()
        self.config.write(trial, directory)
        payload_bytes = (self.settings.benchmark / "www" / trial.payload).stat().st_size
        env = dict(self.settings.env, RUN_DIR=str(directory), SCENARIO=trial.scenario_params,
                   SERVER_PARAMS=self.config.server_params, CLIENT_PARAMS=trial.client_params)
        row = dict(trial.to_dict(), index=index, status="failed", error="",
                   client_params=trial.client_params, run_dir=directory.name,
                   started_utc=datetime.now(timezone.utc).isoformat())
        errors = []
        try:
            self.compose.down(env)
            up = self.compose.up(env, self.timeout)
            (directory / "compose.log").write_text(up.stdout + up.stderr)
            row["client_exit_code"] = up.returncode
            if up.returncode:
                errors.append(f"client/compose exited {up.returncode}")
        except subprocess.TimeoutExpired as exc:
            output = [part.decode(errors="replace") if isinstance(part, bytes) else part or ""
                      for part in (exc.stdout, exc.stderr)]
            (directory / "compose.log").write_text("".join(output))
            errors.append(f"timed out after {self.timeout:g}s")
        except (OSError, RuntimeError) as exc:
            errors.append(str(exc))
        finally:
            down = self.compose.down(env)
            (directory / "cleanup.log").write_text(down.stdout + down.stderr)
        try:
            result = parse_output(directory / "client/h2load.json")
            row.update(result)
            errors.extend(validate(result, trial.n, trial.n * payload_bytes))
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            errors.append(f"metrics: {exc}")
        row["error"] = "; ".join(e for e in errors if e)
        row["status"] = "failed" if row["error"] else "ok"
        row["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(directory / "result.json", row)
        return row


class Experiment:
    def __init__(self, settings: Settings, matrix: Matrix, compose: DockerCompose):
        self.settings, self.matrix, self.compose = settings, matrix, compose

    def prepare_inputs(self):
        benchmark = self.settings.benchmark
        (benchmark / "certs").mkdir(exist_ok=True)
        (benchmark / "www").mkdir(exist_ok=True)
        (benchmark / "www").chmod(0o755)
        cert, key = benchmark / "certs/cert.crt", benchmark / "certs/cert.key"
        if cert.exists() != key.exists():
            raise ValueError("Both cert.crt and cert.key must exist, or neither.")
        if not cert.exists():
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                            "-days", "3650", "-subj", "/CN=server",
                            "-keyout", str(key), "-out", str(cert)], check=True)
            key.chmod(0o600)
        for name in self.payloads():
            size, path = PAYLOAD_SIZES[name], benchmark / "www" / name
            if path.exists():
                if path.stat().st_size != size:
                    raise ValueError(f"Unexpected payload size: {path}")
                continue
            rng = random.Random(0)
            with path.open("xb") as fh:
                remaining = size
                while remaining:
                    chunk = min(remaining, 1024 * 1024)
                    fh.write(rng.randbytes(chunk))
                    remaining -= chunk
            path.chmod(0o644)

    def payloads(self) -> list[str]:
        return sorted({"1k.bin"} | {trial.payload for trial in self.matrix.trials})

    def provenance(self) -> dict:
        settings = self.settings
        info = json.loads(self.compose.command(["docker", "info", "--format", "{{json .}}"]).stdout)
        inspected = self.compose.command(
            ["docker", "image", "inspect", settings.env["SIM_IMAGE"], settings.env["SERVER"]],
            check=False).stdout
        images = json.loads(inspected) if inspected.strip() else []
        inputs = [settings.nginx_binary, settings.benchmark / "certs/cert.crt",
                  *[settings.benchmark / "www" / name for name in self.payloads()]]
        hashes = {}
        for path in inputs:
            if path.is_file():
                name = str(path.relative_to(settings.root)) if path.is_relative_to(settings.root) else str(path)
                hashes[name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
        return {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "git_head": self.compose.command(["git", "rev-parse", "HEAD"], check=False).stdout.strip(),
            "git_status": self.compose.command(["git", "status", "--porcelain"], check=False).stdout,
            "host": platform.uname()._asdict(),
            "docker": {k: info.get(k) for k in ("ServerVersion", "KernelVersion", "NCPU", "MemTotal", "OSType")},
            "images": [{k: img.get(k) for k in ("Id", "RepoTags", "Created", "Architecture", "Os")} for img in images],
            "inputs": hashes,
            "settings": {k: settings.env.get(k, "") for k in ("NGINX_WORKERS", "HTTP3_STREAM_BUFFER_SIZE")},
            "plan": self.matrix.to_list(),
        }

    @staticmethod
    def save_results(directory: Path, rows: list[dict]):
        fields = list(dict.fromkeys(key for row in rows for key in row))
        tmp = directory / "results.csv.tmp"
        with tmp.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        tmp.replace(directory / "results.csv")

    def run(self, *, output: Path | None, seed: int, timeout: float) -> int:
        self.prepare_inputs()
        self.settings.validate()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        directory = (output or self.settings.benchmark / "results" / stamp).resolve()
        directory.mkdir(parents=True, exist_ok=False)
        write_json(directory / "metadata.json", dict(self.provenance(), seed=seed, timeout_s=timeout))
        total = len(self.matrix.trials)
        print(f"Experiment: {directory}\n{total} trials", flush=True)
        runner, rows = TrialRunner(self.settings, self.compose, timeout), []
        for index, trial in enumerate(self.matrix.trials, 1):
            label = trial.label(index)
            print(f"[{index}/{total}] {label}", flush=True)
            try:
                row = runner.run(index, trial, directory / label)
            except KeyboardInterrupt:
                print("interrupted; tearing down", flush=True)
                self.compose.down()
                return 130
            rows.append(row)
            self.save_results(directory, rows)
            summary = row["error"] or f"{row.get('body_goodput_MBps', 0):.3f} MB/s"
            print(f"  {row['status']}: {summary}", flush=True)
        print(f"Results: {directory / 'results.csv'}", flush=True)
        return int(any(row["status"] != "ok" for row in rows))
