"""Real Linux/SSH checks using disposable veth cables, never the runner's NICs."""

import os
import platform
import socket
import tempfile
import unittest
import uuid
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path

from src.artifacts import atomic_json, parse_json, read_json
from src.bundle_validation import validate_bundle
from src.physical_campaign import _check_treatment, _retrieve, preflight, trial_command
from src.physical_profile import validate_profile
from src.processes import run_command
from src.run_bundle import source_identity
from src.services import Service
from src.topology_runtime import namespace_identity
from src.trial import ROOT, TrialConfig, run_trial

ENABLED = (
    platform.system() == "Linux"
    and os.geteuid() == 0
    and os.environ.get("NETWORKS_PHYSICAL_STANDIN") == "1"
)


@unittest.skipUnless(ENABLED, "requires an explicitly authorized disposable Linux SSH testbed")
class PhysicalStandinTests(unittest.TestCase):
    def test_udp_tcp_ssh_retrieval_and_interface_restoration_for_every_policy(self):
        # All roles share one kernel in this check. It establishes implementation
        # behavior, not physical cable, NIC, USB adapter, or clock equivalence.
        with tempfile.TemporaryDirectory(prefix="networks-ssh-") as temporary, ExitStack() as stack:
            directory = Path(temporary)
            profile = self.prepare(directory, stack)
            before = self.interfaces(profile)
            identities = preflight(profile)
            self.assertEqual(
                identities["client"]["tree_sha256"], source_identity(ROOT)["tree_sha256"]
            )
            rows = []
            for transport in ("udp", "tcp"):
                for policy in ("fifo", "fq_codel", "cake_best_effort", "cake_bounded"):
                    token = uuid.uuid4().hex[:12]
                    config = TrialConfig(
                        mode="physical",
                        policy=policy,
                        measurement_seconds=2,
                        warmup_seconds=0,
                        aggregate_bps=110_000_000,
                        transport=transport,
                        shadow_forecast=transport == "tcp",
                    )
                    request = {"profile": profile, "token": token, "configuration": asdict(config)}
                    run_command(trial_command(profile, "run", request), timeout=60)
                    destination = directory / token
                    destination.mkdir(mode=0o700)
                    _retrieve(destination, profile, token)
                    _check_treatment(destination, identities["client"], config)
                    self.assertTrue(validate_bundle(destination)["integrity_valid"])
                    foreground = read_json(destination / "foreground.json")
                    self.assertGreater(foreground["counts"]["measurement"]["on_time"], 0)
                    if transport == "tcp":
                        observer = read_json(destination / "tcp-observer.json")
                        self.assertGreater(observer["observed_packets"], 0)
                        self.assertGreater(observer["observed_flows"], 0)
                        self.assertIn(
                            "total_retransmissions",
                            read_json(destination / "foreground-transport.json")["after"],
                        )
                    for role in ("client", "router", "server"):
                        journal = ROOT / ".local" / f"physical-{token}-{role}" / "lease.json"
                        self.assertEqual(read_json(journal)["owned"], {})
                        self.assertIsNone(namespace_identity(f"np-{token}-{role}"))
                    self.assertEqual(self.interfaces(profile), before)
                    rows.append({"policy": policy, "transport": transport, "state": "passed"})
            # Exercise the namespace backend with the new TCP observer as well.
            namespace = directory / "namespace-tcp"
            run_trial(
                namespace,
                TrialConfig(
                    mode="namespace",
                    policy="cake_bounded",
                    transport="tcp",
                    flows=0,
                    aggregate_bps=0,
                    measurement_seconds=2,
                ),
            )
            self.assertTrue(validate_bundle(namespace)["integrity_valid"])
            evidence = ROOT / ".local/physical-standin-evidence"
            evidence.mkdir(exist_ok=True)
            atomic_json(
                evidence / "report.json",
                {
                    "environment": "disposable_Linux_veth_and_loopback_SSH",
                    "physical_hardware_validated": False,
                    "source": source_identity(ROOT),
                    "checks": rows,
                    "namespace_tcp": "passed",
                    "interfaces_restored": True,
                },
            )

    def prepare(self, directory, stack):
        prefix = "t" + uuid.uuid4().hex[:7]
        names = [f"{prefix}{suffix}" for suffix in ("c", "r0", "r1", "s")]
        for left, right in ((names[0], names[1]), (names[2], names[3])):
            run_command(("ip", "link", "add", left, "type", "veth", "peer", "name", right))
            stack.callback(run_command, ("ip", "link", "del", left))
        for name in ("host", "client"):
            run_command(
                ("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(directory / name))
            )
        authorization = directory / "authorized_keys"
        authorization.write_bytes((directory / "client.pub").read_bytes())
        authorization.chmod(0o600)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        (Path("/run/sshd")).mkdir(exist_ok=True)
        sshd = directory / "sshd_config"
        sshd.write_text(
            f"Port {port}\nListenAddress 127.0.0.1\nHostKey {directory / 'host'}\n"
            f"AuthorizedKeysFile {authorization}\nPidFile {directory / 'sshd.pid'}\n"
            "PasswordAuthentication no\nKbdInteractiveAuthentication no\n"
            "PermitRootLogin prohibit-password\nUsePAM no\nStrictModes yes\n"
            "AllowUsers root\nLogLevel VERBOSE\n"
        )
        host = (directory / "host.pub").read_text().split()
        known = directory / "known_hosts"
        known.write_text(f"[127.0.0.1]:{port} {host[0]} {host[1]}\n")
        config = directory / "ssh_config"
        config.write_text(
            "Host test-client test-router test-server\n  HostName 127.0.0.1\n"
            f"  Port {port}\n  User root\n  IdentityFile {directory / 'client'}\n"
            f"  IdentitiesOnly yes\n  UserKnownHostsFile {known}\n  StrictHostKeyChecking yes\n"
        )
        stack.enter_context(
            Service(
                ("/usr/sbin/sshd", "-D", "-e", "-f", str(sshd)), b"Server listening", timeout=300
            )
        )
        roles = {
            "client": {"eth0": names[0]},
            "router": {"to-client": names[1], "to-server": names[2]},
            "server": {"eth0": names[3]},
        }
        return validate_profile(
            {
                "schema_version": 1,
                "roles": {
                    role: {
                        "host": f"test-{role}",
                        "repository": str(ROOT),
                        "interfaces": interfaces,
                        "ssh_config": str(config),
                    }
                    for role, interfaces in roles.items()
                },
            }
        )

    @staticmethod
    def interfaces(profile):
        return {
            name: parse_json(run_command(("ip", "-j", "address", "show", "dev", name)).stdout)[0]
            for item in profile["roles"].values()
            for name in item["interfaces"].values()
        }
