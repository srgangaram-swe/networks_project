"""Small, atomic, nonblocking event writes to an owned local FIFO."""

import json
import os
import stat


class EventWriter:
    def __init__(self, path=None):
        self.descriptor = None
        self.sent = 0
        self.dropped = 0
        if path is not None:
            self.descriptor = os.open(path, os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            metadata = os.fstat(self.descriptor)
            if not stat.S_ISFIFO(metadata.st_mode) or metadata.st_mode & 0o077:
                self.close()
                raise PermissionError("event stream must be a private FIFO")

    def __call__(self, event):
        if self.descriptor is None:
            return
        data = (json.dumps(event, separators=(",", ":"), allow_nan=False) + "\n").encode()
        if len(data) > 512:
            raise ValueError("event exceeds its atomic 512-byte budget")
        try:
            if os.write(self.descriptor, data) != len(data):
                raise OSError("event FIFO write was not atomic")
            self.sent += 1
        except (BlockingIOError, BrokenPipeError):
            # The traffic generator never waits for a slower observer.
            self.dropped += 1

    def close(self):
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
