import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import physical_jobs, physical_worker
from src.artifacts import atomic_json, read_json
from src.run_bundle import RunBundle
from src.trial import TrialConfig
from src.trial_observers import observers
from tests.unit.physical_support import source


class ObserverLifecycleTests(unittest.TestCase):
    def test_observers_join_before_manifest_registration_and_retain_drop_quality(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for transport, shadow in (("udp", False), ("udp", True), ("tcp", False), ("tcp", True)):
                output = root / f"{transport}-{shadow}"
                bundle = RunBundle(output, {"mode": "namespace", "policy": "fifo"}, source())
                calls = []

                class Service:
                    def __init__(self, args, *unused, **kwargs):
                        self.args = args
                        self.output = Path(args[args.index("--output") + 1])

                    def __enter__(self, calls=calls, output=output):
                        calls.append(("start", self.output.name))
                        if self.output.name == "shadow-forecast.json":
                            (output / "events.fifo").touch(mode=0o600)
                        return self

                    def __exit__(self, *_, calls=calls):
                        calls.append(("stop", self.output.name))
                        atomic_json(self.output, {"event_stream": {"sent": 1, "dropped": 1}})

                backend = SimpleNamespace(
                    client_address="10.203.0.2",
                    server_address="10.203.0.6",
                    command=lambda role, args: args,
                )
                config = TrialConfig(
                    mode="namespace", policy="fifo", transport=transport, shadow_forecast=shadow
                )
                with (
                    patch("src.trial_observers.Service", Service),
                    observers(bundle, config, backend),
                ):
                    atomic_json(
                        output / "foreground-transport.json",
                        {"event_stream": {"sent": 1, "dropped": 0}},
                    )
                    self.assertNotIn("foreground-transport.json", bundle.manifest["artifacts"])
                self.assertIn("foreground-transport.json", bundle.manifest["artifacts"])
                if shadow:
                    result = read_json(output / "shadow-forecast.json")
                    self.assertEqual(result["producer_events_dropped"], int(transport == "tcp"))
                    self.assertEqual(calls[-1], ("stop", "shadow-forecast.json"))
                    self.assertFalse((output / "events.fifo").exists())
                self.assertEqual(
                    "tcp-observer.json" in bundle.manifest["artifacts"], transport == "tcp"
                )

    def test_passive_worker_paths_stay_inside_its_client_bundle(self):
        root = Path("/experiment")
        request = {"role": "client", "token": "a" * 12}
        parent = root / ".local/physical-runs" / request["token"]
        args = (
            "--output",
            str(parent / "tcp-observer.json"),
            "--events-fifo",
            str(parent / "events.fifo"),
        )
        physical_worker._observer_paths(request, args, root)
        physical_worker._observer_paths(request, args[:2], root)
        for bad_request, bad_args in (
            ({**request, "role": "server"}, args),
            (request, ("--output", "/outside")),
            (request, ("--output",)),
        ):
            with self.assertRaises(PermissionError):
                physical_worker._observer_paths(bad_request, bad_args, root)

    def test_pidfd_signals_only_the_process_with_the_retained_start_identity(self):
        record = {"pid": 12345, "start": "123"}
        for current in ("123", "456"):
            with (
                patch.object(physical_jobs.os, "pidfd_open", return_value=77, create=True),
                patch.object(physical_jobs.signal, "pidfd_send_signal", create=True) as signal,
                patch.object(physical_jobs, "process_start", return_value=current),
                patch.object(physical_jobs.os, "close") as close,
            ):
                physical_jobs._signal_owned(record)
            self.assertEqual(signal.called, current == "123")
            close.assert_called_once_with(77)
        with patch.object(
            physical_jobs.os, "pidfd_open", side_effect=ProcessLookupError, create=True
        ):
            physical_jobs._signal_owned(record)
        with (
            patch.object(physical_jobs.os, "pidfd_open", return_value=77, create=True),
            patch.object(
                physical_jobs.signal,
                "pidfd_send_signal",
                side_effect=ProcessLookupError,
                create=True,
            ),
            patch.object(physical_jobs, "process_start", return_value="123"),
            patch.object(physical_jobs.os, "close"),
        ):
            physical_jobs._signal_owned(record)
