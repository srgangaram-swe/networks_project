import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.artifacts import atomic_json, read_json
from src.physical_lease import PhysicalLease, inspect_interfaces
from src.processes import CommandError
from tests.unit.physical_support import Kernel, profile


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".local").mkdir()
        self.item = profile(self.root)["roles"]["router"]
        self.kernel = Kernel()
        for name, value in (
            ("run_command", self.kernel),
            ("namespace_identity", self.kernel.identities.get),
            ("require_linux", lambda: None),
        ):
            patched = patch(f"src.physical_lease.{name}", value)
            patched.start()
            self.addCleanup(patched.stop)

    def prepare(self):
        return PhysicalLease.prepare(self.item, "router", "a" * 12)

    def test_prepare_and_idempotent_cleanup_restore_only_owned_interfaces(self):
        before = copy.deepcopy(self.kernel.links)
        lease = self.prepare()
        self.assertNotIn("router0", self.kernel.links)
        self.assertEqual(
            set(self.kernel.namespaces[lease.state["namespace"]]), {"to-client", "to-server"}
        )
        loaded = PhysicalLease.load(self.item, "router", "a" * 12)
        loaded.cleanup()
        loaded.cleanup()
        self.assertEqual(self.kernel.links, before)
        self.assertFalse(self.kernel.identities)
        self.assertEqual(read_json(lease.directory / "lease.json")["phase"], "closed")

    def test_interface_preflight_rejects_management_and_nonblank_state(self):
        for change in (
            {"flags": ["UP"]},
            {"addr_info": [{"local": "192.0.2.1"}]},
            {"master": "bridge0"},
            {"link_type": "loopback"},
        ):
            before = self.kernel.links["router0"].copy()
            self.kernel.links["router0"].update(change)
            with self.assertRaises(PermissionError):
                inspect_interfaces(self.item)
            self.kernel.links["router0"] = before
        self.kernel.routes = [{"dev": "router0", "dst": "default"}]
        with self.assertRaises(PermissionError):
            self.prepare()
        self.assertFalse(self.kernel.identities)
        self.kernel.routes = [{"dst": "default", "nexthops": [{"dev": "router0"}]}]
        with self.assertRaises(PermissionError):
            self.prepare()
        self.assertFalse(self.kernel.identities)
        self.kernel.routes = []
        self.kernel.queues = [{"kind": "cake", "handle": "1:"}]
        with self.assertRaises(PermissionError):
            self.prepare()

    def test_replaced_namespaces_and_live_processes_block_cleanup(self):
        lease = self.prepare()
        namespace = lease.state["namespace"]
        original = self.kernel.identities[namespace]
        self.kernel.identities[namespace] = [9, 9]
        with self.assertRaises(PermissionError):
            lease.cleanup()
        self.kernel.identities[namespace] = original
        self.kernel.pids[namespace] = b"1234\n"
        with self.assertRaisesRegex(RuntimeError, "live processes"):
            lease.cleanup()
        self.kernel.pids.clear()
        lease.cleanup()

    def test_partial_setup_failure_returns_interfaces_and_preserves_error(self):
        def fail(command, **kwargs):
            if "name" in command and "to-server" in command:
                raise CommandError("rename failed")
            return self.kernel(command, **kwargs)

        with patch("src.physical_lease.run_command", side_effect=fail):
            with self.assertRaisesRegex(CommandError, "rename failed"):
                self.prepare()
        self.assertEqual(set(self.kernel.links), {"client0", "server0", "router0", "router1"})
        self.assertFalse(self.kernel.identities)

    def test_bad_journal_permissions_names_and_profiles_are_rejected(self):
        lease = self.prepare()
        lease.directory.chmod(0o755)
        with self.assertRaises(PermissionError):
            PhysicalLease.load(self.item, "router", "a" * 12)
        lease.directory.chmod(0o700)
        original = copy.deepcopy(lease.state)
        for key, value in (
            ("role", "client"),
            ("namespace", "unowned"),
            ("owned", {"other": [1, 2]}),
        ):
            atomic_json(lease.directory / "lease.json", {**original, key: value})
            with self.assertRaises(ValueError):
                PhysicalLease.load(self.item, "router", "a" * 12)
        atomic_json(lease.directory / "lease.json", original)
        lease.cleanup()
