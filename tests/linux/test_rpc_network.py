"""Network-namespace tests for the Birrell--Nelson-inspired RPC transport.

These tests require Linux network namespaces and root privileges. They use a
private veth pair and, when available, netem to inject delay and packet loss.
The namespaces and interfaces are removed after the test suite finishes.
"""

import json
import os
import select
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from threading import Event
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLIENT_ADDRESS = "10.217.53.1"
SERVER_ADDRESS = "10.217.53.2"
SERVER_PORT = 53021
CLIENT_MAC = "02:71:30:00:53:01"
SERVER_MAC = "02:71:30:00:53:02"
PAYLOAD = b"namespace rpc"
READY_TIMEOUT_SECONDS = 5
WORKER_TIMEOUT_SECONDS = 8


def _worker_server() -> None:
    """Run the real RPC server inside its network namespace."""
    from src.basic_rpc_protocol.rpc_connector import run_server
    from src.basic_rpc_protocol.rpc_server import RpcServer

    stop = Event()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
    server = RpcServer(lambda data: data.upper())
    result = run_server(
        server,
        (SERVER_ADDRESS, SERVER_PORT),
        CLIENT_ADDRESS,
        allow_isolated=True,
        duration_ms=15_000,
        stop=stop,
        ready=lambda _address: print("READY", flush=True),
    )
    print(json.dumps(result), flush=True)


def _worker_client(timeout_ms: int, max_retries: int) -> None:
    """Run one real RPC call and print its result and retry counters."""
    from src.basic_rpc_protocol.rpc_client import RpcClient, RpcTimeout
    from src.basic_rpc_protocol.rpc_connector import run_client

    client = RpcClient(
        machine_id=123,
        activity_id=1,
        timeout_ns=timeout_ms * 1_000_000,
        max_retries=max_retries,
    )
    print("READY", flush=True)
    started_ns = time.monotonic_ns()
    try:
        reply = run_client(
            client,
            PAYLOAD,
            (CLIENT_ADDRESS, 0),
            (SERVER_ADDRESS, SERVER_PORT),
            allow_isolated=True,
            total_timeout_ms=5000,
        )
        outcome = "completed"
        payload = reply.decode("ascii")
    except RpcTimeout:
        outcome = "timeout"
        payload = None

    result = {
        "outcome": outcome,
        "payload": payload,
        "elapsed_ms": (time.monotonic_ns() - started_ns) / 1_000_000,
        "client_counts": client.statistics(),
    }
    print(json.dumps(result), flush=True)


