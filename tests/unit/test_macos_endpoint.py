import copy
import fcntl
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from src import macos_endpoint as mac
from src.artifacts import atomic_json, read_json
from src.physical_backend import PhysicalBackend
from src.physical_profile import profile_mode, validate_profile, worker_command
from src.pipeline import plan
from src.processes import CommandResult
from tests.unit.physical_support import profile

LINK = (
    "en7: flags=8863<UP,BROADCAST,RUNNING> mtu 1500\n"
    "\tether 02:00:00:00:00:01\n\tinet 10.203.0.2 netmask 0xfffffffc\n\tstatus: active\n"
)
HARDWARE = (
    "Hardware Port: USB 10/100/1000 LAN Ethernet\nDevice: en7\n"
    "Ethernet Address: 02:00:00:00:00:01\n"
)


def mac_profile(root):
    value = profile(root)
    value["roles"]["router"]["host"] = "lab-router"
    for role in ("client", "server"):
        value["roles"][role].update(
            host=f"lab-{role}",
            platform="macos",
            iperf3="/opt/homebrew/bin/iperf3",
            interfaces={"eth0": "en7"},
        )
    return value


class MacEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = mac_profile(self.root)
        self.item = self.profile["roles"]["client"]
        self.request = {"item": self.item, "role": "client", "token": "a" * 12}

    def test_platform_selection_is_explicit_and_ssh_does_not_request_root_on_macs(self):
        self.assertEqual(validate_profile(self.profile), self.profile)
        self.assertEqual(profile_mode(self.profile), "macos")
        resolved = plan("macos", profile=self.profile)
        self.assertEqual(resolved["kind"], "macos_testbed_diagnostics")
        self.assertEqual(len(resolved["schedule"]["cells"]), 16)
        command = worker_command(self.profile, "client", "inspect", "a" * 12)
        self.assertIn("macos_host.py", command[-1])
        self.assertNotIn("sudo", command[-1])
        with self.assertRaises(ValueError):
            plan("physical", profile=self.profile)
        for role, change in (
            ("client", {"platform": "windows"}),
            ("router", {"platform": "macos"}),
            ("client", {"iperf3": "relative"}),
            ("client", {"iperf3": None}),
            ("client", {"iperf3": "/" + "a" * 512}),
        ):
            altered = copy.deepcopy(self.profile)
            altered["roles"][role].update(change)
            with self.assertRaises(ValueError):
                validate_profile(altered)
        self.profile["roles"]["server"]["platform"] = "linux"
        with self.assertRaises(ValueError):
            profile_mode(self.profile)

    def test_link_checks_reject_wifi_wrong_mask_extra_addresses_and_disconnected_cables(self):
        self.assertEqual(mac.check_link(LINK, HARDWARE, "en7", "10.203.0.2"), "02:00:00:00:00:01")
        self.assertEqual(
            mac.check_link(
                LINK.replace("status: active", "status: inactive"),
                HARDWARE,
                "en7",
                "10.203.0.2",
                require_active=False,
            ),
            "02:00:00:00:00:01",
        )
        for link, hardware in (
            (LINK, HARDWARE.replace("USB 10/100/1000 LAN Ethernet", "Wi-Fi")),
            (LINK, ""),
            (LINK.replace("UP,", ""), HARDWARE),
            (LINK.replace("1500", "9000"), HARDWARE),
            ("", HARDWARE),
            (LINK.replace("fffffffc", "ffffff00"), HARDWARE),
            (LINK + "\tinet 192.168.1.2 netmask 0xffffff00\n", HARDWARE),
            (LINK.replace("ether ", "missing "), HARDWARE),
            (LINK.replace("status: active", "status: inactive"), HARDWARE),
        ):
            with self.subTest(link=link, hardware=hardware), self.assertRaises(PermissionError):
                mac.check_link(link, hardware, "en7", "10.203.0.2")

    def test_inspection_requires_separate_management_and_exact_peer_route(self):
        def command(args, **kwargs):
            if args[0] == "/sbin/route":
                text = (
                    "interface: en0\n"
                    if args[-1] == "default"
                    else "interface: en7\ngateway: 10.203.0.1\n"
                )
            elif args[0] == "/sbin/ifconfig":
                text = LINK
            elif args[0] == "/usr/sbin/networksetup":
                text = HARDWARE
            else:
                text = "iperf 3.22\n"
            return CommandResult(0, text.encode(), b"")

        with (
            patch.object(mac.platform, "system", return_value="Darwin"),
            patch.object(mac, "run_command", side_effect=command),
            patch.object(mac.socket, "if_nametoindex", return_value=7),
        ):
            result = mac.inspect(self.item, "client")
            self.assertEqual(result["address"], "10.203.0.2")
            self.assertFalse(result["network_changes"])
            for values in (
                ({}, {}),
                ({"interface": "en7"}, {}),
                ({"interface": "en0"}, {"interface": "en7", "gateway": "wrong"}),
            ):
                with (
                    patch.object(mac, "route_fields", side_effect=values),
                    self.assertRaises(PermissionError),
                ):
                    mac.inspect(self.item, "client")
            with (
                patch.object(mac, "check_link", return_value="mac"),
                patch.object(
                    mac,
                    "route_fields",
                    side_effect=[
                        {"interface": "en0"},
                        {"interface": "en7", "gateway": "10.203.0.5"},
                    ],
                ),
            ):
                self.assertEqual(mac.inspect(self.item, "server")["address"], "10.203.0.6")
        with (
            patch.object(mac.platform, "system", return_value="Linux"),
            self.assertRaises(PermissionError),
        ):
            mac.inspect(self.item, "client")

    def test_lease_exclusivity_exec_identity_and_idempotent_cleanup(self):
        evidence = {"interfaces": [{"ifindex": 7}], "network_changes": False}
        with patch.object(mac, "inspect", return_value=evidence):
            self.assertEqual(mac.act("inspect", self.request, Event()), evidence)
            state = mac.act("prepare", self.request, Event())
            with self.assertRaises(FileExistsError):
                mac.prepare(self.item, "client", "b" * 12)
            request = {**self.request, "args": [self.item["iperf3"], "--version"]}
            with patch.object(mac, "run_command", return_value=CommandResult(7, b"", b"")):
                self.assertEqual(mac.act("exec", request, Event()), 7)
            with patch.object(mac, "inspect", return_value={}), self.assertRaises(PermissionError):
                mac.act("exec", request, Event())
            with self.assertRaises(ValueError):
                mac.act("unexpected", self.request, Event())
            self.assertEqual(mac.act("cleanup", self.request, Event())["phase"], "closed")
            self.assertEqual(mac.act("cleanup", self.request, Event())["phase"], "closed")
            with self.assertRaises(PermissionError):
                mac.act("exec", request, Event())
            directory = mac.role_path(self.item, "a" * 12, "client")
            state["token"] = "b" * 12
            atomic_json(directory / "lease.json", state)
            with self.assertRaises(PermissionError):
                mac.act("cleanup", self.request, Event())

    def test_replaced_active_owner_and_unsafe_journals_are_retained(self):
        with patch.object(mac, "inspect", return_value={}):
            mac.prepare(self.item, "client", "a" * 12)
        active = self.root / ".local/macos-client-active.json"
        atomic_json(active, {"token": "b" * 12})
        with self.assertRaises(PermissionError):
            mac.act("cleanup", self.request, Event())
        self.assertEqual(read_json(active), {"token": "b" * 12})
        directory = mac.role_path(self.item, "a" * 12, "client")
        directory.chmod(0o755)
        with self.assertRaises(PermissionError):
            mac.act("cleanup", self.request, Event())

    def test_commands_are_bounded_and_cleanup_wait_has_a_deadline(self):
        args = [
            str(self.root / ".venv/bin/python"),
            str(self.root / "scripts/foreground.py"),
            "client",
        ]
        self.assertEqual(mac.workload(self.item, args), tuple(args))
        for value in (None, [1], ["\0"], [], ["x"] * 65, ["x" * 8193]):
            with self.assertRaises(ValueError):
                mac.workload(self.item, value)
        with self.assertRaises(PermissionError):
            mac.workload(self.item, ["/bin/rm"])
        with (
            patch.object(fcntl, "flock", side_effect=BlockingIOError),
            patch.object(mac.time, "monotonic", side_effect=[0, 6]),
            self.assertRaises(TimeoutError),
        ):
            with mac.lock(self.root / "lock"):
                self.fail("busy lease acquired")
        with (
            patch.object(fcntl, "flock", side_effect=[BlockingIOError, None]),
            patch.object(mac.time, "sleep"),
        ):
            with mac.lock(self.root / "lock", shared=True):
                pass

    def test_backend_keeps_router_queue_commands_off_the_macs(self):
        from src.artifacts import json_bytes

        calls = []

        def command(args, **kwargs):
            calls.append(args)
            text = " ".join(args)
            if '"args"' in text:
                result = [{"dev": "to-client", "kind": "cake", "handle": "1:"}]
            else:
                result = {"network_host": str(len(calls)), "interfaces": [{"ifindex": 7}]}
            return CommandResult(0, json_bytes(result), b"")

        with patch("src.physical_backend.run_command", side_effect=command):
            backend = PhysicalBackend(self.profile, "a" * 12, "cake_bounded")
            backend.setup()
            self.assertEqual(backend.snapshot()["kind"], "macos_testbed")
            self.assertIn(
                "/opt/homebrew/bin/iperf3", backend.command("client", ("iperf3", "--version"))[-1]
            )
            self.assertTrue(any("20ms" in str(c) for c in calls))
            self.assertFalse(any("macos_host.py" in str(c) and '"args"' in str(c) for c in calls))
            backend.close()
