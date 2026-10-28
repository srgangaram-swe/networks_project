"""Bounded background services with output-based readiness and joined shutdown."""

from concurrent.futures import Future
from threading import Event, Thread

from src.processes import CommandError, CommandResult, run_command


class Service:
    def __init__(self, args: tuple[str, ...], marker: bytes, *, timeout: float = 180):
        self.args = args
        self.marker = marker
        self.timeout = timeout
        self.stop = Event()
        self.ready = Event()
        self.result: Future[CommandResult] = Future()
        self.thread = Thread(target=self._run, name="experiment-service")
        self.buffers = {"stdout": bytearray(), "stderr": bytearray()}

    def _observe(self, stream: str, data: bytes) -> None:
        # Retain only a marker-sized suffix; the process collector owns the full
        # bounded log. Keeping streams separate avoids matching across streams.
        buffer = self.buffers[stream]
        buffer.extend(data)
        if self.marker in buffer:
            self.ready.set()
        del buffer[: -max(1, len(self.marker))]

    def _run(self) -> None:
        try:
            self.result.set_result(
                run_command(
                    self.args,
                    timeout=self.timeout,
                    limit=1024 * 1024,
                    check=False,
                    observe=self._observe,
                    stop=self.stop,
                )
            )
        except Exception as exc:
            self.result.set_exception(exc)
        finally:
            self.ready.set()

    def __enter__(self) -> "Service":
        self.thread.start()
        try:
            if not self.ready.wait(5):
                raise CommandError("service did not report readiness within five seconds")
            if self.result.done():
                result = self.result.result()
                raise CommandError(f"service exited before use with status {result.returncode}")
        except BaseException as error:
            try:
                self.close()
            except CommandError as cleanup:
                error.add_note(f"service startup cleanup also failed: {cleanup}")
            raise
        return self

    def close(self) -> None:
        already_finished = self.result.done()
        self.stop.set()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise CommandError("service did not stop within the shutdown deadline")
        if already_finished and self.result.result().returncode != 0:
            raise CommandError("service exited unsuccessfully before shutdown")

    def __exit__(self, kind, error, _traceback) -> None:
        try:
            self.close()
            if kind is None:
                self.result.result()
        except CommandError as cleanup:
            if error is None:
                raise
            error.add_note(f"service cleanup also failed: {cleanup}")

    def check_running(self) -> None:
        if self.result.done():
            result = self.result.result()
            raise CommandError(f"service stopped unexpectedly with status {result.returncode}")
