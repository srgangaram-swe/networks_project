import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from threading import Event
from unittest.mock import patch

from src import physical_campaign as campaign
from src.artifacts import atomic_json, json_bytes, read_json
from src.bundle_validation import ARTIFACTS
from src.physical_profile import check_inspections
from src.processes import CommandResult
from src.trial import ROOT, TrialConfig
from tests.unit.physical_support import profile, source


class PhysicalCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = profile(self.root)
        raw = read_json(ROOT / "configs/pilot.json")
        self.plan = campaign.physical_plan(raw, source(), transport="tcp", shadow_forecast=True)
        self.plan["schedule"]["cells"] = self.plan["schedule"]["cells"][:2]

    def test_serial_collection_binds_each_cell_source_and_derived_files(self):
        observed = []

        def command(args, **kwargs):
            request = json.loads(args[-1])
            observed.append(request)
            return CommandResult(0, b"{}", b"")

        def retrieve(local, *_):
            request = observed[-1]
            atomic_json(local / "configuration.json", request["configuration"])
            atomic_json(local / "manifest.json", {"source": source()})

        with (
            patch.object(campaign, "run_command", side_effect=command),
            patch.object(campaign, "_retrieve", side_effect=retrieve),
            patch.object(campaign, "summarize", return_value=({"scheduled": 1}, [])),
        ):
            trials = campaign.collect_physical(
                self.root / "collection",
                self.plan,
                self.profile,
                Event(),
                lambda *_args, **_kwargs: None,
            )
        self.assertEqual(len(trials), 2)
        self.assertTrue(all(row["configuration"]["transport"] == "tcp" for row in observed))
        self.assertEqual(read_json(self.root / "collection/progress.json")["state"], "completed")
        for row in trials:
            self.assertIn("requests", row["table_hashes"])
            self.assertEqual(row["state"], "completed")

    def test_collection_cancellation_and_persistence_keep_original_failures(self):
        cancel = Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            campaign.collect_physical(
                self.root / "cancel", self.plan, self.profile, cancel, lambda *_: None
            )
        for broken_storage in (False, True):
            output = self.root / str(broken_storage)
            original = campaign.atomic_json

            def persist(path, data, broken_storage=broken_storage, original=original):
                if broken_storage and path.name == "failure.json":
                    raise OSError("cannot retain failure")
                original(path, data)

            with (
                patch.object(
                    campaign, "run_command", side_effect=RuntimeError("remote disconnected")
                ),
                patch.object(campaign, "atomic_json", side_effect=persist),
            ):
                with self.assertRaisesRegex(RuntimeError, "remote disconnected") as caught:
                    campaign.collect_physical(
                        output, self.plan, self.profile, Event(), lambda *_a, **_k: None
                    )
            if broken_storage:
                self.assertIn("cannot retain failure", caught.exception.__notes__[0])
            else:
                self.assertTrue(
                    read_json(output / "trial-001/failure.json")["remote_evidence_retained"]
                )

    def test_retrieval_whitelist_and_treatment_cross_checks(self):
        for mode in ("physical", "loopback", "unsafe"):
            output = self.root / mode
            output.mkdir()
            names = dict.fromkeys(ARTIFACTS, "0" * 64)
            if mode == "unsafe":
                names["../../outside"] = "0" * 64
            manifest = {"mode": mode, "artifacts": names}

            def fetch(args, manifest=manifest, **kwargs):
                name = json.loads(args[-1])["artifact"]
                return CommandResult(
                    0, json_bytes(manifest if name == "manifest.json" else {}), b""
                )

            with (
                patch.object(campaign, "run_command", side_effect=fetch),
                patch.object(campaign, "validate_bundle"),
            ):
                if mode == "physical":
                    campaign._retrieve(output, self.profile, "a" * 12)
                    self.assertEqual(
                        {path.name for path in output.iterdir()}, ARTIFACTS | {"manifest.json"}
                    )
                else:
                    with self.assertRaises(ValueError):
                        campaign._retrieve(output, self.profile, "a" * 12)
        output = self.root / "binding"
        output.mkdir()
        config = TrialConfig(mode="physical", policy="fifo")
        atomic_json(output / "manifest.json", {"source": source()})
        atomic_json(output / "configuration.json", asdict(config))
        campaign._check_treatment(output, source(), config)
        with self.assertRaises(ValueError):
            campaign._check_treatment(output, {**source(), "commit": "3" * 40}, config)
        with self.assertRaises(ValueError):
            campaign._check_treatment(
                output, source(), TrialConfig(mode="physical", policy="fq_codel")
            )
        with self.assertRaises(ValueError):
            check_inspections(
                [{"network_host": "same", "interfaces": [{"ifindex": 3}, {"ifindex": 3}]}]
            )
