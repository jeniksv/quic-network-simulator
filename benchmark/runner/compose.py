import os
from pathlib import Path
import subprocess


class DockerCompose:
    def __init__(self, compose_file, defaults_file):
        self.compose_file = Path(compose_file).resolve()
        self.defaults_file = Path(defaults_file).resolve()
        self.project = f"qns-benchmark-{os.getpid()}"

    def _run(self, arguments, environment, log_path):
        command = [
            "docker", "compose",
            "--file", str(self.compose_file),
            "--env-file", str(self.defaults_file),
            "--project-name", self.project,
        ] + arguments
        env = os.environ.copy()
        env.update(environment)
        with Path(log_path).open("ab") as log:
            return subprocess.run(
                command, cwd=self.compose_file.parent, env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                check=True,
            )

    def validate(self, environment, directory):
        self._run([
            "run", "--rm", "--no-deps", "-T",
            "--entrypoint", "/usr/local/nginx/sbin/nginx", "server",
            "-t", "-e", "stderr", "-c", "/usr/local/nginx/conf/nginx.conf",
        ], environment, directory / "nginx-test.log")

    def up(self, environment, directory):
        self._run([
            "up", "--no-build", "--abort-on-container-exit",
            "--exit-code-from", "client",
        ], environment, directory / "compose.log")

    def stop(self, environment, directory):
        self._run(["stop", "--timeout", "5"], environment, directory / "compose.log")

    def logs(self, service, environment, directory):
        self._run([
            "logs", "--no-color", "--no-log-prefix", service,
        ], environment, directory / service / "console.log")

    def down(self, environment, directory):
        # Include a validation container left behind by an interrupted `run`.
        self._run(["down", "--remove-orphans", "--timeout", "5"],
                  environment, directory / "compose.log")
