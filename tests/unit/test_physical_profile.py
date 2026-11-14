import shlex
import unittest
from pathlib import Path
from unittest.mock import patch

from src.physical_commands import allowed_kernel_commands, split_command
from src.physical_profile import (
    decode_payload,
    host_command,
    payload,
    role_path,
    validate_profile,
    worker_command,
)
from src.topology import Topology, configuration_commands
from tests.unit.physical_support import profile


class ProfileTests(unittest.TestCase):
    def test_profiles_and_remote_arguments_have_exact_round_trip(self):
        raw = profile(Path("/tmp/project with spaces"))
        self.assertEqual(validate_profile(raw), raw)
        request = {"path": "/tmp/a 'b; c", "rows": [1, 2]}
        self.assertEqual(decode_payload(payload(request)), request)
        item = {**raw["roles"]["client"], "host": "lab-client", "ssh_config": "/tmp/ssh config"}
        command = host_command(item, ("python", "a 'b; c"), privileged=True)
        self.assertEqual(shlex.split(command[-1]), ["sudo", "-n", "python", "a 'b; c"])
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertEqual(command[1:3], ("-F", "/tmp/ssh config"))
        with patch("src.physical_profile.os.geteuid", return_value=0):
            self.assertEqual(
                host_command(raw["roles"]["client"], ("python",), privileged=True), ("python",)
            )
        with patch("src.physical_profile.os.geteuid", return_value=1000):
            self.assertEqual(
                host_command(raw["roles"]["client"], ("python",), privileged=True),
                ("sudo", "-n", "python"),
            )
        self.assertEqual(host_command(raw["roles"]["client"], ("python",)), ("python",))
        self.assertIn("--request", worker_command(raw, "client", "inspect", "a" * 12))
        self.assertEqual(role_path(item, "a" * 12, "client").name, "physical-aaaaaaaaaaaa-client")

    def test_invalid_profile_fields_and_aliases_are_rejected(self):
        for mutate in (
            lambda p: p.update(extra=True),
            lambda p: p.update(schema_version=True),
            lambda p: p.update(roles=[]),
            lambda p: p["roles"].pop("server"),
            lambda p: p["roles"]["client"].update(extra=1),
            lambda p: p["roles"]["client"].update(host="-oProxyCommand=bad"),
            lambda p: p["roles"]["client"].update(repository="relative"),
            lambda p: p["roles"]["client"].update(repository="/tmp/../bad"),
            lambda p: p["roles"]["client"].update(repository="/tmp/\nother"),
            lambda p: p["roles"]["client"].update(interfaces={"wrong": "eth0"}),
            lambda p: p["roles"]["client"].update(interfaces={"eth0": "lo"}),
            lambda p: p["roles"]["client"].update(interfaces={"eth0": "x" * 16}),
            lambda p: p["roles"]["client"].update(ssh_config="relative"),
            lambda p: p["roles"]["client"].update(ssh_config="/tmp/\nbad"),
            lambda p: p["roles"]["server"].update(interfaces={"eth0": "client0"}),
        ):
            raw = profile(Path("/tmp/project"))
            mutate(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate_profile(raw)
        for bad in ([], {}, {"schema_version": 1, "roles": {"client": None}}):
            with self.assertRaises(ValueError):
                validate_profile(bad)
        for text in ("[]", "x", " " * 16385):
            with self.assertRaises(ValueError):
                decode_payload(text)
        with self.assertRaises(ValueError):
            payload({"large": "x" * 16385})
        with self.assertRaises(ValueError):
            role_path(profile(Path("/tmp/x"))["roles"]["client"], "a" * 12, "unknown")

    def test_shared_plan_is_split_only_inside_its_owned_role(self):
        topology = Topology("a" * 12)
        for command in configuration_commands(topology):
            role, inner = split_command(command, topology)
            self.assertIn(inner, allowed_kernel_commands(role, topology.token))
        with self.assertRaises(ValueError):
            split_command(("rm", "/tmp/x"), topology)
