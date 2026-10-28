import shutil
import socket
import unittest

from src.artifacts import parse_json
from src.bulk import BulkPlan, client_command, server_command, summarize_bulk
from src.processes import run_command
from src.services import Service


@unittest.skipUnless(
    shutil.which("iperf3"), "iperf3 is required for real TCP integration; see issue #8"
)
class BulkIntegrationTests(unittest.TestCase):
    def test_one_and_eight_real_tcp_flows(self):
        for flows in (1, 8):
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            plan = BulkPlan(8_000_000, flows, 1)
            with Service(server_command("127.0.0.1", port), b"Server listening on", timeout=10):
                result = run_command(
                    client_command(plan, "127.0.0.1", "127.0.0.1", port), timeout=8
                )
                summary = summarize_bulk(parse_json(result.stdout), plan)
            self.assertEqual(summary["actual_flows"], flows)
            self.assertGreater(summary["receiver_bytes"], 0)
            self.assertFalse(summary["foreground_window_aligned"])


if __name__ == "__main__":
    unittest.main()