class RpcNetworkTests(unittest.TestCase):
    """Exercise RPC across isolated namespaces under controlled impairment."""

    @classmethod
    def _command(cls, *arguments: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a bounded system command and include stderr on failure."""
        result = subprocess.run(
            arguments,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"Command failed: {' '.join(arguments)}\n{result.stderr.strip()}")
        return result

    @classmethod
    def setUpClass(cls) -> None:
        """Create two private network namespaces connected by a veth pair."""
        if os.environ.get("NETWORKS_RUN_PRIVILEGED") != "1":
            raise unittest.SkipTest("Enable the isolated Linux check explicitly; see issue #41")
        if sys.platform != "linux":
            raise unittest.SkipTest("Linux network namespaces are required")
        if os.geteuid() != 0:
            raise unittest.SkipTest("Run namespace tests with sudo/root privileges")
        if shutil.which("ip") is None:
            raise unittest.SkipTest("The iproute2 'ip' command is required")

        suffix = uuid4().hex[:6]
        cls.client_ns = f"rpcn{suffix}c"
        cls.server_ns = f"rpcn{suffix}s"
        cls.client_dev = f"rpcv{suffix}c"
        cls.server_dev = f"rpcv{suffix}s"
        cls.created_namespaces: list[str] = []

        try:
            for namespace in (cls.client_ns, cls.server_ns):
                cls._command("ip", "netns", "add", namespace)
                cls.created_namespaces.append(namespace)

            cls._command(
                "ip",
                "link",
                "add",
                cls.client_dev,
                "type",
                "veth",
                "peer",
                "name",
                cls.server_dev,
            )
            cls._command("ip", "link", "set", cls.client_dev, "netns", cls.client_ns)
            cls._command("ip", "link", "set", cls.server_dev, "netns", cls.server_ns)
            for namespace, device, address, mac, peer, peer_mac in (
                (
                    cls.client_ns,
                    cls.client_dev,
                    CLIENT_ADDRESS,
                    CLIENT_MAC,
                    SERVER_ADDRESS,
                    SERVER_MAC,
                ),
                (
                    cls.server_ns,
                    cls.server_dev,
                    SERVER_ADDRESS,
                    SERVER_MAC,
                    CLIENT_ADDRESS,
                    CLIENT_MAC,
                ),
            ):
                cls._command("ip", "-n", namespace, "link", "set", device, "address", mac)
                cls._command(
                    "ip", "-n", namespace, "address", "add", f"{address}/30", "dev", device
                )
                cls._command("ip", "-n", namespace, "link", "set", "lo", "up")
                cls._command("ip", "-n", namespace, "link", "set", device, "up")
                # Static neighbors keep 100% loss tests from dropping ARP
                # instead of the RPC request and response datagrams.
                cls._command(
                    "ip",
                    "-n",
                    namespace,
                    "neigh",
                    "replace",
                    peer,
                    "lladdr",
                    peer_mac,
                    "nud",
                    "permanent",
                    "dev",
                    device,
                )
        except Exception as exc:
            cls._cleanup_namespaces()
            if any(
                term in str(exc).lower()
                for term in (
                    "operation not permitted",
                    "permission denied",
                    "mount --make-shared",
                )
            ):
                raise unittest.SkipTest(f"Network namespaces unavailable: {exc}") from exc
            raise

    @classmethod
    def _cleanup_namespaces(cls) -> None:
        """Remove private interfaces and namespaces, including partial setup."""
        for namespace in reversed(getattr(cls, "created_namespaces", [])):
            cls._command("ip", "netns", "delete", namespace, check=False)
        for device in (getattr(cls, "client_dev", ""), getattr(cls, "server_dev", "")):
            if device:
                cls._command("ip", "link", "delete", device, check=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._cleanup_namespaces()

    def tearDown(self) -> None:
        """Clear netem on both endpoints between test cases."""
        for namespace, device in (
            (self.client_ns, self.client_dev),
            (self.server_ns, self.server_dev),
        ):
            if shutil.which("tc"):
                self._command(
                    "ip",
                    "netns",
                    "exec",
                    namespace,
                    "tc",
                    "qdisc",
                    "del",
                    "dev",
                    device,
                    "root",
                    check=False,
                )

    def _netem(self, side: str, *options: str) -> None:
        """Apply netem to one egress interface, skipping unsupported kernels."""
        if shutil.which("tc") is None:
            self.skipTest("The iproute2 'tc' command is unavailable")
        namespace, device = (
            (self.client_ns, self.client_dev)
            if side == "client"
            else (self.server_ns, self.server_dev)
        )
        result = self._command(
            "ip",
            "netns",
            "exec",
            namespace,
            "tc",
            "qdisc",
            "replace",
            "dev",
            device,
            "root",
            "netem",
            *options,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.strip()
            if any(
                term in message.lower()
                for term in (
                    "specified qdisc kind is unknown",
                    "no such file or directory",
                    "unknown qdisc",
                    "operation not supported",
                )
            ):
                self.skipTest(f"Kernel netem support unavailable: {message}")
            self.fail(f"Could not configure netem: {message}")

    def _clear_netem(self, side: str) -> None:
        """Remove injected impairment while a call remains in flight."""
        namespace, device = (
            (self.client_ns, self.client_dev)
            if side == "client"
            else (self.server_ns, self.server_dev)
        )
        self._command(
            "ip",
            "netns",
            "exec",
            namespace,
            "tc",
            "qdisc",
            "del",
            "dev",
            device,
            "root",
        )

    def _start_worker(self, namespace: str, role: str, *arguments: str) -> subprocess.Popen:
        """Start a worker and wait until its socket or caller is ready."""
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        process = subprocess.Popen(
            [
                "ip",
                "netns",
                "exec",
                namespace,
                sys.executable,
                "-u",
                str(Path(__file__).resolve()),
                role,
                *arguments,
            ],
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        readable, _, _ = select.select([process.stdout], [], [], READY_TIMEOUT_SECONDS)
        if not readable or process.stdout.readline().strip() != "READY":
            output, errors = self._stop_worker(process)
            self.fail(f"RPC worker {role} did not become ready: {output} {errors}")
        return process

    @staticmethod
    def _stop_worker(process: subprocess.Popen) -> tuple[str, str]:
        """Stop a worker and its namespace-exec children without leaking PIDs."""
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            return process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return process.communicate(timeout=3)

    def _exercise(
        self,
        *,
        timeout_ms: int = 120,
        max_retries: int = 5,
        restore_side: str | None = None,
    ) -> tuple[dict, dict]:
        """Run one call and collect counters from both real socket endpoints."""
        server = self._start_worker(self.server_ns, "--server")
        client = None
        try:
            client = self._start_worker(
                self.client_ns,
                "--client",
                str(timeout_ms),
                str(max_retries),
            )
            if restore_side is not None:
                # Keep 100% loss long enough for at least one retry, then
                # restore delivery before the client's retry budget expires.
                time.sleep(0.40)
                self._clear_netem(restore_side)
            client_out, client_err = client.communicate(timeout=WORKER_TIMEOUT_SECONDS)
            self.assertEqual(client.returncode, 0, client_err)
            self.assertTrue(client_out.strip(), "Client produced no result")
            client_result = json.loads(client_out.strip().splitlines()[-1])
            time.sleep(0.08)  # Allow ACK to reach server before shutdown.
        finally:
            if client is not None and client.poll() is None:
                self._stop_worker(client)
            server_out, server_err = self._stop_worker(server)

        self.assertTrue(server_out.strip(), f"Server produced no result: {server_err}")
        server_result = json.loads(server_out.strip().splitlines()[-1])
        self.assertNotEqual(server_result["status"], "io_error", server_result)
        return client_result, server_result

    def test_namespace_round_trip(self) -> None:
        """A real RPC call crosses two isolated Linux namespaces."""
        client, server = self._exercise()
        self.assertEqual(client["outcome"], "completed")
        self.assertEqual(client["payload"], PAYLOAD.decode("ascii").upper())
        self.assertEqual(server["protocol_counts"].get("calls_executed"), 1)

    def test_netem_delay(self) -> None:
        """A delayed round trip still completes without retransmission."""
        self._netem("client", "delay", "20ms")
        self._netem("server", "delay", "20ms")
        client, server = self._exercise(timeout_ms=500)
        self.assertEqual(client["outcome"], "completed")
        self.assertGreaterEqual(client["elapsed_ms"], 30)
        self.assertEqual(client["client_counts"].get("retransmissions", 0), 0)
        self.assertEqual(server["protocol_counts"].get("calls_executed"), 1)

    def test_lost_request(self) -> None:
        """Dropping outgoing CALLs forces a retry before delivery resumes."""
        self._netem("client", "loss", "100%")
        client, server = self._exercise(max_retries=8, restore_side="client")
        self.assertEqual(client["outcome"], "completed")
        self.assertGreaterEqual(client["client_counts"].get("retransmissions", 0), 1)
        self.assertEqual(server["protocol_counts"].get("calls_executed"), 1)

    def test_lost_response(self) -> None:
        """Dropping RESULTs forces a retry, not duplicate execution."""
        self._netem("server", "loss", "100%")
        client, server = self._exercise(max_retries=8, restore_side="server")
        self.assertEqual(client["outcome"], "completed")
        self.assertGreaterEqual(client["client_counts"].get("retransmissions", 0), 1)
        self.assertEqual(server["protocol_counts"].get("calls_executed"), 1)
        self.assertGreaterEqual(server["protocol_counts"].get("duplicate_calls", 0), 1)

    def test_persistent_loss_times_out(self) -> None:
        """A permanent blackhole eventually exhausts the client's retries."""
        self._netem("client", "loss", "100%")
        client, server = self._exercise(timeout_ms=120, max_retries=2)
        self.assertEqual(client["outcome"], "timeout")
        self.assertEqual(client["client_counts"].get("retransmissions"), 2)
        self.assertEqual(client["client_counts"].get("calls_timed_out"), 1)
        self.assertEqual(server["protocol_counts"].get("calls_executed", 0), 0)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        _worker_server()
    elif len(sys.argv) == 4 and sys.argv[1] == "--client":
        _worker_client(int(sys.argv[2]), int(sys.argv[3]))
    else:
        unittest.main()
