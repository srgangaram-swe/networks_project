import unittest

from src.experiment_config import POLICIES
from src.queue_policy import check_queue_kinds, counter_delta, policy_commands
from src.topology import Topology


class QueueTests(unittest.TestCase):
    def test_every_profile_is_isolated_and_fixed_rate(self):
        topology = Topology("012345abcdef")
        for policy in POLICIES:
            commands = policy_commands(topology, policy)
            self.assertTrue(
                all(
                    command[:4] == ("ip", "netns", "exec", topology.namespace("router"))
                    for command in commands
                )
            )
            text = " ".join(" ".join(command) for command in commands)
            self.assertIn("100mbit", text)
            self.assertNotIn("replace", text)
            self.assertEqual(text.count("dsfield set 0"), 2)
        bounded = " ".join(
            " ".join(command) for command in policy_commands(topology, "cake_bounded")
        )
        self.assertIn("conform-exceed continue/pipe", bounded)
        self.assertIn("priority 1:2", bounded)
        self.assertIn("priority 1:3", bounded)
        self.assertIn("src_port 42000", bounded)
        self.assertIn("dst_port 42001", bounded)
        self.assertIn("csum ip4h", bounded)
        with self.assertRaises(ValueError):
            policy_commands(topology, "unknown")

    def test_attachment_checks_do_not_claim_rate_validation(self):
        cake = [{"dev": "to-client", "kind": "cake", "handle": "1:"}]
        check_queue_kinds(cake, "cake_bounded")
        for bad in ({}, [None], [], [{"kind": "cake"}]):
            with self.assertRaises(ValueError):
                check_queue_kinds(bad, "cake_best_effort")
        fifo = [{"dev": "to-client", "kind": "htb", "handle": "1:"}]
        with self.assertRaises(ValueError):
            check_queue_kinds(fifo, "fifo")
        fifo.append({"dev": "to-client", "kind": "bfifo", "parent": "1:10"})
        check_queue_kinds(fifo, "fifo")

    def test_counter_differences_reject_reset_and_identity_changes(self):
        before = {
            "dev": "to-client",
            "kind": "cake",
            "handle": "1:",
            "bytes": 100,
            "packets": 2,
            "drops": 0,
        }
        after = dict(before, bytes=200, packets=4, drops=1)
        self.assertEqual(counter_delta(before, after), {"bytes": 100, "packets": 2, "drops": 1})
        for changed in (dict(after, handle="2:"), dict(after, bytes=1), dict(after, drops=True)):
            with self.assertRaises(ValueError):
                counter_delta(before, changed)


if __name__ == "__main__":
    unittest.main()
