import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.hardware_probe import (
    MAX_INTERFACES,
    MODULES,
    _attribute,
    _default_links,
    _driver,
    _number,
    _probe,
    inspect_hardware,
    interface_inventory,
    local_hardware,
    tool_versions,
)
from src.processes import CommandError, CommandResult


def success(args, **kwargs):
    banners = {
        "ip": b"ip utility, iproute2-6.1.0\nprivate-build-path",
        "tc": b"tc utility, iproute2-6.1.0",
        "iperf3": b"iperf 3.22 (private machine identity)",
        "tcpdump": b"tcpdump version 4.99.5",
        "ethtool": b"ethtool version 6.1",
        "modinfo": b"filename: /private/kernel/module.ko",
    }
    if "route" in args:
        return CommandResult(0, b'[{"dev":"enp1s0","gateway":"192.168.1.1"}]', b"")
    return CommandResult(0, banners[args[0]], b"")


class HardwareProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.nic = self.root / "enp1s0"
        (self.nic / "device/driver/igc").mkdir(parents=True)
        for field, value in {"carrier": "1", "speed": "2500", "mtu": "1500"}.items():
            (self.nic / field).write_text(value)

    def test_read_only_report_omits_addresses_and_command_banners(self):
        with patch("src.hardware_probe._driver", return_value="igc"):
            report = inspect_hardware("Linux", net_root=self.root, find=lambda n: n, run=success)
        row = report["interfaces"][0]
        self.assertEqual((row["speed_mbps"], row["mtu"], row["driver"]), (2500, 1500, "igc"))
        self.assertTrue(row["default_route"])
        self.assertFalse(row["authorized_for_changes"])
        self.assertFalse(report["ready_for_experiment"])
        self.assertFalse(report["network_changes"])
        self.assertEqual(len(report["modules"]), len(MODULES))
        encoded = json.dumps(report)
        for private in ("192.168", "private-build", "private machine", "/private", "gateway"):
            self.assertNotIn(private, encoded)

    def test_non_linux_does_not_read_sysfs_or_launch_anything(self):
        find, run = Mock(), Mock()
        report = inspect_hardware("Darwin", net_root=Path("missing"), find=find, run=run)
        self.assertEqual(report["status"], "unsupported_platform")
        find.assert_not_called()
        run.assert_not_called()
        with patch("src.hardware_probe.platform.system", return_value="Darwin"):
            self.assertEqual(local_hardware()["platform"], "Darwin")

    def test_missing_failed_and_timed_out_probes_are_distinct(self):
        run = Mock()
        self.assertEqual(_probe(("ip", "-V"), lambda _: None, run), ("missing", b""))
        run.assert_not_called()
        for result, expected in (
            (CommandResult(1, b"private", b""), "command_failed"),
            (CommandError("deadline"), "probe_failed"),
            (OSError("permission"), "probe_failed"),
        ):
            runner = (
                Mock(side_effect=result)
                if isinstance(result, Exception)
                else Mock(return_value=result)
            )
            self.assertEqual(_probe(("ip", "-V"), lambda n: n, runner)[0], expected)
            self.assertEqual(
                runner.call_args.kwargs, {"timeout": 3, "limit": 16384, "check": False}
            )

    def test_versions_only_keep_the_version_token(self):
        versions = tool_versions(lambda n: n, success)
        self.assertEqual(
            [v["version"] for v in versions], ["6.1.0", "6.1.0", "3.22", "4.99.5", "6.1"]
        )
        versions = tool_versions(
            lambda n: n, lambda *a, **kw: CommandResult(0, b"unrecognized", b"")
        )
        self.assertTrue(all(v["version"] is None for v in versions))

    def test_bad_or_unavailable_routes_never_imply_unprotected(self):
        for data in (b"{}", b"not json", b"[null]", b"[{}]", json.dumps([{}] * 65).encode()):
            run = Mock(return_value=CommandResult(0, data, b""))
            self.assertEqual(_default_links(lambda n: n, run), (set(), False))
        self.assertEqual(_default_links(lambda _: None, Mock()), (set(), False))
        self.assertIsNone(interface_inventory(self.root, set(), False)[0]["default_route"])

    def test_sysfs_attribute_limits_and_unknown_values(self):
        path = self.nic / "speed"
        for data in (b"-1", b"x", b"0", b"1000001", b"9" * 257, b"\xff"):
            path.write_bytes(data)
            self.assertIsNone(_number(path, 1, 1_000_000))
        path.unlink()
        self.assertIsNone(_attribute(path))
        self.assertIsNone(_driver(path))
        self.assertEqual(_driver(self.nic / "device/driver/igc"), "igc")
        strange = self.nic / "bad driver"
        strange.mkdir()
        self.assertIsNone(_driver(strange))

    def test_virtual_links_names_and_counts_are_bounded(self):
        (self.root / "lo").mkdir()
        self.assertEqual(len(interface_inventory(self.root, set(), True)), 1)
        bad = self.root / "bad name"
        bad.mkdir()
        with self.assertRaisesRegex(ValueError, "name"):
            interface_inventory(self.root, set(), True)
        bad.rmdir()
        for i in range(MAX_INTERFACES):
            (self.root / f"veth{i}").mkdir()
        with self.assertRaisesRegex(ValueError, "limit"):
            interface_inventory(self.root, set(), True)
