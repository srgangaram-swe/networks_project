import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

from analysis import diagnostic_report as report
from src.artifacts import digest, read_json
from src.basic_rpc_protocol.rpc_metrics import RpcCallRecord
from src.basic_rpc_protocol.rpc_workload import RpcWorkloadConfig, _results


class DiagnosticReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_loopback_tables_figures_and_failure_totals_agree(self):
        row = {
            "measurement_kind": "loopback_diagnostic",
            "transport": "udp",
            "scheduled": 1000,
            "sent": 990,
            "on_time": 980,
            "timeout_count": 10,
            "not_sent": 10,
            "not_sent_rate": 0.01,
            "p99_ms": 2.5,
            "manifest_sha256": "a" * 64,
            "requested_mbps": 110,
        }
        with patch.object(report, "summarize", return_value=(row, [])):
            totals = report.analyze_loopback([self.root], self.root / "loopback")
        self.assertEqual(totals["timeout_count"], 10)
        self.check_files(self.root / "loopback")
        with patch.object(
            report, "summarize", return_value=({**row, "measurement_kind": "simulation"}, [])
        ):
            with self.assertRaises(ValueError):
                report.analyze_loopback([self.root], self.root / "rejected")
        with self.assertRaises(ValueError):
            report.analyze_loopback([], self.root / "empty")

    def test_rpc_tables_keep_application_durations_and_capacity_omissions(self):
        future = Future()
        future.set_result((RpcCallRecord(1, 1, 1, 0, 2_000_000, "completed"), {}, 0, False))
        config = RpcWorkloadConfig(requests_per_second=2, measurement_seconds=1)
        raw = _results(config, 1, 2, 0, [future], 1, "completed")

        def read(path, *args):
            if path.name == "rpc.json":
                return raw
            if path.name == "configuration.json":
                return {"mode": "loopback", "policy": "none", "aggregate_bps": 0}
            return {"goodput_mbps": 0}

        with (
            patch.object(report, "read_json", side_effect=read),
            patch.object(report, "validate_bundle"),
            patch.object(report, "digest", return_value="a" * 64),
        ):
            totals = report.analyze_rpc([self.root], self.root / "rpc")
        self.assertEqual(totals["completed"], 1)
        self.assertEqual(totals["skipped_capacity"], 1)
        self.assertIn(
            "percentiles exclude failed calls", (self.root / "rpc/findings.txt").read_text()
        )
        for paths in ([], [self.root] * 281):
            with self.assertRaises(ValueError):
                report.analyze_rpc(paths, self.root / "bad")

    def check_files(self, path):
        manifest = read_json(path / "manifest.json")
        self.assertFalse(manifest["eligible_for_primary"])
        self.assertEqual(manifest["layout"]["text_overflow_count"], 0)
        for name, checksum in manifest["outputs"].items():
            self.assertEqual(digest(path / name), checksum)
