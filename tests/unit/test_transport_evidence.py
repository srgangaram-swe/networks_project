import copy
import tempfile
import unittest
from pathlib import Path

from src import transport_validation as check
from src.artifacts import atomic_json
from src.transport_summary import summarize_transport


def socket_metrics():
    return {
        "status": "available",
        "source": "Linux_TCP_INFO",
        "total_retransmissions": 2,
        "rtt_us": 20000,
        "rtt_variation_us": 100,
        "send_cwnd_segments": 10,
    }


def foreground():
    return {
        "transport": "tcp",
        "framing_bytes": 512,
        "nagle_disabled": True,
        "before": socket_metrics(),
        "after": socket_metrics(),
        "samples": [{"observed_ns": 100, **socket_metrics()}],
        "event_stream": {"sent": 4, "dropped": 0},
    }


def observer():
    return {
        "schema_version": 1,
        "status": "completed",
        "observed_packets": 8,
        "observed_flows": 1,
        "capture_dropped": 0,
        "quality": "no_reported_capture_drops",
        "event_stream": {"sent": 1, "dropped": 0},
        "windows": [
            {
                "index": 0,
                "foreground_duplicate_ack_candidates": 1,
                "bulk_duplicate_ack_candidates": 2,
            }
        ],
    }


def forecast():
    return {
        "schema_version": 1,
        "mode": "shadow_only_no_policy_changes",
        "packet_loss_labels_available": False,
        "producer_events_dropped": 0,
        "quality": "no_reported_event_drops",
        "forecasts": [
            {
                "issued_ns": 0,
                "target_start_ns": 1,
                "prediction": {"p99_ms": 2, "timeout_fraction": None},
            }
        ],
    }


class EvidenceTests(unittest.TestCase):
    def test_transport_counter_schemas_and_missing_data_are_checked(self):
        check._foreground(foreground(), "tcp")
        check._foreground({"transport": "udp", "event_stream": {"sent": 0, "dropped": 0}}, "udp")
        for invalid in (None, {}, {"sent": -1, "dropped": 0}):
            with self.assertRaises(ValueError):
                check._stream(invalid)
        for invalid in (None, {}, {"source": "Linux_TCP_INFO", "status": "invented"}):
            with self.assertRaises(ValueError):
                check._socket_info(invalid)
        check._socket_info({"source": "Linux_TCP_INFO", "status": "unavailable_platform"})
        for key, value in (
            ("transport", "udp"),
            ("framing_bytes", 1),
            ("nagle_disabled", False),
            ("samples", None),
            ("samples", [{}] * 191),
        ):
            raw = foreground()
            raw[key] = value
            with self.assertRaises(ValueError):
                check._foreground(raw, "tcp")
        with self.assertRaises(ValueError):
            check._foreground(None, "tcp")

    def test_passive_capture_and_forecast_quality_cannot_hide_drops_or_future_targets(self):
        for function, original, mutations in (
            (
                check._observer,
                observer(),
                (
                    ("schema_version", 2),
                    ("quality", "capture_drops"),
                    ("windows", None),
                    ("windows", [{"index": 0}] * 192),
                    ("observed_packets", -1),
                ),
            ),
            (
                check._forecast,
                forecast(),
                (
                    ("mode", "active_policy"),
                    ("packet_loss_labels_available", True),
                    ("quality", "incomplete_event_stream"),
                    ("forecasts", None),
                    ("forecasts", [{}] * 192),
                ),
            ),
        ):
            function(original)
            with self.assertRaises(ValueError):
                function(None)
            for key, value in mutations:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    function({**original, key: value})
        raw = observer()
        raw.update(capture_dropped=1, quality="capture_drops")
        check._observer(raw)
        raw = forecast()
        raw.update(producer_events_dropped=1, quality="incomplete_event_stream")
        check._forecast(raw)
        raw["forecasts"][0]["issued_ns"] = 1
        with self.assertRaises(ValueError):
            check._forecast(raw)
        raw["forecasts"][0]["issued_ns"] = 0
        raw["forecasts"][0]["prediction"]["timeout_fraction"] = 1.1
        with self.assertRaises(ValueError):
            check._forecast(raw)

    def test_isolated_endpoints_and_optional_evidence_match_transport(self):
        from src.topology import CLIENT_ADDRESS, SERVER_ADDRESS

        artifacts = {
            "configuration.json": {
                "mode": "namespace",
                "transport": "tcp",
                "shadow_forecast": True,
            },
            "foreground.json": {"bind": [CLIENT_ADDRESS, 42001], "peer": [SERVER_ADDRESS, 42000]},
            "foreground-transport.json": foreground(),
            "tcp-observer.json": observer(),
            "shadow-forecast.json": forecast(),
        }
        check.validate_transport_artifacts(artifacts)
        original = copy.deepcopy(artifacts)
        artifacts["foreground.json"]["peer"] = ["127.0.0.1", 42000]
        with self.assertRaises(ValueError):
            check.validate_transport_artifacts(artifacts)
        del original["tcp-observer.json"]
        with self.assertRaises(ValueError):
            check.validate_transport_artifacts(original)

    def test_summary_retains_unavailable_values_and_scopes_ack_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = {"artifacts": {}}
            self.assertTrue(
                all(value is None for value in summarize_transport(root, manifest).values())
            )
            raw = foreground()
            raw["after"]["total_retransmissions"] = 5
            atomic_json(root / "foreground-transport.json", raw)
            atomic_json(root / "tcp-observer.json", observer())
            manifest["artifacts"] = {"foreground-transport.json": "", "tcp-observer.json": ""}
            result = summarize_transport(root, manifest)
            self.assertEqual(result["tcp_total_retransmissions"], 3)
            self.assertEqual(result["tcp_foreground_duplicate_ack_candidates"], 1)
            self.assertEqual(result["tcp_bulk_duplicate_ack_candidates"], 2)
            atomic_json(root / "foreground-transport.json", {"transport": "udp"})
            self.assertIsNone(summarize_transport(root, manifest)["tcp_total_retransmissions"])
