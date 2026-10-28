import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.artifacts import atomic_json, digest, parse_json, read_bytes, read_json


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_round_trip_digest_and_size(self):
        path = self.root / "value.json"
        atomic_json(path, {"x": [1, 2.5, None]})
        self.assertEqual(read_json(path), {"x": [1, 2.5, None]})
        self.assertEqual(len(digest(path)), 64)
        with self.assertRaises(ValueError):
            read_bytes(path, 1)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_rejects_duplicate_nonfinite_and_invalid_encoding(self):
        for data in (b'{"a":1,"a":2}', b"NaN", b"Infinity", b"1e999", b'"\xff"', b"[" * 2000):
            with self.assertRaises(ValueError):
                parse_json(data)
        self.assertEqual(parse_json(b"1.25"), 1.25)

    def test_symlinks_and_special_files_are_not_read(self):
        target = self.root / "target"
        target.write_text("hello")
        link = self.root / "link"
        link.symlink_to(target)
        with self.assertRaises(OSError):
            read_bytes(link)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            read_bytes(fifo)

    def test_failed_publication_preserves_existing_artifact(self):
        path = self.root / "value.json"
        atomic_json(path, {"value": 1})
        with patch("src.artifacts.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                atomic_json(path, {"value": 2})
        self.assertEqual(json.loads(path.read_text()), {"value": 1})
        self.assertEqual(list(self.root.iterdir()), [path])
        with patch("src.artifacts.MAX_JSON_BYTES", 1):
            with self.assertRaises(ValueError):
                atomic_json(path, {"value": 2})


if __name__ == "__main__":
    unittest.main()
