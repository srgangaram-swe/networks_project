import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event

from src.artifacts import digest, read_json
from src.processes import terminate
from src.simulation import collect_simulation, simulation_plan
from src.table_export import export_run_tables

ROOT = Path(__file__).resolve().parents[2]


class SimulationIntegrationTests(unittest.TestCase):
    def test_real_spawn_pool_is_identical_to_serial_and_retains_threefold_volume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = simulation_plan()
            serial = collect_simulation(root / "serial", plan, 1, Event())
            parallel = collect_simulation(root / "parallel", plan, 4, Event())
            self.assertEqual(len(serial), 48)
            for one, many in zip(serial, parallel, strict=True):
                self.assertEqual(one["manifest_sha256"], many["manifest_sha256"])
                self.assertEqual(one["table_hashes"], many["table_hashes"])
                path = many["directory"]
                self.assertEqual(
                    digest(root / "serial" / path / "requests.csv"),
                    digest(root / "parallel" / path / "requests.csv"),
                )
            export_run_tables(root / "export", root / "parallel", plan, parallel)
            index = read_json(root / "export/index.json")
            self.assertEqual(len(index["batches"]), 3)
            requests = sum(
                read_json(root / "export" / row["directory"] / "provenance.json")["request_count"]
                for row in index["batches"]
            )
            self.assertEqual(requests, 240000)

    def test_real_cli_cancellation_retains_a_cancelled_status_and_reaps_the_pool(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "cancelled"
            child = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "scripts/pipeline.py"),
                    "--topology",
                    "local",
                    "--simulation-multiplier",
                    "10",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                # The first event is emitted before any worker starts, so cancellation
                # can be checked without guessing a scheduler-dependent delay.
                import selectors

                with selectors.DefaultSelector() as poll:
                    poll.register(child.stderr, selectors.EVENT_READ)
                    self.assertTrue(poll.select(10))
                    line = child.stderr.readline()
                self.assertIn(b"stage_started", line)
                os.kill(child.pid, signal.SIGTERM)
                _, errors = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 130, errors.decode())
                self.assertEqual(read_json(output / "status.json")["state"], "cancelled")
            finally:
                terminate(child)
                child.stdout.close()
                child.stderr.close()
