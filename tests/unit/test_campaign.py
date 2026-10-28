import copy
import fcntl
import os
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from src.artifacts import atomic_json, digest, read_json
from src.campaign import create_campaign, execute_campaign, resolve_trials

ROOT = Path(__file__).resolve().parents[2]
SOURCE = {"commit": "a" * 40, "tree_sha256": "b" * 64, "dirty": False}


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "campaign"
        self.raw = read_json(ROOT / "configs/pilot.json")
        self.raw["policies"] = ["fifo"]
        self.source = patch("src.campaign.source_identity", return_value=SOURCE).start()
        self.addCleanup(patch.stopall)
        self.observed = []

    def fake_trial(self, directory, config, _cancel):
        self.observed.append(config)
        directory.mkdir()
        atomic_json(directory / "manifest.json", {"state": "completed"})

    def run_campaign(self, **kwargs):
        with (
            patch("src.campaign.run_trial", side_effect=self.fake_trial),
            patch("src.campaign.validate_bundle", return_value={"integrity_valid": True}),
        ):
            return execute_campaign(self.directory, **kwargs)

    def test_schedule_is_saved_before_execution_and_completed_cells_are_not_repeated(self):
        create_campaign(self.directory, self.raw, 1)
        plan_hash = digest(self.directory / "plan.json")
        result = self.run_campaign()
        self.assertEqual(result["state"], "completed")
        self.assertEqual(len(self.observed), 4)
        self.assertEqual(sum(config.flows == 0 for config in self.observed), 2)
        self.assertTrue(all(config.mode == "namespace" for config in self.observed))
        self.assertEqual(digest(self.directory / "plan.json"), plan_hash)
        self.assertEqual(result, self.run_campaign())
        self.assertEqual(len(self.observed), 4)
        with self.assertRaises(FileExistsError):
            create_campaign(self.directory, self.raw)

    def test_failed_attempt_requires_explicit_reason_and_is_retained(self):
        create_campaign(self.directory, self.raw)
        with patch("src.campaign.run_trial", side_effect=OSError("workload failed")):
            with self.assertRaisesRegex(OSError, "workload failed"):
                execute_campaign(self.directory)
        failed = read_json(self.directory / "progress.json")["attempts"][0]
        self.assertEqual(failed["status"], "failed")
        with self.assertRaisesRegex(ValueError, "replacement reason"):
            self.run_campaign()
        result = self.run_campaign(
            replacement_reason="Corrected a missing tool; no data was collected"
        )
        self.assertEqual(result["attempts"][0], failed)
        self.assertEqual(result["attempts"][1]["replaces"], 0)
        self.assertEqual(len(result["attempts"]), 5)
        self.assertEqual(len({a["directory"] for a in result["attempts"]}), 5)

    def test_cancellation_before_launch_and_attempt_limits(self):
        create_campaign(self.directory, self.raw)
        cancel = Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            execute_campaign(self.directory, cancel=cancel)
        self.assertEqual(read_json(self.directory / "progress.json")["attempts"], [])
        with patch("src.campaign.run_trial", side_effect=InterruptedError("cancelled")):
            for _ in range(3):
                with self.assertRaises(InterruptedError):
                    execute_campaign(
                        self.directory, replacement_reason="Explicit interruption test"
                    )
        with self.assertRaisesRegex(ValueError, "three-attempt limit"):
            self.run_campaign(replacement_reason="Another interruption")

    def test_existing_attempt_hash_is_checked_and_partial_manifest_is_retained(self):
        create_campaign(self.directory, self.raw)

        def fail(directory, *_):
            directory.mkdir()
            atomic_json(directory / "manifest.json", {"state": "failed"})
            raise ValueError("invalid observations")

        with patch("src.campaign.run_trial", side_effect=fail):
            with self.assertRaises(ValueError):
                execute_campaign(self.directory)
        attempt = read_json(self.directory / "progress.json")["attempts"][0]
        path = self.directory / attempt["directory"] / "manifest.json"
        self.assertEqual(attempt["manifest_sha256"], digest(path))
        atomic_json(path, {"state": "completed"})
        with self.assertRaisesRegex(ValueError, "manifest changed"):
            self.run_campaign(replacement_reason="Review corrupted evidence")

    def test_changed_source_schedule_and_plan_hash_fail_before_any_trial(self):
        create_campaign(self.directory, self.raw)
        plan = read_json(self.directory / "plan.json")
        for key, value in (
            ("kind", "primary"),
            ("schema_version", 2),
            ("schedule", {}),
            ("source", {}),
        ):
            with self.subTest(key=key):
                atomic_json(self.directory / "plan.json", dict(plan, **{key: value}))
                with self.assertRaises(ValueError):
                    self.run_campaign()
        atomic_json(self.directory / "plan.json", plan)
        progress = read_json(self.directory / "progress.json")
        atomic_json(self.directory / "progress.json", dict(progress, plan_sha256="changed"))
        with self.assertRaisesRegex(ValueError, "digest changed"):
            self.run_campaign()
        self.assertEqual(self.observed, [])

    def test_progress_and_attempt_corruption_is_rejected(self):
        create_campaign(self.directory, self.raw)
        original = self.run_campaign()
        corruptions = [
            ("schema_version", 2),
            ("state", "unknown"),
            ("attempts", {}),
            ("attempts", original["attempts"] * 4),
        ]
        for key, value in corruptions:
            atomic_json(self.directory / "progress.json", dict(original, **{key: value}))
            with self.assertRaises(ValueError):
                self.run_campaign()
        for key, value in (
            ("cell_id", "unknown"),
            ("directory", "../outside"),
            ("status", "invalid"),
            ("replaces", 4),
            ("reason", 1),
            ("error", "x" * 1025),
            ("manifest_sha256", None),
        ):
            changed = copy.deepcopy(original)
            changed["attempts"][0][key] = value
            atomic_json(self.directory / "progress.json", changed)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.run_campaign()
        changed = copy.deepcopy(original)
        changed["attempts"][0]["extra"] = True
        atomic_json(self.directory / "progress.json", changed)
        with self.assertRaises(ValueError):
            self.run_campaign()

    def test_symlink_lock_and_concurrent_execution_are_refused(self):
        create_campaign(self.directory, self.raw)
        link = self.directory.parent / "alias"
        link.symlink_to(self.directory)
        with self.assertRaises(ValueError):
            execute_campaign(link)
        with self.assertRaises(ValueError):
            execute_campaign(self.directory, replacement_reason="x" * 1025)
        with (self.directory / ".lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                execute_campaign(self.directory)
        (self.directory / ".lock").unlink()
        (self.directory / ".lock").symlink_to(self.directory / "plan.json")
        with self.assertRaises(OSError):
            execute_campaign(self.directory)
        (self.directory / ".lock").unlink()
        os.mkfifo(self.directory / ".lock")
        with self.assertRaisesRegex(ValueError, "regular file"):
            execute_campaign(self.directory)

    def test_unfinished_namespace_ownership_blocks_another_attempt(self):
        create_campaign(self.directory, self.raw)
        result = self.run_campaign()
        run = self.directory / result["attempts"][0]["directory"]
        (run / "topology").mkdir()
        atomic_json(run / "topology/ownership.json", {"owned": {"client": [1, 2]}})
        with self.assertRaisesRegex(ValueError, "still owns namespaces"):
            self.run_campaign()
        atomic_json(run / "topology/ownership.json", {"owned": {}})
        self.assertEqual(self.run_campaign()["state"], "completed")

    def test_unsupported_execution_settings_fail_before_output_creation(self):
        for key, value in (
            ("link_rate_mbps", 200),
            ("background_flow_counts", [2]),
            ("measurement_seconds", 121),
            ("repetitions", 100),
            ("background_load_fractions", [0.501, 0.502]),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                resolve_trials(dict(self.raw, **{key: value}), 1)
        with self.assertRaises(ValueError):
            create_campaign(self.directory, self.raw, 61)
        self.assertFalse(self.directory.exists())


if __name__ == "__main__":
    unittest.main()
