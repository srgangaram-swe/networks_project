import tempfile
import unittest
from pathlib import Path

from src.artifacts import atomic_json
from src.processes import CommandError, CommandResult
from src.topology import ROLES, Topology, inspection_commands, setup_commands
from src.topology_runtime import OwnedTopology


class FakeNetwork:
    def __init__(self):
        self.namespaces = {}
        self.calls = []
        self.fail = None
        self.live = False

    def run(self, command):
        self.calls.append(command)
        if self.fail and self.fail(command):
            raise CommandError("injected failure")
        if command[:3] == ("ip", "netns", "add"):
            self.namespaces[command[3]] = [1, len(self.calls)]
        elif command[:3] == ("ip", "netns", "delete"):
            self.namespaces.pop(command[3], None)
        output = b"123\n" if self.live and command[:3] == ("ip", "netns", "pids") else b""
        return CommandResult(0, output, b"")


class TopologyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "state"
        self.network = FakeNetwork()
        self.topology = Topology("012345abcdef")

    def create(self):
        lease = OwnedTopology.create(
            self.directory,
            self.topology,
            run=self.network.run,
            identity=self.network.namespaces.get,
        )
        self.addCleanup(lease.__exit__)
        return lease

    def test_commands_are_confined_to_namespaces(self):
        allowed = {self.topology.namespace(role) for role in ROLES}
        for command in setup_commands(self.topology) + list(
            inspection_commands(self.topology).values()
        ):
            self.assertEqual(command[0], "ip")
            namespace = command[2] if command[1] == "-n" else command[3]
            self.assertIn(namespace, allowed)
        plan = " ".join(" ".join(command) for command in setup_commands(self.topology))
        self.assertEqual(plan.count("10ms"), 2)
        self.assertNotIn(" flush ", plan)

    def test_setup_cleanup_and_repeated_cleanup(self):
        lease = self.create()
        self.network.namespaces["unrelated"] = [9, 9]
        lease.setup()
        lease.verify()
        with self.assertRaises(FileExistsError):
            lease.setup()
        lease.cleanup()
        lease.cleanup()
        self.assertEqual(self.network.namespaces, {"unrelated": [9, 9]})

    def test_partial_setup_rolls_back_only_created_namespaces(self):
        lease = self.create()
        self.network.fail = lambda command: "ethtool" in command
        with self.assertRaises(CommandError):
            lease.setup()
        self.assertFalse(self.network.namespaces)

    def test_collision_and_replacement_are_preserved(self):
        lease = self.create()
        name = self.topology.namespace("client")
        self.network.namespaces[name] = [9, 9]
        with self.assertRaises(FileExistsError):
            lease.setup()
        self.assertEqual(self.network.namespaces[name], [9, 9])
        self.network.namespaces.clear()
        lease.setup()
        self.network.namespaces[name] = [8, 8]
        with self.assertRaises(PermissionError):
            lease.verify()
        with self.assertRaisesRegex(RuntimeError, "replaced"):
            lease.cleanup()
        self.assertEqual(self.network.namespaces[name], [8, 8])

    def test_cleanup_retains_failure_for_retry(self):
        lease = self.create()
        lease.setup()
        self.network.live = True
        with self.assertRaisesRegex(RuntimeError, "live processes"):
            lease.cleanup()
        self.assertEqual(len(lease.state["owned"]), 3)
        self.network.live = False
        lease.cleanup()

    def test_missing_resources_and_incomplete_topology(self):
        lease = self.create()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            lease.verify()
        lease.setup()
        self.network.namespaces.clear()
        lease.cleanup()
        self.assertFalse(lease.state["owned"])

    def test_tokens_and_journal_validation(self):
        for token in (None, "../anything", "ABCDEF012345", "abc"):
            with self.assertRaises(ValueError):
                Topology(token)
        with self.assertRaises(ValueError):
            self.topology.namespace("host")
        lease = self.create()
        bad = dict(lease.state, owned={"unrelated": [1, 1]})
        atomic_json(self.directory / "ownership.json", bad)
        with self.assertRaises(ValueError):
            OwnedTopology(self.directory)


if __name__ == "__main__":
    unittest.main()
