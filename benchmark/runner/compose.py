import subprocess

from .config import Settings


class DockerCompose:
    def __init__(self, settings: Settings):
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
