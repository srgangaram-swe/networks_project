"""Fault cases at data, lifecycle and resource-budget boundaries."""

import copy
import tempfile
import unittest
from pathlib import Path

from src import bundle_validation as validation
from src.artifacts import read_json
from src.bulk import BulkPlan, summarize_bulk
from src.experiment_config import bounded_number
from src.run_bundle import RunBundle
from src.shadow_forecast import SECOND, ShadowForecast
from src.trial import TrialConfig
from tests.fixtures import valid_bundle
from tests.unit.test_bulk import report


class EvidenceBoundaryTests(unittest.TestCase):
    def test_bulk_rejects_wrong_shapes_missing_flows_and_empty_measured_intervals(self):
        for mutate in (
            lambda r: r.update(start=[]),
            lambda r: r.update(end=[]),
            lambda r: r["start"].update(test_start=[]),
            lambda r: r["start"]["test_start"].update(protocol="UDP"),
            lambda r: r["start"]["test_start"].update(target_bitrate=1),
            lambda r: r["start"].update(connected={}),
            lambda r: r.update(intervals=[]),
            lambda r: r["intervals"][0]["sum"].update(omitted=True),
            lambda r: r["intervals"][0].update(sum=[]),
        ):
            value = report()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                summarize_bulk(value, BulkPlan(8_000_000, 1, 1))

    def test_trial_and_numeric_limits_do_not_accept_boolean_or_wrong_ports(self):
        for options in (
            {"flows": False, "aggregate_bps": 0},
            {"mode": "missing"},
            {"mode": "loopback", "policy": "fifo"},
            {"mode": "namespace", "foreground_port": 42002},
            {"bulk_port": 0},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                TrialConfig(**options)
        with self.assertRaises(ValueError):
            bounded_number(float("nan"), "limit", 0, 1)

    def test_run_bundle_registration_and_terminal_transitions_preserve_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "bundle"
            bundle = RunBundle(root, {"mode": "macos", "policy": "fifo"}, {})
            self.assertEqual(
                read_json(root / "environment.json")["measurement_kind"], "macos_testbed"
            )
            for name in ("../escape.json", "manifest.json"):
                with self.assertRaises(ValueError):
                    bundle.register(name)
            with self.assertRaises(FileExistsError):
                bundle.register("configuration.json")
            with self.assertRaises(ValueError):
                bundle.transition("completed")

    def test_manifest_and_artifact_corruption_cannot_change_scientific_claims(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "bundle"
            bundle = valid_bundle(root)
            artifacts = {name: read_json(root / name) for name in bundle.manifest["artifacts"]}
            for mutate in (
                lambda a: a["cpu.json"].update(busy_percent=1),
                lambda a: a["cpu.json"].update(scope="router_without_evidence"),
                lambda a: a["configuration.json"].update(policy="fifo"),
                lambda a: a["foreground.json"]["config"].update(requests_per_second=100),
            ):
                changed = copy.deepcopy(artifacts)
                mutate(changed)
                with self.assertRaises(ValueError):
                    validation._cross_checks(changed, bundle.manifest)
                    validation._supporting_artifacts(changed, bundle.manifest)
            changed = copy.deepcopy(bundle.manifest)
            changed["history"][0]["state"] = "completed"
            with self.assertRaises(ValueError):
                validation._history(changed)
            changed = copy.deepcopy(bundle.manifest)
            changed["artifacts"]["foreground.json"] = "bad"
            with self.assertRaises(ValueError):
                validation._load_artifacts(root, changed)
            changed = copy.deepcopy(bundle.manifest)
            changed["source"]["dirty"] = 1
            with self.assertRaises(ValueError):
                validation._manifest_identity(changed)
            changed = copy.deepcopy(bundle.manifest)
            changed["state"] = "warmup"
            with self.assertRaises(ValueError):
                validation.validate_contents(root, changed)

    def test_macos_queue_evidence_requires_router_attachments(self):
        from src.topology import Topology, inspection_commands

        snapshots = dict.fromkeys(inspection_commands(Topology("a" * 12)), [])
        snapshots["router_queues"] = [{"dev": "to-client", "kind": "cake", "handle": "1:"}]
        evidence = {
            "kind": "macos_testbed",
            "attachment_checked": True,
            "calibrated": False,
            "snapshots": snapshots,
        }
        artifacts = {
            name: copy.deepcopy(evidence) for name in ("queues-before.json", "queues-after.json")
        }
        validation._queues(artifacts, "macos", "cake_bounded")
        for mutate in (
            lambda a: a["queues-after.json"].update(kind="virtual_testbed"),
            lambda a: a["queues-after.json"]["snapshots"].update(client_links={}),
        ):
            altered = copy.deepcopy(artifacts)
            mutate(altered)
            with self.assertRaises(ValueError):
                validation._queues(altered, "macos", "cake_bounded")

    def test_forecast_limits_reject_invalid_ack_counts_ids_duplicates_and_rate(self):
        forecast = ShadowForecast(0)
        with self.assertRaises(ValueError):
            forecast.observe(
                {"kind": "tcp_window", "observed_ns": 0, "foreground_duplicate_ack_candidates": -1},
                0,
            )
        with self.assertRaises(ValueError):
            forecast.observe({"kind": "send", "observed_ns": 0, "request_id": -1}, 0)
        event = {"kind": "send", "observed_ns": 0, "request_id": 0}
        forecast.observe(event, 0)
        with self.assertRaises(ValueError):
            forecast.observe(event, 0)
        forecast.windows[0]["counts"]["sent"] = 500
        with self.assertRaises(ValueError):
            forecast.observe({**event, "request_id": 1}, 0)
        forecast.advance(SECOND)
        forecast.advance(SECOND)
        self.assertEqual(len(forecast.forecasts), 1)
        forecast.advance(190 * SECOND)
        self.assertNotIn(191, forecast.forecasts)
