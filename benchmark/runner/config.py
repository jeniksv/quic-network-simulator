from dataclasses import dataclass
import os
from pathlib import Path
import re

from .matrix import Trial


@dataclass(frozen=True)
class Settings:
    benchmark: Path
    env: dict[str, str]

    @classmethod
    def load(cls, benchmark: Path, nginx: Path | None = None):
        env = {}
        for line in (benchmark / "defaults.env").read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                key, value = line.split("=", 1)
                env[key] = value
        env.update(os.environ)
        if nginx is not None:
            env["NGINX_BIN"] = str(nginx.resolve())
        return cls(benchmark, env)

    @property
    def root(self) -> Path:
        return self.benchmark.parent

    @property
    def nginx_binary(self) -> Path:
        path = Path(self.env["NGINX_BIN"])
        return path if path.is_absolute() else self.root / path

    @property
    def workers(self) -> str:
        return self.env.get("NGINX_WORKERS") or "auto"

    @property
    def stream_buffer(self) -> str:
        return self.env.get("HTTP3_STREAM_BUFFER_SIZE") or "4m"

    def validate(self):
        if not os.access(self.nginx_binary, os.X_OK):
            raise ValueError(f"Patched NGINX binary not executable: {self.nginx_binary} "
                             "(pass --nginx PATH or set NGINX_BIN, and chmod +x).")
        if not re.fullmatch(r"[1-9][0-9]*|auto", self.workers):
            raise ValueError("NGINX_WORKERS must be a positive integer or 'auto'.")
        if not re.fullmatch(r"[1-9][0-9]*[kKmM]?", self.stream_buffer):
            raise ValueError("HTTP3_STREAM_BUFFER_SIZE must be a positive integer "
                             "with an optional k/m suffix.")


class NginxConfig:
    server_params = "-c /logs/nginx.conf"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.template = (settings.benchmark / "conf/nginx.conf.template").read_text()

    def write(self, trial: Trial, directory: Path):
        config = self.template
        values = {
            "__BACKEND__": trial.backend,
            "__CC__": trial.cc,
            "__WORKERS__": self.settings.workers,
            "__BUFFER__": self.settings.stream_buffer,
        }

        for placeholder, value in values.items():
            config = config.replace(placeholder, value)
        (directory / "server/nginx.conf").write_text(config)
