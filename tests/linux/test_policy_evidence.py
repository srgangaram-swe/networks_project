"""Independent traffic, packet and counter checks for the candidate queue rules."""

import json
import os
import platform
import sys
import tempfile
import unittest
from pathlib import Path

from src.artifacts import atomic_json, parse_json
from src.bulk import server_command
from src.experiment_config import POLICIES
from src.processes import run_command
from src.services import Service
from src.testbed_backend import Backend

ENABLED = (
    platform.system() == "Linux"
    and os.geteuid() == 0
    and os.environ.get("NETWORKS_RUN_PRIVILEGED") == "1"
)
PROBE = str(Path(__file__).with_name("probe_udp.py"))


def record(name: str, value: dict) -> None:
    destination = os.environ.get("NETWORKS_EVIDENCE_DIR")
    if destination:
        path = Path(destination)
        path.mkdir(parents=True, exist_ok=True)
        target = path / f"{name}.json"
        if target.exists():
            raise FileExistsError(target)
        atomic_json(target, value)
    print(f"Evidence {name}: {json.dumps(value, sort_keys=True)}", flush=True)


def probe(backend: Backend, *, port: int, rate: int, tos: int) -> dict:
    receiver = backend.command("client", (sys.executable, PROBE, "receive"))
    capture = backend.command(
        "client",
        (
            "tcpdump",
            "-n",
            "-l",
            "-vv",
            "-s",
            "96",
            "-c",
            "8",
            "-i",
            "eth0",
            "udp",
            "and",
            "dst",
            "port",
            "42001",
        ),
    )
    with (
        Service(receiver, b"ready", timeout=6) as service,
        Service(capture, b"listening on", timeout=6) as packets,
    ):
        sender = run_command(
            backend.command(
                "server",
                (
                    sys.executable,
                    PROBE,
                    "send",
                    "--port",
                    str(port),
                    "--rate",
                    str(rate),
                    "--tos",
                    str(tos),
                ),
            ),
            timeout=4,
        )
        result = service.result.result(timeout=5)
        sample = packets.result.result(timeout=5)
        if result.returncode or sample.returncode:
            raise RuntimeError("packet probe did not complete")
    return {
        "sent": parse_json(sender.stdout),
        "received": parse_json(result.stdout.splitlines()[-1]),
        "packet_sample": sample.stdout.decode("ascii"),
    }


@unittest.skipUnless(ENABLED, "requires an explicitly authorized Linux testbed; issues #6 and #11")
class PolicyEvidenceTests(unittest.TestCase):
    def test_packet_marks_are_rewritten_and_priority_has_a_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            for policy in sorted(POLICIES):
                path = Path(directory) / policy
                path.mkdir()
                backend = Backend("namespace", policy, path)
                try:
                    backend.setup()
                    for port, rate, tos in ((42002, 500, 184), (42000, 500, 0), (42000, 5000, 184)):
                        observed = probe(backend, port=port, rate=rate, tos=tos)
                        record(f"marks-{policy}-{port}-{rate}", observed)
                        received = observed["received"]
                        self.assertGreater(received["received"], rate * 0.9)
                        counts = received["tos_counts"]
                        if policy != "cake_bounded" or port == 42002:
                            self.assertEqual(set(counts), {"0"})
                        elif rate == 500:
                            self.assertEqual(set(counts), {"184"})
                        else:
                            self.assertGreater(counts.get("0", 0), 0)
                            self.assertGreater(counts.get("184", 0), 0)
                            budget = 5_000_000 * observed["sent"]["elapsed_ns"] / 8e9 + 16384 + 554
                            self.assertLessEqual(counts["184"] * 554, budget)
                finally:
                    backend.close()

    def test_effective_udp_capacity_across_policies(self):
        summaries = []
        with tempfile.TemporaryDirectory() as directory:
            for policy in sorted(POLICIES):
                for repetition in range(2):
                    path = Path(directory) / f"{policy}-{repetition}"
                    path.mkdir()
                    backend = Backend("namespace", policy, path)
                    try:
                        backend.setup()
                        server = backend.command(
                            "server",
                            server_command(backend.server_address, 5201, allow_isolated=True),
                        )
                        with Service(server, b"Server listening on", timeout=20):
                            output = run_command(
                                backend.command(
                                    "client",
                                    (
                                        "iperf3",
                                        "-c",
                                        backend.server_address,
                                        "-B",
                                        backend.client_address,
                                        "-u",
                                        "-R",
                                        "-b",
                                        "200M",
                                        "-l",
                                        "1200",
                                        "-t",
                                        "8",
                                        "-O",
                                        "1",
                                        "-J",
                                        "--get-server-output",
                                    ),
                                ),
                                timeout=15,
                            )
                        raw = parse_json(output.stdout)
                        # The reverse-mode client is the receiver. Sender totals
                        # measure offered demand and cannot establish a bottleneck.
                        measured = [
                            row["sum"] for row in raw["intervals"] if row["sum"]["omitted"] is False
                        ]
                        self.assertTrue(measured)
                        self.assertTrue(all(row["sender"] is False for row in measured))
                        byte_count = sum(row["bytes"] for row in measured)
                        seconds = measured[-1]["end"] - measured[0]["start"]
                        rate = 8 * byte_count / seconds / 1e6
                        queues = backend.snapshot()["snapshots"]["router_queues"]
                        root = next(
                            row
                            for row in queues
                            if row.get("dev") == "to-client" and row.get("handle") == "1:"
                        )
                        summary = {
                            "policy": policy,
                            "repetition": repetition + 1,
                            "udp_payload_bytes": 1200,
                            "offered_mbps": 200,
                            "receiver_bytes": byte_count,
                            "receiver_seconds": seconds,
                            "goodput_mbps": rate,
                            "root_counters": root,
                            "iperf_version": raw["start"]["version"],
                        }
                        record(f"capacity-{policy}-{repetition + 1}", summary)
                        summaries.append(summary)
                        self.assertGreater(root["bytes"], byte_count)
                        self.assertGreater(root["drops"], 0)
                        self.assertGreater(rate, 90)
                        self.assertLess(rate, 100)
                    finally:
                        backend.close()
        rates = [row["goodput_mbps"] for row in summaries]
        self.assertLess(
            max(rates) - min(rates),
            3,
            "capacity differs by more than the predeclared 3 Mb/s tolerance",
        )


if __name__ == "__main__":
    unittest.main()
