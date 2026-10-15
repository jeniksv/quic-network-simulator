import json
from pathlib import Path
import subprocess

SERVICES = ("client", "sim", "server")


class Cell:
    def __init__(self, nginx_conf, scenario, workload, directory):
        self.nginx_conf = nginx_conf
        self.scenario = scenario
        self.workload = workload
        self.directory = Path(directory).resolve()
        self.result = None

    def run(self, compose):
        self.directory.mkdir(parents=True, exist_ok=False)
        for name in ("conf", *SERVICES):
            (self.directory / name).mkdir()

        environment = {
            "RUN_DIR": str(self.directory),
            "SCENARIO": self.scenario.parameters,
            "CLIENT_PARAMS": self.workload.client_params,
        }
        self.result = {
            "config": self.nginx_conf.name,
            "scenario": self.scenario.name,
            "scenario_parameters": self.scenario.parameters,
            "workload": self.workload.name,
            "client_params": self.workload.client_params,
            "status": "failed",
            "errors": [],
        }
        cleanup_failed = False
        try:
            self.nginx_conf.write(self.directory / "conf/nginx.conf")
            compose.validate(environment, self.directory)
            compose.up(environment, self.directory)

            data = json.loads((self.directory / "client/h2load.json").read_text())
            self.workload.check(data["measurements"])
            self.result["status"] = "ok"
        except KeyboardInterrupt:
            self.result["status"] = "interrupted"
        except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
            self.result["errors"].append(str(error))
        finally:
            # Stop before collecting logs, but remove containers only afterwards.
            self._cleanup("stop", compose.stop, environment, self.directory)
            for service in SERVICES:
                self._cleanup(f"{service} logs", compose.logs, service, environment, self.directory)
            while True:
                try:
                    compose.down(environment, self.directory)
                    break
                except KeyboardInterrupt:
                    # Finish removing the stack before propagating Ctrl-C.
                    self.result["status"] = "interrupted"
                except (OSError, subprocess.SubprocessError) as error:
                    cleanup_failed = True
                    self.result["errors"].append(f"down: {error}")
                    break

            if self.result["errors"] and self.result["status"] == "ok":
                self.result["status"] = "failed"
            (self.directory / "result.json").write_text(json.dumps(self.result, indent=2) + "\n")

        if self.result["status"] == "interrupted":
            raise KeyboardInterrupt
        if cleanup_failed:
            raise RuntimeError(f"Compose cleanup failed; see {self.directory / 'result.json'}")
        return self.result["status"] == "ok"

    def _cleanup(self, label, step, *args):
        """Run a best-effort cleanup step, recording an error or Ctrl-C instead of raising."""
        try:
            step(*args)
        except KeyboardInterrupt:
            self.result["status"] = "interrupted"
        except (OSError, subprocess.SubprocessError) as error:
            self.result["errors"].append(f"{label}: {error}")
