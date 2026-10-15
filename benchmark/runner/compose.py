from dataclasses import dataclass
import os
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class DockerComposeSettings:
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

    def validate(self):
        if not os.access(self.nginx_binary, os.X_OK):
            raise ValueError(f"Patched NGINX binary not executable: {self.nginx_binary} "
                             "(pass --nginx PATH or set NGINX_BIN, and chmod +x).")


class DockerCompose:
    def __init__(self, settings: DockerComposeSettings):
        self.settings = settings

    def command(self, args, *, env=None, timeout=120, check=True):
        result = subprocess.run([str(a) for a in args], cwd=self.settings.root,
                                env=self.settings.env if env is None else env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(map(str, args))}\n"
                               f"{result.stdout}{result.stderr}")
        return result

    def run(self, *args, env=None, timeout=120, check=True):
        return self.command(["docker", "compose", "--env-file",
                            self.settings.benchmark / "defaults.env", "-f",
                            self.settings.root / "docker-compose.yml", *args],
                            env=env, timeout=timeout, check=check)

    def build(self):
        self.run("build", "server", timeout=7200)
        self.run("pull", "sim", timeout=1200)

    def down(self, env=None):
        return self.run("down", "--remove-orphans", env=env, check=False)

    def up(self, env, timeout):
        return self.run("up", "--no-build", "--abort-on-container-exit",
                        "--exit-code-from", "client", env=env, timeout=timeout, check=False)
