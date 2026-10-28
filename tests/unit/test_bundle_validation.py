import copy
import tempfile
import unittest
from pathlib import Path

from src.artifacts import atomic_json, digest, read_json
from src.bundle_validation import validate_bundle, validate_capture
from tests.fixtures import capture, valid_bundle


class CaptureValidationTests(unittest.TestCase):
    def test_late_and_unanswered_requests_remain_separate_outcomes(self):
        data = capture()
        data["records"][0]["received_ns"] = data["records"][0]["sent_ns"] + 1_000_000_001
        data["records"][1]["received_ns"] = None
        data["counts"]["measurement"].update(on_time=498, late=1, timeout=1)
        records = validate_capture(data)
        self.assertEqual([row.outcome for row in records[:2]], ["late", "timeout"])
        data["counts"]["measurement"].update(late=0, timeout=2)
        with self.assertRaisesRegex(ValueError, "reconcile"):
            validate_capture(data)

    def test_documented_capture_fixtures(self):
        directory = Path(__file__).resolve().parents[1] / "fixtures"
        records = validate_capture(read_json(directory / "foreground-valid.json"))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[1].rtt_ns, 1_000_000)
        with self.assertRaises(ValueError):
            validate_capture(read_json(directory / "foreground-invalid-duplicate.json"))

    def test_hand_calculated_latency_and_exact_schedule(self):
        records = validate_capture(capture())
        self.assertEqual(len(records), 500)
        self.assertEqual(records[-1].scheduled_ns - records[0].scheduled_ns, 998_000_000)
        self.assertEqual(records[0].rtt_ns, 1_000_000)
        self.assertEqual(records[0].completion_ns, 1_001_000)

    def test_mutate_each_top_level_field_and_record_invariants(self):
        original = capture()
        for key in original:
            value = copy.deepcopy(original)
            del value[key]
            with self.assertRaises(ValueError, msg=key):
                validate_capture(value)
        for key, value in (
            ("request_id", 1),
            ("schema_version", True),
            ("scheduled_ns", 0),
            ("sent_ns", -1),
            ("received_ns", 9_000_000_000),
        ):
            changed = copy.deepcopy(original)
            changed["records"][0][key] = value
            with self.assertRaises(ValueError, msg=key):
                validate_capture(changed)

    def test_corrupt_phases_counts_and_event_logs(self):
        original = capture()
        mutations = (
            ("events_dropped", 1),
            ("records", []),
            ("status", "cancelled"),
            ("planned_end_ns", 1),
            ("incomplete_deadlines", 1),
            ("counts", {}),
            ("event_counts", {"duplicate_reply": 1}),
            ("protocol_status", "accepted"),
            ("bind", []),
            ("events", [{"kind": "nonsense", "observed_ns": 1, "request_id": 0}]),
        )
        for key, value in mutations:
            changed = copy.deepcopy(original)
            changed[key] = value
            with self.assertRaises(ValueError, msg=key):
                validate_capture(changed)

    def test_not_sent_requires_an_event_and_boolean_counts_are_rejected(self):
        value = capture()
        value["records"][0].update(sent_ns=None, received_ns=None)
        value["counts"]["measurement"].update(on_time=499, not_sent=1)
        with self.assertRaisesRegex(ValueError, "matching event"):
            validate_capture(value)
        value["events"] = [
            {"kind": "generator_late", "observed_ns": 1_010_000_000, "request_id": 0}
        ]
        value["event_counts"] = {"generator_late": 1}
        self.assertEqual(validate_capture(value)[0].outcome, "not_sent")
        value["counts"]["measurement"]["not_sent"] = True
        with self.assertRaises(ValueError):
            validate_capture(value)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "bundle"
        self.bundle = valid_bundle(self.root)

    def replace_artifact(self, name, value):
        atomic_json(self.root / name, value)
        self.bundle.manifest["artifacts"][name] = digest(self.root / name)
        self.bundle.save()

    def test_consistent_receiver_totals_cannot_hide_a_wrong_measurement_duration(self):
        bulk = read_json(self.root / "bulk.json")
        bulk.update(receiver_seconds=10, goodput_mbps=0.8)
        bulk["intervals"][0]["end_seconds"] = 10
        self.replace_artifact("bulk.json", bulk)
        with self.assertRaisesRegex(ValueError, "duration differs"):
            validate_bundle(self.root)

    def test_complete_fixture_and_exclusive_creation(self):
        result = validate_bundle(self.root)
        self.assertTrue(result["integrity_valid"])
        self.assertFalse(result["eligible_for_primary"])
        self.assertEqual(result["measurement_requests"], 500)
        with self.assertRaises(FileExistsError):
            valid_bundle(self.root)
        for name in ("../outside.json", "manifest.json", "foreground.json"):
            with self.assertRaises((ValueError, FileExistsError)):
                self.bundle.artifact(name, {})
        with self.assertRaises(ValueError):
            self.bundle.transition("failed")

    def test_missing_altered_and_symlinked_artifacts_fail(self):
        path = self.root / "foreground.json"
        old = path.read_bytes()
        path.write_bytes(old + b" ")
        with self.assertRaisesRegex(ValueError, "digest"):
            validate_bundle(self.root)
        path.unlink()
        with self.assertRaises(OSError):
            validate_bundle(self.root)
        external = Path(self.temp.name) / "capture.json"
        external.write_bytes(old)
        path.symlink_to(external)
        with self.assertRaises(OSError):
            validate_bundle(self.root)

    def test_manifest_invariants_cannot_be_forged(self):
        original = copy.deepcopy(self.bundle.manifest)
        mutations = (
            ("state", "failed"),
            ("schema_version", True),
            ("units", {}),
            ("policy", "fifo"),
            ("source", {}),
            ("history", []),
            ("artifacts", {}),
            ("run_id", "../x"),
            ("phases", {}),
            ("started_utc", "2026-10-27"),
            ("errors", ["failed"]),
            ("validity", {"eligible_for_primary": True, "reasons": []}),
        )
        for key, value in mutations:
            changed = copy.deepcopy(original)
            changed[key] = value
            atomic_json(self.root / "manifest.json", changed)
            with self.assertRaises(ValueError, msg=key):
                validate_bundle(self.root)

    def test_bulk_and_config_cross_checks(self):
        original = read_json(self.root / "bulk.json")
        for key, value in (
            ("actual_flows", 8),
            ("goodput_mbps", 110),
            ("receiver_bytes", True),
            ("foreground_window_aligned", True),
            ("per_flow_bps", 1),
        ):
            changed = dict(original, **{key: value})
            self.replace_artifact("bulk.json", changed)
            with self.assertRaises(ValueError, msg=key):
                validate_bundle(self.root)

    def test_cpu_and_topology_claims_are_checked(self):
        self.replace_artifact(
            "cpu.json", {"scope": "shared_host", "busy_percent": 90, "iowait_percent": 20}
        )
        with self.assertRaises(ValueError):
            validate_bundle(self.root)
        self.replace_artifact(
            "cpu.json", {"scope": "shared_host", "busy_percent": 30, "iowait_percent": 5}
        )
        self.assertTrue(validate_bundle(self.root)["integrity_valid"])
        self.replace_artifact(
            "queues-after.json",
            {"kind": "loopback", "network_changes": True, "queue_verified": True},
        )
        with self.assertRaises(ValueError):
            validate_bundle(self.root)

    def test_additional_manifest_and_source_corruption(self):
        original = copy.deepcopy(self.bundle.manifest)
        mutations = (
            ("mode", "physical"),
            ("started_utc", None),
            ("started_utc", "2026-01-01T00:00:00+02:00"),
            ("source", {"commit": "x", "tree_sha256": "b" * 64, "dirty": False}),
            ("source", {"commit": "a" * 40, "tree_sha256": "b" * 64, "dirty": 0}),
            ("validity", {"eligible_for_primary": False, "reasons": []}),
            ("validity", {"eligible_for_primary": False, "reasons": [False]}),
        )
        for key, value in mutations:
            atomic_json(self.root / "manifest.json", dict(original, **{key: value}))
            with self.assertRaises(ValueError, msg=key):
                validate_bundle(self.root)

    def test_interval_and_environment_corruption(self):
        original = read_json(self.root / "bulk.json")
        mutations = (
            ("intervals", []),
            ("window", "foreground"),
            ("tool_version", ""),
            ("intervals", [{"start_seconds": 0, "end_seconds": 0, "bytes": 1_000_000}]),
            ("intervals", [{"start_seconds": 0, "end_seconds": 1, "bytes": 9}]),
        )
        for key, value in mutations:
            self.replace_artifact("bulk.json", dict(original, **{key: value}))
            with self.assertRaises(ValueError, msg=key):
                validate_bundle(self.root)
        self.replace_artifact("bulk.json", original)
        environment = read_json(self.root / "environment.json")
        for key, value in (("system", []), ("measurement_kind", "physical_nic")):
            self.replace_artifact("environment.json", dict(environment, **{key: value}))
            with self.assertRaises(ValueError, msg=key):
                validate_bundle(self.root)


if __name__ == "__main__":
    unittest.main()
