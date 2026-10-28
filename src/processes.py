"""Shell-free child processes with bounded output, deadlines, and cleanup."""

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event

from src.experiment_config import bounded_integer, bounded_number


class CommandError(RuntimeError):
    """A command failed, timed out, or exceeded its output budget."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def terminate(child: subprocess.Popen) -> None:
    """Reap only this child's session; also stop descendants holding pipe handles."""
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait(timeout=1)


def _collect(
    child: subprocess.Popen,
    timeout: float,
    limit: int,
    observe: Callable | None,
    stop: Event | None,
) -> CommandResult:
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout
    size = 0
    interrupted = False
    with selectors.DefaultSelector() as poll:
        for name in outputs:
            stream = getattr(child, name)
            os.set_blocking(stream.fileno(), False)
            poll.register(stream, selectors.EVENT_READ, name)
        while poll.get_map() or child.poll() is None:
            if stop is not None and stop.is_set() and not interrupted:
                _request_stop(child)
                deadline = min(deadline, time.monotonic() + 1)
                interrupted = True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CommandError("command exceeded its deadline")
            for key, _ in poll.select(min(remaining, 0.05)):
                data = os.read(key.fd, min(65536, limit - size + 1))
                if not data:
                    poll.unregister(key.fileobj)
                    continue
                size += len(data)
                if size > limit:
                    raise CommandError("command exceeded its output budget")
                outputs[key.data].extend(data)
                if observe is not None:
                    observe(key.data, data)
    try:
        status = child.wait(timeout=max(0.001, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as exc:
        raise CommandError("command exceeded its deadline") from exc
    return CommandResult(status, bytes(outputs["stdout"]), bytes(outputs["stderr"]))


def _request_stop(child: subprocess.Popen) -> None:
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def run_command(
    args: tuple[str, ...] | list[str],
    *,
    timeout: float = 10,
    limit: int = 1024 * 1024,
    check: bool = True,
    observe: Callable | None = None,
    stop: Event | None = None,
) -> CommandResult:
    """O(output bytes) time and space, capped at limit across both output streams."""
    bounded_number(timeout, "command timeout", 0.001, 300)
    bounded_integer(limit, "output limit", 1, 32 * 1024 * 1024)
    if not args or any(not isinstance(arg, str) or "\0" in arg for arg in args):
        raise ValueError("command requires nonempty, NUL-free string arguments")
    try:
        child = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise CommandError(f"could not start {args[0]}: {exc.strerror}") from exc
    primary_error = None
    try:
        result = _collect(child, timeout, limit, observe, stop)
        if check and result.returncode:
            raise CommandError(f"{args[0]} exited with status {result.returncode}")
        return result
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            terminate(child)
        except (OSError, subprocess.TimeoutExpired) as cleanup:
            if primary_error is None:
                raise CommandError(f"could not reap {args[0]}") from cleanup
            primary_error.add_note(f"child cleanup also failed: {cleanup}")
        finally:
            child.stdout.close()
            child.stderr.close()
