"""Exercise the public CLI and server entrypoint using subprocess fixtures."""
import csv
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

BENCHMARK = Path(__file__).resolve().parents[1]


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quic-benchmark-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.benchmark = self.root / "benchmark"
        self.benchmark.mkdir(parents=True)
        for name in ("run.py", "defaults.env", "scenarios.tsv"):
            shutil.copy2(BENCHMARK / name, self.benchmark / name)
        for name in ("runner", "conf"):
            shutil.copytree(BENCHMARK / name, self.benchmark / name,
                            ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(BENCHMARK.parent / "docker-compose.yml", self.root)
        certs = self.benchmark / "certs"
        certs.mkdir()
        # No TLS handshake occurs in these tests; avoid an OpenSSL dependency.
        (certs / "cert.crt").write_text("test certificate")
        (certs / "cert.key").write_text("test private key")
        binaries = self.root / "bin"
        binaries.mkdir()
        self.calls_file = self.root / "docker-calls.jsonl"
        self.nginx = binaries / "nginx"
        self.nginx.write_text(
            f"#!{sys.executable}\nimport json, os, sys\n"
            "with open(os.environ['TEST_NGINX_ARGS'], 'a') as fh:\n"
            "    fh.write(json.dumps({'args': sys.argv[1:], 'pid': os.getpid()}) + '\\n')\n"
            "sys.exit(23)\n")
        self.nginx.chmod(0o755)
        shutil.copy2(BENCHMARK / "tests/fake_docker.py", binaries / "docker")
        (binaries / "docker").chmod(0o755)
        self.env = dict(os.environ, PATH=f"{binaries}:{os.environ['PATH']}",
                        TEST_DOCKER_CALLS=str(self.calls_file),
                        NGINX_WORKERS="2", HTTP3_STREAM_BUFFER_SIZE="64k")
        self.output = self.root / "experiment"

    def invoke(self, *args, mode="ok"):
        return subprocess.run([sys.executable, str(self.benchmark / "run.py"),
                               "--nginx", str(self.nginx), *args],
                              cwd=self.root, env=dict(self.env, TEST_DOCKER_MODE=mode),
                              capture_output=True, text=True, timeout=15)

    def run_cells(self, *args, mode="ok"):
        return self.invoke("--scenario", "broadband", "--workload", "tiny-1k",
                           "--repeats", "1", "--output", str(self.output), *args, mode=mode)

    def calls(self):
        return [json.loads(line) for line in self.calls_file.read_text().splitlines()]

    def rows(self):
        with (self.output / "results.csv").open() as fh:
            return list(csv.DictReader(fh))

    def test_dry_run_does_not_start_docker_or_prepare_payloads(self):
        full = self.invoke("--dry-run")
        quick = self.invoke("--quick", "--dry-run")
        self.assertEqual(full.returncode, 0, full.stderr)
        self.assertEqual(quick.returncode, 0, quick.stderr)
        self.assertEqual(len(json.loads(full.stdout)), 144)
        self.assertEqual(len(json.loads(quick.stdout)), 4)
        self.assertFalse(self.calls_file.exists())
        self.assertFalse((self.benchmark / "www").exists())

    def test_cells_and_repetitions_have_independent_configs_and_logs(self):
        result = self.run_cells("--repeats", "2", "--quiche-cc", "bbr2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = self.rows()
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({row["run_dir"] for row in rows}), 4)
        for row in rows:
            directory = self.output / row["run_dir"]
            config = (directory / "server/nginx.conf").read_text()
            self.assertIn(f"listen 443 quic={row['backend']} reuseport;", config)
            cc = "bbr2" if row["backend"] == "quiche" else "cubic"
            for directive in (f"quic_congestion_control {cc};", "worker_processes 2;",
                              "http3_stream_buffer_size 64k;", "daemon off;",
                              "error_log /logs/error.log warn;", "pid /tmp/nginx.pid;",
                              "lock_file /tmp/nginx.lock;",
                              "client_body_temp_path /tmp/client_body_temp;",
                              "proxy_temp_path /tmp/proxy_temp;",
                              "fastcgi_temp_path /tmp/fastcgi_temp;",
                              "uwsgi_temp_path /tmp/uwsgi_temp;",
                              "scgi_temp_path /tmp/scgi_temp;"):
                self.assertIn(directive, config)
            self.assertEqual((directory / "server/error.log").read_text(), row["run_dir"])
            self.assertEqual(row["status"], "ok")
            self.assertEqual(json.loads((directory / "result.json").read_text())["status"], "ok")
            self.assertTrue((directory / "cleanup.log").exists())
        metadata = json.loads((self.output / "metadata.json").read_text())
        self.assertEqual(len(metadata["plan"]), 4)
        self.assertTrue(metadata["inputs"])
        up = [call for call in self.calls() if "up" in call["args"]]
        self.assertEqual(len({call["run_dir"] for call in up}), 4)
        # Existing experiments must never be silently overwritten.
        saved = (self.output / "results.csv").read_bytes()
        repeated = self.run_cells()
        self.assertNotEqual(repeated.returncode, 0)
        self.assertEqual((self.output / "results.csv").read_bytes(), saved)

    def test_failed_client_still_cleans_up_and_saves_results(self):
        result = self.run_cells("--backend", "nginx", mode="failed")
        self.assertEqual(result.returncode, 1)
        row = self.rows()[0]
        self.assertEqual(row["status"], "failed")
        self.assertIn("client/compose exited 17", row["error"])
        self.assertEqual(sum("down" in call["args"] for call in self.calls()), 2)
        self.assertTrue((self.output / row["run_dir"] / "server/nginx.conf").exists())

    def test_incorrect_body_byte_count_is_not_a_success(self):
        result = self.run_cells("--backend", "quiche", mode="bad-body")
        self.assertEqual(result.returncode, 1)
        self.assertIn("body_bytes=", self.rows()[0]["error"])

    def test_timeout_preserves_partial_output_and_cleans_up(self):
        result = self.run_cells("--backend", "nginx", "--timeout", "0.3", mode="timeout")
        self.assertEqual(result.returncode, 1)
        row = self.rows()[0]
        self.assertIn("timed out", row["error"])
        output = (self.output / row["run_dir"] / "compose.log").read_text()
        self.assertIn("client starting", output)
        self.assertIn("partial stderr", output)
        self.assertEqual(sum("down" in call["args"] for call in self.calls()), 2)

    def test_build_only_builds_shared_endpoint_and_pulls_simulator(self):
        result = self.invoke("--build")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call["args"][5:] for call in self.calls()],
                         [["build", "server"], ["pull", "sim"]])
        self.assertFalse((self.benchmark / "www").exists())

    def test_server_forwards_arguments_once(self):
        setup = self.root / "setup.sh"
        setup.write_text("#!/bin/sh\nexit 0\n")
        setup.chmod(0o755)
        args_file = self.root / "nginx-args.jsonl"
        source = (BENCHMARK.parent / "endpoint/run_endpoint.sh").read_text()
        source = source.replace("/setup.sh", shlex.quote(str(setup)))
        source = source.replace("mkdir -p /logs", f"mkdir -p {shlex.quote(str(self.root / 'logs'))}")
        source = source.replace("NGINX_BIN=/opt/nginx-bin/nginx", f"NGINX_BIN={shlex.quote(str(self.nginx))}")
        endpoint = self.root / "run_endpoint.sh"
        endpoint.write_text(source)
        expected = ["-c", "/logs/nginx.conf"]
        env = dict(self.env, ROLE="server", SERVER_PARAMS=" ".join(expected),
                   TEST_NGINX_ARGS=str(args_file))
        with subprocess.Popen(["bash", str(endpoint)], cwd=self.root, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 23, stdout + stderr)
            recorded = [json.loads(line) for line in args_file.read_text().splitlines()]
            self.assertEqual(len(recorded), 1)
            self.assertEqual(recorded[0]["args"], expected)


if __name__ == "__main__":
    unittest.main()
