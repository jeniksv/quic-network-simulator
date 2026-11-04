from dataclasses import dataclass


@dataclass
class Workload:
    name: str
    client_params: str

    def check(self, measurements):
        requests = measurements["requests"]
        total = requests["total"]

        if total <= 0 or any(requests[key] != total for key in ("started", "done", "succeeded")):
            raise ValueError("h2load did not successfully complete all requests")
        if any(requests[key] != 0 for key in ("failed", "errored", "timeout")):
            raise ValueError("h2load reported failed requests")
        if measurements["status_codes"]["2xx"] != total:
            raise ValueError("Not all responses have a 2xx status")
