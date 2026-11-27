import socket
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event

from src.artifacts import read_json
from src.basic_rpc_protocol.rpc_connector import run_server
from src.basic_rpc_protocol.rpc_server import RpcServer
from src.basic_rpc_protocol.rpc_workload import RpcWorkloadConfig, run_rpc_workload
from src.bundle_validation import validate_bundle
from src.rpc_validation import validate_rpc
from src.trial import TrialConfig, run_trial


class RpcWorkloadIntegrationTests(unittest.TestCase):
    def test_actual_concurrent_calls_keep_unique_ids_and_reconcilable_outcomes(self):
        ready, stop, address = Event(), Event(), []

        def listening(endpoint):
            address.append(endpoint)
            ready.set()

        with ThreadPoolExecutor(max_workers=1) as pool:
            server = pool.submit(
                run_server,
                RpcServer(bytes),
                ("127.0.0.1", 0),
                "127.0.0.1",
                stop=stop,
                ready=listening,
                duration_ms=5000,
            )
            try:
                self.assertTrue(ready.wait(2))
                config = RpcWorkloadConfig(
                    peer=address[0], requests_per_second=100, measurement_seconds=1, workers=4
                )
                raw = run_rpc_workload(config)
            finally:
                stop.set()
            evidence = server.result(timeout=2)
        summary = validate_rpc(raw)
        self.assertEqual(raw["scheduled_calls"], 100)
        self.assertEqual(raw["admitted_calls"] + raw["skipped_capacity"], 100)
        self.assertGreater(summary["counts"]["completed"], 0)
        self.assertEqual(summary["counts"]["timeout"], 0)
        self.assertEqual(evidence["status"], "cancelled")

    def test_blackhole_exhausts_retries_and_capacity_without_unbounded_queue(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as blackhole:
            blackhole.bind(("127.0.0.1", 0))
            config = RpcWorkloadConfig(
                peer=blackhole.getsockname(),
                requests_per_second=100,
                measurement_seconds=1,
                workers=1,
                retry_timeout_ms=50,
                max_retries=1,
                total_timeout_ms=300,
            )
            raw = run_rpc_workload(config)
        summary = validate_rpc(raw)
        self.assertGreater(raw["skipped_capacity"], 0)
        self.assertLess(raw["admitted_calls"], 20)
        self.assertEqual(summary["counts"]["timeout"], raw["admitted_calls"])
        self.assertEqual(summary["retransmissions"], raw["admitted_calls"])

    def test_trial_records_rpc_without_changing_the_foreground_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            for flows in (0, 1):
                root = Path(temporary) / str(flows)
                config = TrialConfig(
                    measurement_seconds=2,
                    rpc_diagnostics=True,
                    flows=flows,
                    aggregate_bps=8000000 if flows else 0,
                )
                run_trial(root, config)
                self.assertTrue(validate_bundle(root)["integrity_valid"])
                self.assertEqual(
                    read_json(root / "foreground.json")["counts"]["measurement"]["on_time"]
                    + read_json(root / "foreground.json")["counts"]["measurement"]["not_sent"],
                    1000,
                )
                rpc = read_json(root / "rpc.json")
                self.assertEqual(rpc["scheduled_calls"], 1000)
                self.assertEqual(read_json(root / "rpc-bulk.json")["actual_flows"], flows)
                server = read_json(root / "rpc-server.json")
                self.assertEqual(server["status"], "completed")
                self.assertGreater(server["counts"]["replies_sent"], 0)
        with self.assertRaises(ValueError):
            replace(config, rpc_diagnostics=1)
