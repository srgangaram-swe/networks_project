import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.artifacts import atomic_json
from src.processes import CommandError, CommandResult
from src.testbed_backend import Backend
from src.topology_runtime import OwnedTopology, namespace_identity, require_linux
from tests.unit.test_topology import FakeNetwork


class BackendTests(unittest.TestCase):
    def test_namespace_adapter_uses_owned_lease_and_checks_attachment(self):
        backend = Backend("namespace", "fifo", Path("unused"))
        lease = MagicMock()

        def command(args):
            data = []
            if "qdisc" in args and backend.topology.namespace("router") in args:
                data = [
                    {"dev": "to-client", "kind": "htb", "handle": "1:"},
                    {"dev": "to-client", "kind": "bfifo", "parent": "1:10"},
                ]
            return CommandResult(0, json.dumps(data).encode(), b"")

        with (
            patch("src.testbed_backend.require_linux"),
            patch("src.testbed_backend.OwnedTopology.create", return_value=lease),
            patch("src.testbed_backend.run_command", side_effect=command),
        ):
            backend.setup()
            self.assertEqual(backend.command("client", ("true",))[:3], ("ip", "netns", "exec"))
            result = backend.snapshot()
            self.assertTrue(result["attachment_checked"])
            self.assertFalse(result["calibrated"])
            backend.close()
            backend.close()
        lease.cleanup.assert_called_once()

    def test_invalid_and_uninitialized_backends_fail_before_use(self):
        for mode, policy in (("host", "none"), ("loopback", "cake_bounded")):
            with self.assertRaises(ValueError):
                Backend(mode, policy, Path("unused"))
        backend = Backend("namespace", "fifo", Path("unused"))
        with self.assertRaises(RuntimeError):
            backend.command("router", ("true",))
        with self.assertRaises(RuntimeError):
            backend.snapshot()
        with patch("src.topology_runtime.platform.system", return_value="Darwin"):
            with self.assertRaises(PermissionError):
                backend.setup()

    def test_linux_and_identity_boundaries(self):
        with (
            patch("src.topology_runtime.platform.system", return_value="Linux"),
            patch("src.topology_runtime.os.geteuid", return_value=0),
        ):
            require_linux()
        with patch.object(Path, "stat", side_effect=FileNotFoundError):
            self.assertIsNone(namespace_identity("missing"))
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_dev=2, st_ino=3)):
            self.assertEqual(namespace_identity("owned"), [2, 3])


class OwnershipFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "state"
        self.root.mkdir(mode=0o700)
        self.state = {"schema_version": 1, "token": "012345abcdef", "owned": {}}
        self.save(self.state)

    def save(self, state):
        atomic_json(self.root / "ownership.json", state)

    def test_corrupt_journal_and_permissions_are_rejected(self):
        name = "np-012345abcdef-client"
        values = (
            {},
            dict(self.state, schema_version=True),
            dict(self.state, owned=[]),
            dict(self.state, owned={name: [True, 1]}),
            dict(self.state, owned={name: [-1, 1]}),
        )
        for value in values:
            self.save(value)
            with self.assertRaises(ValueError):
                OwnedTopology(self.root)
        self.save(self.state)
        self.root.chmod(0o777)
        with self.assertRaises(PermissionError):
            OwnedTopology(self.root)

    def test_lock_prevents_concurrent_cleanup(self):
        with OwnedTopology(self.root):
            with self.assertRaises(BlockingIOError):
                OwnedTopology(self.root)

    def test_unobserved_creation_and_cleanup_error_preserve_primary(self):
        network = FakeNetwork()
        with OwnedTopology(self.root, run=network.run, identity=lambda _: None) as lease:
            with self.assertRaisesRegex(CommandError, "not observable"):
                lease.setup()
        network = FakeNetwork()
        network.fail = lambda command: "ethtool" in command or "delete" in command
        with OwnedTopology(self.root, run=network.run, identity=network.namespaces.get) as lease:
            with self.assertRaises(CommandError) as error:
                lease.setup()
            self.assertIn("cleanup also failed", error.exception.__notes__[0])
            network.fail = None
            lease.cleanup()

    def test_delete_must_really_remove_the_recorded_namespace(self):
        name = "np-012345abcdef-client"
        self.save(dict(self.state, owned={name: [1, 2]}))
        with OwnedTopology(
            self.root, run=lambda _: CommandResult(0, b"", b""), identity=lambda _: [1, 2]
        ) as lease:
            with self.assertRaisesRegex(RuntimeError, "survived deletion"):
                lease.cleanup()


if __name__ == "__main__":
    unittest.main()
