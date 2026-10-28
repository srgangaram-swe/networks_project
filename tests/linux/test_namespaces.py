"""Explicitly enabled tests for an isolated Linux host. Never run against host NICs."""

import os
import platform
import re
import tempfile
import unittest
import uuid
from pathlib import Path
from threading import Event
from unittest.mock import patch

from src.artifacts import parse_json, read_json
from src.bundle_validation import validate_bundle
from src.experiment_config import POLICIES
from src.processes import CommandError, run_command
from src.queue_policy import counter_delta
from src.testbed_backend import Backend
from src.topology import CLIENT_ADDRESS, SERVER_ADDRESS, Topology
from src.topology_runtime import OwnedTopology, namespace_identity
from src.trial import TrialConfig, _phase, run_trial

ENABLED = (
    platform.system() == "Linux"
    and os.geteuid() == 0
    and os.environ.get("NETWORKS_RUN_PRIVILEGED") == "1"
)


def root_queue(bundle: Path, name: str) -> dict:
    rows = read_json(bundle / name)["snapshots"]["router_queues"]
    return next(row for row in rows if row.get("dev") == "to-client" and row.get("handle") == "1:")


@unittest.skipUnless(
    ENABLED,
    "requires root on isolated Linux and NETWORKS_RUN_PRIVILEGED=1; issues #3, #5, #6, #11",
)
class NamespaceTests(unittest.TestCase):
    def test_every_queue_profile_runs_and_leaves_no_owned_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            for policy in sorted(POLICIES):
                path = Path(directory) / policy
                config = TrialConfig(
                    mode="namespace", policy=policy, measurement_seconds=2, warmup_seconds=1
                )
                run_trial(path, config)
                self.assertTrue(validate_bundle(path)["integrity_valid"])
                counters = counter_delta(
                    root_queue(path, "queues-before.json"), root_queue(path, "queues-after.json")
                )
                self.assertGreater(counters["bytes"], 0)
                self.assertGreater(counters["packets"], 0)
                self.assertEqual(read_json(path / "topology/ownership.json")["owned"], {})
                capture = read_json(path / "foreground.json")
                replies = [row for row in capture["records"] if row["received_ns"] is not None]
                self.assertTrue(replies)
                self.assertGreater(
                    min(row["received_ns"] - row["sent_ns"] for row in replies), 18_000_000
                )

    def test_above_capacity_demand_with_one_and_eight_flows(self):
        with tempfile.TemporaryDirectory() as directory:
            for flows in (1, 8):
                path = Path(directory) / f"flows-{flows}"
                run_trial(
                    path,
                    TrialConfig(
                        mode="namespace",
                        policy="fifo",
                        flows=flows,
                        aggregate_bps=110_000_000,
                        measurement_seconds=3,
                        warmup_seconds=1,
                    ),
                )
                self.assertTrue(validate_bundle(path)["integrity_valid"])
                bulk = read_json(path / "bulk.json")
                self.assertEqual(bulk["actual_flows"], flows)
                self.assertEqual(bulk["per_flow_bps"] * flows, 110_000_000)
                self.assertGreater(bulk["goodput_mbps"], 0)
                self.assertLess(bulk["goodput_mbps"], 110)
                counters = counter_delta(
                    root_queue(path, "queues-before.json"), root_queue(path, "queues-after.json")
                )
                self.assertGreaterEqual(counters["bytes"], bulk["receiver_bytes"])
                foreground = read_json(path / "foreground.json")
                self.assertEqual(foreground["config"]["requests_per_second"], 500)
                self.assertEqual(len(foreground["records"]), 2000)
                self.assertEqual(read_json(path / "topology/ownership.json")["owned"], {})
                print(
                    f"Above-capacity check: {flows} flows, 110 Mb/s requested, "
                    f"{bulk['goodput_mbps']:.3f} Mb/s received, {counters['bytes']} queued bytes."
                )


@unittest.skipUnless(
    ENABLED, "requires explicit root-enabled Linux namespace verification; issue #5"
)
class NamespaceOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.sentinel = Topology(uuid.uuid4().hex[:12]).namespace("client")
        run_command(("ip", "netns", "add", self.sentinel))
        self.sentinel_identity = namespace_identity(self.sentinel)
        self.addCleanup(self.remove_sentinel)

    def remove_sentinel(self):
        self.assertEqual(namespace_identity(self.sentinel), self.sentinel_identity)
        run_command(("ip", "netns", "delete", self.sentinel))

    def assert_cleaned(self, directory):
        with OwnedTopology(directory) as lease:
            lease.cleanup()
            lease.cleanup()
            self.assertEqual(lease.state["owned"], {})
            for role in ("client", "router", "server"):
                self.assertIsNone(namespace_identity(lease.topology.namespace(role)))
        self.assertEqual(namespace_identity(self.sentinel), self.sentinel_identity)

    def test_partial_setup_failure_removes_only_the_owned_namespaces(self):
        def fail_after_links_exist(command):
            if "ethtool" in command:
                raise CommandError("injected failure after real namespace and veth creation")
            return run_command(command)

        path = self.directory / "partial"
        topology = Topology(uuid.uuid4().hex[:12])
        with OwnedTopology.create(path, topology, run=fail_after_links_exist) as lease:
            try:
                with self.assertRaisesRegex(CommandError, "injected failure"):
                    lease.setup()
            finally:
                lease.cleanup()
        self.assert_cleaned(path)

    def test_interrupted_trial_preserves_failure_and_supports_repeated_cleanup(self):
        def interrupt(bundle, state, deadline, cancel, futures):
            if state == "measurement":
                cancel.set()
            return _phase(bundle, state, deadline, cancel, futures)

        path = self.directory / "cancelled"
        with patch("src.trial._phase", side_effect=interrupt):
            with self.assertRaises(InterruptedError):
                run_trial(path, TrialConfig(mode="namespace", policy="fifo"), Event())
        self.assertEqual(read_json(path / "manifest.json")["state"], "cancelled")
        self.assert_cleaned(path / "topology")

    def test_routes_offloads_and_delay_in_both_directions(self):
        backend = Backend("namespace", "fifo", self.directory)
        self.addCleanup(backend.close)
        backend.setup()
        for role, peer, gateway in (
            ("client", SERVER_ADDRESS, "10.203.0.1"),
            ("server", CLIENT_ADDRESS, "10.203.0.5"),
        ):
            route = parse_json(
                run_command(backend.topology.link(role, "-j", "route", "get", peer)).stdout
            )
            self.assertEqual(route[0]["gateway"], gateway)
            ping = run_command(
                backend.command(
                    role, ("ping", "-n", "-q", "-c", "3", "-i", "0.05", "-W", "2", peer)
                ),
                timeout=5,
            )
            minimum = re.search(rb"=\s*([0-9.]+)/[0-9.]+/[0-9.]+/[0-9.]+ ms", ping.stdout)
            self.assertIsNotNone(minimum, ping.stdout)
            self.assertGreater(float(minimum[1]), 18)
            self.assertLess(float(minimum[1]), 200)
            settings = run_command(backend.command(role, ("ethtool", "-k", "eth0"))).stdout
            for feature in (
                b"tcp-segmentation-offload",
                b"generic-segmentation-offload",
                b"generic-receive-offload",
            ):
                self.assertIn(feature + b": off", settings)
        backend.close()
        self.assert_cleaned(self.directory / "topology")


if __name__ == "__main__":
    unittest.main()
