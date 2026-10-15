from pathlib import Path

from .matrix import Trial


class NginxConfig:
    server_params = "-c /logs/nginx.conf"

    def __init__(self, benchmark: Path):
        self.template = (benchmark / "conf/nginx.conf.template").read_text()

    def write(self, trial: Trial, directory: Path):
        config = self.template
        values = {
            "__BACKEND__": trial.backend,
            "__CC__": trial.cc,
        }

        for placeholder, value in values.items():
            config = config.replace(placeholder, value)
        (directory / "server/nginx.conf").write_text(config)
