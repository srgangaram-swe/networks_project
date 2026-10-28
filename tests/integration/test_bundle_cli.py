import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.artifacts import atomic_json, digest, read_json

ROOT = Path(__file__).resolve().parents[2]


class BundleCliTests(unittest.TestCase):
    def call(self, *args):
        return subprocess.run(
            [sys.executable, *args], cwd=ROOT, capture_output=True, text=True, timeout=10
        )

    def test_complete_labeled_examples_and_semantic_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            examples = Path(temporary) / "examples"
            generated = self.call("-m", "tests.fixtures", "--output", str(examples))
            self.assertEqual(generated.returncode, 0, generated.stderr)
            valid = examples / "valid-synthetic"
            invalid = examples / "invalid-duplicate"
            self.assertEqual(
                read_json(valid / "environment.json")["measurement_kind"], "synthetic_fixture"
            )
            result = self.call("scripts/validate_bundle.py", str(valid))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)["eligible_for_primary"])
            result = self.call("scripts/validate_bundle.py", str(invalid))
            self.assertEqual(result.returncode, 2)
            self.assertIn("request IDs", result.stderr)
            result = self.call(
                "scripts/export_diagnostics.py", str(valid), "--output", str(examples / "export")
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("synthetic fixtures", result.stderr)
            self.assertEqual(
                self.call("-m", "tests.fixtures", "--output", str(examples)).returncode, 2
            )

    def test_partial_and_truncated_bundles_are_rejected_without_changing_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            examples = Path(temporary) / "examples"
            self.assertEqual(
                self.call("-m", "tests.fixtures", "--output", str(examples)).returncode, 0
            )
            valid = examples / "valid-synthetic"
            path = valid / "manifest.json"
            original = path.read_bytes()
            for content in (b'{"schema_version":', b""):
                path.write_bytes(content)
                self.assertEqual(self.call("scripts/validate_bundle.py", str(valid)).returncode, 2)
                self.assertEqual(path.read_bytes(), content)
            path.write_bytes(original)
            manifest = read_json(path)
            manifest["state"] = "measurement"
            atomic_json(path, manifest)
            checksum = digest(path)
            result = self.call("scripts/validate_bundle.py", str(valid))
            self.assertEqual(result.returncode, 2)
            self.assertIn("incomplete", result.stderr)
            self.assertEqual(digest(path), checksum)


if __name__ == "__main__":
    unittest.main()
