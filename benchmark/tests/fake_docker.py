#!/usr/bin/env python3
"""Small subprocess fixture for exercising the runner without a Docker daemon."""
import json
import os
from pathlib import Path
import re
import shlex
import sys
import time
from urllib.parse import urlparse

args = sys.argv[1:]
with Path(os.environ["TEST_DOCKER_CALLS"]).open("a") as fh:
    fh.write(json.dumps({"args": args, "run_dir": os.environ.get("RUN_DIR"),
                         "server_params": os.environ.get("SERVER_PARAMS")}) + "\n")
if args[0] == "info":
    print(json.dumps({"ServerVersion": "test", "NCPU": 1}))
elif args[:2] == ["image", "inspect"]:
    print(json.dumps([{"Id": "test-image", "RepoTags": args[2:]}]))
elif args[0] == "compose":
    assert args[1] == "--env-file" and args[3] == "-f", args
    action = args[5]
    if action == "up":
        assert args[6:] == ["--no-build", "--abort-on-container-exit", "--exit-code-from", "client"]
        directory = Path(os.environ["RUN_DIR"])
        config = (directory / "server/nginx.conf").read_text()
        assert "__" not in config and "daemon off;" in config
        assert shlex.split(os.environ["SERVER_PARAMS"]) == ["-c", "/logs/nginx.conf"]
        error_path = re.search(r"error_log\s+(\S+)", config).group(1)
        assert error_path.startswith("/logs/")
        (directory / "server" / error_path.removeprefix("/logs/")).write_text(directory.name)
        print("client starting", flush=True)
        mode = os.environ.get("TEST_DOCKER_MODE", "ok")
        if mode == "failed":
            sys.exit(17)
        if mode == "timeout":
            print("partial stderr", file=sys.stderr, flush=True)
            time.sleep(5)
        params = shlex.split(os.environ["CLIENT_PARAMS"])
        n = int(next(p[2:] for p in params if p.startswith("-n")))
        payload = Path(urlparse(params[-1]).path).name
        size = (Path.cwd() / "benchmark/www" / payload).stat().st_size
        body = n * size - (1 if mode == "bad-body" else 0)
        measurements = {
            "duration": 1, "request_per_second": n, "udp_datagram": {},
            "requests": {"total": n, "started": n, "done": n, "succeeded": n,
                         "failed": 0, "errored": 0, "timeout": 0},
            "status_codes": {"2xx": n, "3xx": 0, "4xx": 0, "5xx": 0},
            "traffic": {"data": body, "total": body + n * 100, "headers": n * 100},
            "performance": {"request": {"mean": .01, "median": .009, "p95": .02, "p99": .03},
                            "ttfb": {"mean": .004}},
        }
        (directory / "client/h2load.json").write_text(json.dumps({"measurements": measurements}))
    elif action not in ("down", "build", "pull"):
        raise AssertionError(args)
else:
    raise AssertionError(args)
