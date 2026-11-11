"""Real-socket regressions for the standalone C++ prototype."""

import argparse
import socket
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.cpp_network_testing.probe import run  # noqa: E402
from src.processes import CommandError, run_command  # noqa: E402
from src.services import Service  # noqa: E402

BUILD = None


class ProbeTests(unittest.TestCase):
    def test_two_trials_and_exclusive_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "observed"
            values = run(BUILD, destination, 2)
            self.assertEqual(len(values), 2)
            self.assertTrue(all(value >= 0 for value in values))
            with self.assertRaises(FileExistsError):
                run(BUILD, destination, 1)
            with self.assertRaises(ValueError):
                run(BUILD, Path(temporary) / "invalid", 101)

    def test_invalid_request_fails_and_stops_the_owned_server(self):
        with self.assertRaises(CommandError):
            with Service((str(BUILD / "server"),), b"Server waiting", timeout=5) as service:
                with socket.create_connection(("127.0.0.1", 5000), timeout=2) as peer:
                    peer.sendall(b"FAIL")
                self.assertNotEqual(service.result.result(timeout=3).returncode, 0)

    def test_refused_connection_and_occupied_listener(self):
        with socket.socket() as reservation:
            reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            reservation.bind(("127.0.0.1", 5000))
            with self.assertRaises(CommandError):
                run_command((str(BUILD / "client"),), timeout=5)
            reservation.listen(1)
            with self.assertRaises(CommandError):
                with Service((str(BUILD / "server"),), b"Server waiting", timeout=5):
                    self.fail("occupied port was accepted")

    def test_invalid_ack_fails(self):
        with self.assertRaises(CommandError):
            with Service((str(BUILD / "server"),), b"Server waiting", timeout=5) as service:
                with socket.create_connection(("127.0.0.1", 5000), timeout=2) as peer:
                    peer.sendall(b"PING")
                    self.assertEqual(peer.recv(4), b"PONG")
                    peer.sendall(b"BAD")
                self.assertNotEqual(service.result.result(timeout=3).returncode, 0)

    def test_fragmented_reply_and_wrong_server_token(self):
        for response in (b"PONG", b"FAIL"):
            code = (
                "import socket,time; s=socket.socket(); "
                "s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); "
                "s.bind(('127.0.0.1',5000)); s.listen(1); print('READY',flush=True); "
                "c,_=s.accept(); c.settimeout(2); c.recv(4); "
                f"c.sendall({response[:2]!r}); time.sleep(.02); c.sendall({response[2:]!r}); "
                "c.recv(3); c.close(); s.close()"
            )
            with Service((sys.executable, "-c", code), b"READY", timeout=5) as service:
                if response == b"PONG":
                    self.assertEqual(run_command((str(BUILD / "client"),), timeout=5).returncode, 0)
                else:
                    with self.assertRaises(CommandError):
                        run_command((str(BUILD / "client"),), timeout=5)
                self.assertEqual(service.result.result(timeout=3).returncode, 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    BUILD = args.build_dir.resolve()
    unittest.main(argv=[sys.argv[0], *remaining])
