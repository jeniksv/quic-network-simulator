import json
from pathlib import Path
import subprocess
import time


class Cell:
    def __init__(self, nginx_conf, scenario, directory):
        self.nginx_conf = nginx_conf
        self.scenario = scenario
        self.directory = Path(directory).resolve()
        self.result = None

    def run(self, compose, timeout=300):
        self.directory.mkdir(parents=True, exist_ok=False)
        for name in ("conf", "client", "sim", "server"):
            (self.directory / name).mkdir()

        environment = {
            "RUN_DIR": str(self.directory),
            "SCENARIO": self.scenario.parameters,
        }
        self.result = {
            "config": self.nginx_conf.name,
            "scenario": self.scenario.name,
            "scenario_parameters": self.scenario.parameters,
            "status": "failed",
            "errors": [],
        }
        started = time.monotonic()
        cleanup_failed = False
        try:
            self.nginx_conf.write(self.directory / "conf/nginx.conf")
            compose.validate(environment, self.directory, timeout)
            compose.up(environment, self.directory, timeout)

            data = json.loads((self.directory / "client/h2load.json").read_text())
            measurements = data["measurements"]
            self.result["measurements"] = measurements
            requests = measurements["requests"]
            total = requests["total"]
            if total <= 0 or any(requests[key] != total for key in ("started", "done", "succeeded")):
                raise ValueError("h2load did not successfully complete all requests")
            if any(requests[key] != 0 for key in ("failed", "errored", "timeout")):
                raise ValueError("h2load reported failed requests")
            if measurements["status_codes"]["2xx"] != total:
                raise ValueError("Not all responses have a 2xx status")
            self.result["status"] = "ok"
        except KeyboardInterrupt:
            self.result["status"] = "interrupted"
        except subprocess.TimeoutExpired:
            self.result["status"] = "timeout"
            self.result["errors"].append(f"Command exceeded {timeout} seconds")
        except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
            self.result["errors"].append(str(error))
        finally:
            # Stop before collecting logs, but remove containers only afterwards.
            try:
                compose.stop(environment, self.directory)
            except KeyboardInterrupt:
                self.result["status"] = "interrupted"
            except (OSError, subprocess.SubprocessError) as error:
                self.result["errors"].append(f"stop: {error}")
            for service in ("client", "sim", "server"):
                try:
                    compose.logs(service, environment, self.directory)
                except KeyboardInterrupt:
                    self.result["status"] = "interrupted"
                except (OSError, subprocess.SubprocessError) as error:
                    self.result["errors"].append(f"{service} logs: {error}")
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
            self.result["elapsed_seconds"] = time.monotonic() - started
            (self.directory / "result.json").write_text(json.dumps(self.result, indent=2) + "\n")

        if self.result["status"] == "interrupted":
            raise KeyboardInterrupt
        if cleanup_failed:
            raise RuntimeError(f"Compose cleanup failed; see {self.directory / 'result.json'}")
        return self.result["status"] == "ok"
