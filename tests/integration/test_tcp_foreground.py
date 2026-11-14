import socket
import tempfile
import threading
import unittest
from pathlib import Path

from src.artifacts import json_bytes, parse_json
from src.bundle_validation import validate_capture
from src.foreground import Workload
from src.foreground_tcp import run_client, run_responder
from src.trial import TrialConfig, run_trial


class TcpForegroundTests(unittest.TestCase):
    def test_real_tcp_stream_preserves_request_ids_and_fixed_frame_payloads(self):
        stop = threading.Event()
        ready = threading.Event()
        address = []
        outcomes = []

        def start():
            outcomes.append(
                run_responder(
                    ("127.0.0.1", 0),
                    "127.0.0.1",
                    stop=stop,
                    duration_ms=5000,
                    ready=lambda bound: (address.append(bound), ready.set()),
                )
            )

        thread = threading.Thread(target=start)
        thread.start()
        try:
            self.assertTrue(ready.wait(2))
            capture = run_client(Workload(0, 300, 1100, 100), ("127.0.0.1", 0), address[0])
            metrics = capture.pop("transport_metrics")
            self.assertEqual(metrics["transport"], "tcp")
            self.assertTrue(metrics["nagle_disabled"])
            self.assertEqual(capture["status"], "completed")
            records = validate_capture(parse_json(json_bytes(capture)))
            self.assertEqual(len(records), 30)
            self.assertGreater(sum(record.outcome == "on_time" for record in records), 0)
        finally:
            stop.set()
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes[0]["status"], "cancelled")

    def test_real_loopback_trial_selects_tcp_without_a_policy_claim(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "trial"
            result = run_trial(
                root,
                TrialConfig(
                    transport="tcp",
                    shadow_forecast=True,
                    flows=0,
                    aggregate_bps=0,
                    foreground_port=port,
                    measurement_seconds=1,
                ),
            )
            self.assertEqual(result["state"], "completed")
            self.assertEqual(result["mode"], "loopback")
            self.assertTrue((root / "foreground-transport.json").exists())
            self.assertIn("shadow-forecast.json", result["artifacts"])
            self.assertFalse((root / "events.fifo").exists())
