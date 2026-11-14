import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch

from src.artifacts import digest, read_json
from src.simulation import collect_simulation, default_workers, simulate_trial, simulation_plan
from src.table_export import export_run_tables
from tests.unit.physical_support import source


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = simulation_plan()

    def test_seeded_trials_retain_all_slots_and_export_bound_batches(self):
        paths = []
        collection = self.root / "collection"
        collection.mkdir()
        for index, cell in enumerate(self.plan["schedule"]["cells"][:2]):
            result = simulate_trial((str(collection / f"trial-{index}"), cell, 10, 561, source()))
            paths.append(result)
            summary = read_json(collection / result["directory"] / "summary.json")
            self.assertEqual(summary["scheduled"], 5000)
            self.assertEqual(
                summary["on_time"] + summary["timeout_count"] + summary["not_sent"], 5000
            )
            self.assertGreater(summary["not_sent"], 0)
        repeated = self.root / "repeat"
        simulate_trial((str(repeated), self.plan["schedule"]["cells"][0], 10, 561, source()))
        self.assertEqual(
            digest(repeated / "requests.csv"), digest(collection / "trial-0/requests.csv")
        )
        export_run_tables(self.root / "export", collection, self.plan, paths)
        index = read_json(self.root / "export/index.json")
        self.assertEqual(index["state"], "completed")
        self.assertEqual(len(index["batches"]), 1)
        self.assertEqual(
            read_json(self.root / "export/batch-001/provenance.json")["request_count"], 10000
        )
        with self.assertRaises(FileExistsError):
            export_run_tables(self.root / "export", collection, self.plan, paths)
        with self.assertRaises(ValueError):
            export_run_tables(self.root / "empty", collection, self.plan, [])
        (collection / "trial-0/manifest.json").write_text("changed")
        with self.assertRaisesRegex(ValueError, "manifest changed"):
            export_run_tables(self.root / "corrupt", collection, self.plan, paths)

    def test_pool_cancellation_timeout_and_worker_bounds(self):
        cancel = Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            collect_simulation(self.root / "cancel", self.plan, 1, cancel)
        cancel.clear()
        pending = MagicMock()
        pending.ready.return_value = False
        pool = MagicMock()
        pool.map_async.return_value = pending
        manager = MagicMock()
        manager.__enter__.return_value = pool
        context = MagicMock()
        context.Pool.return_value = manager
        with (
            patch("src.simulation.multiprocessing.get_context", return_value=context),
            patch("src.simulation.time.monotonic", side_effect=[0, 200]),
        ):
            with self.assertRaises(TimeoutError):
                collect_simulation(self.root / "timeout", self.plan, 2, cancel)
        with (
            patch("src.simulation.multiprocessing.get_context", return_value=context),
            patch.object(cancel, "wait", return_value=True),
        ):
            with self.assertRaises(InterruptedError):
                collect_simulation(self.root / "interrupt", self.plan, 2, cancel)
        pending.ready.side_effect = [False, True]
        pending.get.return_value = ["complete"]
        with patch("src.simulation.multiprocessing.get_context", return_value=context):
            self.assertEqual(
                collect_simulation(self.root / "ok", self.plan, 2, cancel), ["complete"]
            )
        for invalid in (0, 9, True):
            with self.assertRaises(ValueError):
                collect_simulation(self.root / "invalid", self.plan, invalid, cancel)
        with patch("src.simulation.os.cpu_count", return_value=None):
            self.assertEqual(default_workers(), 1)
        with self.assertRaises(ValueError):
            simulation_plan(0)
        with self.assertRaises(ValueError):
            simulation_plan(seed=-1)
