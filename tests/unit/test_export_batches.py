import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.export_pilot import export
from src.artifacts import atomic_json, digest, read_json
from src.campaign import create_campaign
from src.export_batches import export_inputs

ROOT = Path(__file__).resolve().parents[2]
SOURCE = {"commit": "a" * 40, "tree_sha256": "b" * 64, "dirty": False}


class ExportBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.campaign = self.root / "campaign"
        with patch("src.campaign.source_identity", return_value=SOURCE):
            create_campaign(
                self.campaign, read_json(ROOT / "configs/primary.json"), diagnostic_matrix=True
            )
        self.progress = read_json(self.campaign / "progress.json")
        cells = read_json(self.campaign / "plan.json")["schedule"]["cells"]
        for index, cell in enumerate(cells):
            name = f"attempt-{index + 1:03d}-{cell['cell_id']}"
            directory = self.campaign / name
            directory.mkdir()
            atomic_json(directory / "manifest.json", {"test_cell": cell["cell_id"]})
            self.progress["attempts"].append(
                {
                    "cell_id": cell["cell_id"],
                    "directory": name,
                    "status": "completed",
                    "manifest_sha256": digest(directory / "manifest.json"),
                }
            )
        self.progress["state"] = "completed"
        atomic_json(self.campaign / "progress.json", self.progress)
        self.chunks = []

    def fake_export(self, directories, destination):
        # This test checks partitioning, not observations or metric validation.
        self.chunks.append(list(directories))
        destination.mkdir()
        atomic_json(destination / "provenance.json", {"run_count": len(directories)})

    def export(self, output):
        with (
            patch("scripts.export_pilot.export_diagnostics", side_effect=self.fake_export),
            patch("scripts.export_pilot.tool_versions", return_value={"test": True}),
        ):
            export(self.campaign, output)

    def test_full_matrix_partitions_every_run_and_binds_complete_ledger(self):
        output = self.root / "export"
        self.export(output)
        self.assertEqual(len(self.chunks), 47)
        self.assertEqual(sum(map(len, self.chunks)), 280)
        self.assertLessEqual(max(map(len, self.chunks)) * 30000, 200000)
        ledger = read_json(output / "attempts.json")
        self.assertEqual(len(ledger["attempts"]), 280)
        self.assertFalse(ledger["primary_eligible"])
        self.assertEqual(ledger["unattempted_cells"], [])
        inputs = export_inputs([output])
        self.assertEqual(len(inputs), 47)
        completed = []
        for directory, binding in inputs:
            self.assertEqual(binding["provenance_sha256"], digest(directory / "provenance.json"))
            design = read_json(directory / "attempts.json")
            self.assertEqual(design["campaign_ledger_sha256"], digest(output / "attempts.json"))
            completed.extend(a["cell_id"] for a in design["attempts"])
        self.assertEqual(len(set(completed)), 280)
        with self.assertRaises(FileExistsError):
            self.export(output)

    def test_flat_partial_and_empty_exports_retain_failed_attempts(self):
        self.progress["attempts"] = self.progress["attempts"][:2]
        self.progress["attempts"][0]["status"] = "failed"
        self.progress["state"] = "stopped"
        atomic_json(self.campaign / "progress.json", self.progress)
        output = self.root / "partial"
        self.export(output)
        self.assertEqual(export_inputs([output]), [(output, {})])
        self.assertEqual(len(read_json(output / "attempts.json")["unattempted_cells"]), 278)
        self.assertEqual(self.chunks, [[self.campaign / self.progress["attempts"][1]["directory"]]])
        self.progress["attempts"][1]["status"] = "failed"
        atomic_json(self.campaign / "progress.json", self.progress)
        self.export(self.root / "no-observations")
        self.assertFalse((self.root / "no-observations/provenance.json").exists())

    def test_corrupt_campaign_fails_before_export(self):
        original = copy.deepcopy(self.progress)
        for change in (
            lambda p: p.update(plan_sha256="changed"),
            lambda p: p.update(schema_version=True),
            lambda p: p.update(state="unknown"),
            lambda p: p.update(attempts=p["attempts"] * 4),
            lambda p: p["attempts"][0].update(cell_id="unknown"),
            lambda p: p["attempts"][0].update(directory="../escape"),
            lambda p: p["attempts"][0].update(manifest_sha256="changed"),
            lambda p: p["attempts"][0].update(status="unknown"),
            lambda p: p["attempts"].append(
                dict(p["attempts"][0], directory=f"attempt-281-{p['attempts'][0]['cell_id']}")
            ),
        ):
            changed = copy.deepcopy(original)
            change(changed)
            atomic_json(self.campaign / "progress.json", changed)
            with self.assertRaises(ValueError):
                self.export(self.root / "invalid")
            self.assertFalse((self.root / "invalid").exists())

    def test_index_corruption_aliases_and_limits_fail_closed(self):
        output = self.root / "export"
        self.export(output)
        original = read_json(output / "index.json")
        for change in (
            lambda i: i.update(schema_version=True),
            lambda i: i.update(kind="primary"),
            lambda i: i.update(state="writing"),
            lambda i: i.update(eligible_for_primary=True),
            lambda i: i.update(batches=[]),
            lambda i: i.update(batches="wrong"),
            lambda i: i.update(batches=i["batches"] * 3),
            lambda i: i.update(attempts_sha256="changed"),
            lambda i: i.update(versions_sha256="changed"),
            lambda i: i["batches"][0].update(directory="../escape"),
        ):
            changed = copy.deepcopy(original)
            change(changed)
            atomic_json(output / "index.json", changed)
            with self.assertRaises(ValueError):
                export_inputs([output])
        atomic_json(output / "index.json", original)
        with self.assertRaisesRegex(ValueError, "128 export batches"):
            export_inputs([output] * 3)
        (output / "batch-001").rename(output / "renamed")
        (output / "batch-001").symlink_to(output / "renamed")
        with self.assertRaises(ValueError):
            export_inputs([output])
        alias = self.root / "alias"
        alias.symlink_to(output)
        for paths in ([], [output] * 129, [self.root / "absent"], [alias], [output] * 3):
            with self.assertRaises(ValueError):
                export_inputs(paths)

    def test_failed_batch_export_remains_incomplete_and_preserves_cause(self):
        output = self.root / "partial-index"
        error = OSError("disk full during batch export")
        with (
            patch("scripts.export_pilot.export_diagnostics", side_effect=error),
            patch("scripts.export_pilot.tool_versions", return_value={}),
        ):
            with self.assertRaises(OSError) as caught:
                export(self.campaign, output)
        self.assertIs(caught.exception, error)
        self.assertEqual(read_json(output / "index.json")["state"], "writing")
        self.assertEqual(len(read_json(output / "attempts.json")["attempts"]), 280)
        with self.assertRaisesRegex(ValueError, "incomplete export index"):
            export_inputs([output])
