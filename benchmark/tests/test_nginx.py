"""Check per-case configuration ownership and invalid directive handling."""
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

BENCHMARK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCHMARK))

from runner.matrix import Matrix
from runner.nginx import NginxConfig, NginxDirective


class NginxConfigTests(unittest.TestCase):
    def test_matrix_cases_own_configs_matching_their_axes(self):
        args = SimpleNamespace(quick=True, scenario=None, workload=None,
                               repeats=2, seed=0, backend=None, quiche_cc="bbr2")
        matrix = Matrix.from_args(args, BENCHMARK / "scenarios.tsv")
        self.assertEqual(len(matrix.cases), 8)
        self.assertEqual(len({id(case.nginx_config) for case in matrix.cases}), 8)
        template = (BENCHMARK / "conf/nginx.conf.template").read_text()
        for case in matrix.cases:
            config = case.nginx_config.render(template)
            for address in ("443", "[::]:443"):
                self.assertIn(f"listen {address} quic={case.backend} reuseport;", config)
            self.assertIn(f"quic_congestion_control {case.cc};", config)
            self.assertNotIn("__", config)
            self.assertNotIn("nginx_config", case.to_dict())
        with self.assertRaises(FrozenInstanceError):
            matrix.cases[0].nginx_config.directives = ()

    def test_invalid_values_are_rejected_at_construction(self):
        for name, value in (
            ("listen", "443 quic=unknown reuseport"),
            ("listen", "443 quic=quiche"),
            ("listen", "443 quic=nginx reuseport; access_log off"),
            ("quic_congestion_control", "unknown"),
            ("quic_congestion_control", "cubic\nerror_log /tmp/log"),
            ("quic_congestion_control", "cubic;"),
            ("quic_congestion_control", "cubic\n"),
            ("quic_congestion_control", ""),
        ):
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                NginxDirective(name, value)
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            NginxDirective("unknown", "on")

    def test_render_preserves_repeated_directives_and_template_indentation(self):
        config = NginxConfig((
            NginxDirective("listen", "443 quic=quiche reuseport"),
            NginxDirective("listen", "[::]:443 quic=quiche reuseport"),
        ))
        self.assertEqual(config.render("server {\n    __LISTEN__\n}\n"),
                         "server {\n    listen 443 quic=quiche reuseport;\n"
                         "    listen [::]:443 quic=quiche reuseport;\n}\n")

    def test_render_rejects_missing_or_unused_placeholders(self):
        config = NginxConfig((NginxDirective("quic_congestion_control", "cubic"),))
        for template in ("http3 on;\n", "__LISTEN__\n",
                         "__QUIC_CONGESTION_CONTROL__\n__UNKNOWN__\n",
                         "__QUIC_CONGESTION_CONTROL__\nlisten __UNKNOWN__;\n"):
            with self.subTest(template=template), self.assertRaises(ValueError):
                config.render(template)

    def test_render_rejects_duplicate_congestion_control(self):
        config = NginxConfig((
            NginxDirective("quic_congestion_control", "cubic"),
            NginxDirective("quic_congestion_control", "bbr2"),
        ))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            config.render("__QUIC_CONGESTION_CONTROL__\n")


if __name__ == "__main__":
    unittest.main()
