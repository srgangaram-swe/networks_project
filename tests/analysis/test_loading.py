import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from analysis.utils.load_data import _csv, _csv_bytes, attach_design, load_data
from src.artifacts import atomic_json, digest, read_json
from tests.analysis.support import fixture, refresh


class LoadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = fixture(Path(self.temp.name) / "export")

    def test_checked_legacy_and_bound_design(self):
        runs, requests, provenance = load_data(self.path)
        self.assertEqual((len(runs), len(requests)), (12, 6000))
        self.assertTrue(provenance["design_bound_to_export"])
        meta = read_json(self.path / "provenance.json")
        del meta["attempts_sha256"]
        atomic_json(self.path / "provenance.json", meta)
        self.assertFalse(load_data(self.path)[2]["design_bound_to_export"])
        (self.path / "attempts.json").unlink()
        self.assertNotIn("block", load_data(self.path)[0])

    def test_hashes_counts_and_symlinks_fail_closed(self):
        meta = read_json(self.path / "provenance.json")
        for field, value in (
            ("summary_sha256", "0" * 64),
            ("requests_sha256", "0" * 64),
            ("attempts_sha256", "0" * 64),
            ("run_count", 99),
            ("eligible_for_primary", True),
            ("schema_version", 2),
        ):
            atomic_json(self.path / "provenance.json", {**meta, field: value})
            with self.assertRaises(ValueError):
                load_data(self.path)
        atomic_json(self.path / "provenance.json", meta)
        original = self.path / "summary.csv"
        original.rename(self.path / "renamed.csv")
        original.symlink_to(self.path / "renamed.csv")
        with self.assertRaises(OSError):
            load_data(self.path)

    def test_semantic_summary_mutations_fail_even_after_rehash(self):
        original = pd.read_csv(self.path / "summary.csv")
        for column, value in (
            ("run_id", "invalid"),
            ("policy", "bad"),
            ("measurement_kind", "synthetic_fixture"),
            ("p99_censored", "yes"),
            ("eligible_for_primary", True),
            ("goodput_mbps", -1),
            ("p99_ms", float("inf")),
            ("p99_ms", None),
            ("scheduled", 499.5),
            ("flows", 3),
            ("sent", 2),
            ("on_time", 2),
            ("late_count", 999),
            ("not_sent_rate", 0.5),
            ("timeout_rate", 0.5),
            ("jitter_ms", 99),
        ):
            changed = original.astype(object).copy()
            changed.loc[0, column] = value
            changed.to_csv(self.path / "summary.csv", index=False)
            refresh(self.path)
            with self.subTest(column=column, value=value), self.assertRaises(ValueError):
                load_data(self.path)
        original.to_csv(self.path / "summary.csv", index=False)

    def test_request_and_design_corruption_fail(self):
        original = pd.read_csv(self.path / "requests.csv", dtype={"run_id": str})
        for column, value in (
            ("run_id", "unknown"),
            ("request_id", -1),
            ("outcome", "bad"),
            ("rtt_ms", 200),
            ("rtt_ms", None),
            ("send_lag_ms", None),
        ):
            changed = original.astype(object).copy()
            changed.loc[0, column] = value
            changed.to_csv(self.path / "requests.csv", index=False)
            refresh(self.path)
            with self.subTest(column=column), self.assertRaises(ValueError):
                load_data(self.path)
        changed = original.copy()
        changed.loc[1, "request_id"] = changed.loc[0, "request_id"]
        changed.to_csv(self.path / "requests.csv", index=False)
        refresh(self.path)
        with self.assertRaisesRegex(ValueError, "duplicate request"):
            load_data(self.path)
        original.to_csv(self.path / "requests.csv", index=False)
        design = read_json(self.path / "attempts.json")
        design["attempts"][0]["manifest_sha256"] = "0" * 64
        atomic_json(self.path / "attempts.json", design)
        refresh(self.path)
        with self.assertRaises(KeyError):
            load_data(self.path)

    def test_csv_bounds_and_duplicate_headers(self):
        path = self.path / "bounded.csv"
        path.write_text("a\n1\n2\n")
        with self.assertRaises(ValueError):
            _csv(path, digest(path), 1)
        path.write_text("a,a\n1,2\n")
        with self.assertRaises(ValueError):
            _csv(path, digest(path), 2)

    def test_compressed_requests_keep_hash_checks_and_expansion_bound(self):
        raw = self.path / "requests.csv"
        original = raw.read_bytes()
        zipped = self.path / "requests.csv.gz"
        zipped.write_bytes(gzip.compress(original, mtime=0))
        with self.assertRaisesRegex(ValueError, "not both"):
            load_data(self.path)
        raw.unlink()
        self.assertEqual(len(load_data(self.path)[1]), 6000)
        with patch("analysis.utils.load_data.MAX_JSON_BYTES", 64):
            with self.assertRaisesRegex(ValueError, "expanded CSV"):
                _csv_bytes(raw)
        for data in (b"invalid gzip", gzip.compress(original)[:-8]):
            zipped.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "compressed CSV"):
                load_data(self.path)
        zipped.write_bytes(gzip.compress(b"changed request bytes"))
        with self.assertRaisesRegex(ValueError, "hash"):
            load_data(self.path)
        zipped.unlink()
        zipped.symlink_to(self.path / "summary.csv")
        with self.assertRaises(OSError):
            load_data(self.path)

    def test_cpu_scope_and_percentages(self):
        original = pd.read_csv(self.path / "summary.csv")
        original["cpu_scope"] = "shared_host"
        original["cpu_busy_percent"] = 12.5
        original["cpu_iowait_percent"] = 1
        original.to_csv(self.path / "summary.csv", index=False)
        refresh(self.path)
        self.assertEqual(load_data(self.path)[0]["cpu_busy_percent"].iloc[0], 12.5)
        for field, value in (
            ("cpu_busy_percent", 101),
            ("cpu_scope", "unknown"),
            ("cpu_busy_percent", None),
            ("cpu_scope", "unavailable"),
        ):
            changed = original.astype(object).copy()
            changed.loc[0, field] = value
            changed.to_csv(self.path / "summary.csv", index=False)
            refresh(self.path)
            with self.assertRaises(ValueError):
                load_data(self.path)

    def test_recorded_design_cannot_change_pairing_or_source(self):
        import copy

        runs, _, _ = load_data(self.path)
        original = read_json(self.path / "attempts.json")
        changes = [
            lambda d: d["plan"]["schedule"].update(seed=999),
            lambda d: d.update(attempts="bad"),
            lambda d: d["attempts"].pop(),
            lambda d: d["attempts"][0].update(manifest_sha256=d["attempts"][1]["manifest_sha256"]),
            lambda d: d["plan"]["source"].update(commit="3" * 40),
        ]
        for change in changes:
            design = copy.deepcopy(original)
            change(design)
            with self.assertRaises(ValueError):
                attach_design(runs, design)
        design = copy.deepcopy(original)
        first = design["attempts"][0]
        choices = [a for a in design["attempts"] if a["cell_id"] != first["cell_id"]]
        for other in choices:
            altered = copy.deepcopy(design)
            altered["attempts"][0]["cell_id"] = other["cell_id"]
            with self.assertRaises(ValueError):
                attach_design(runs, altered)
