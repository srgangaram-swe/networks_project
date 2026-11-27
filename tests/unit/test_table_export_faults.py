import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.artifacts import atomic_json, digest, read_json
from src.simulation import simulate_trial, simulation_plan
from src.table_export import _requests, export_run_tables
from tests.unit.physical_support import source


class TableExportFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.collection = self.root / "collection"
        self.collection.mkdir()
        self.plan = simulation_plan()
        cell = self.plan["schedule"]["cells"][0]
        self.trial = simulate_trial((str(self.collection / "trial-1"), cell, 10, 561, source()))

    def test_duplicate_unknown_and_failed_cells_are_not_exported(self):
        for rows in (
            [self.trial, self.trial],
            [{**self.trial, "cell_id": "unknown"}],
            [{**self.trial, "state": "failed"}],
        ):
            with self.assertRaises(ValueError):
                export_run_tables(self.root / "out", self.collection, self.plan, rows)
        self.assertFalse((self.root / "out").exists())

    def test_escaping_aliases_and_changed_tables_fail(self):
        for index, directory in enumerate(("../escape", "trial-999")):
            row = {**self.trial, "directory": directory}
            with self.assertRaises(ValueError):
                export_run_tables(self.root / f"bad-{index}", self.collection, self.plan, [row])
        path = self.collection / "trial-1/summary.json"
        original = read_json(path)
        atomic_json(path, {**original, "manifest_sha256": "0" * 64})
        with self.assertRaisesRegex(ValueError, "binding changed"):
            export_run_tables(self.root / "binding", self.collection, self.plan, [self.trial])
        atomic_json(path, original)
        altered = copy.deepcopy(self.trial)
        altered["table_hashes"]["requests"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "table changed"):
            export_run_tables(self.root / "table", self.collection, self.plan, [altered])
        self.assertEqual(digest(path), self.trial["table_hashes"]["summary"])

    def test_request_column_and_row_limits_are_enforced(self):
        for name, data in (("header", b"bad\n1\n"), ("rows", None)):
            destination = self.root / name
            destination.mkdir()
            if data is None:
                from src.simulation import REQUEST_FIELDS

                data = (",".join(REQUEST_FIELDS) + "\n" + "\n" * 200001).encode()
            with (
                patch("src.table_export.read_bytes", return_value=data),
                self.assertRaises(ValueError),
            ):
                _requests(destination, self.collection, [self.trial])
