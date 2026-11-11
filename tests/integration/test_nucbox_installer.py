import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/setup_nucbox.sh"


class NucboxInstallerTests(unittest.TestCase):
    def test_portable_plan_does_not_change_the_callers_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                ["sh", str(SCRIPT), "--plan"],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Ubuntu 24.04 LTS", result.stdout)
            self.assertIn("does not install", result.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_invalid_actions_fail_before_installing_anything(self):
        for args in ([], ["--invalid"], ["--install", "--plan"]):
            with self.subTest(args=args):
                result = subprocess.run(
                    ["sh", str(SCRIPT), *args], capture_output=True, text=True, timeout=5
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")

    def test_non_linux_host_cannot_install(self):
        # A sentinel sudo prevents privileged work even if the platform guard
        # regresses. Platform rejection must happen before that sentinel runs.
        with tempfile.TemporaryDirectory() as directory:
            uname = Path(directory) / "uname"
            uname.write_text("#!/bin/sh\nprintf '%s\\n' Darwin\n")
            uname.chmod(0o700)
            sudo = Path(directory) / "sudo"
            sudo.write_text("#!/bin/sh\nprintf '%s\\n' unexpected_sudo >&2\nexit 99\n")
            sudo.chmod(0o700)

            result = subprocess.run(
                ["sh", str(SCRIPT), "--install"],
                env={**os.environ, "PATH": directory + os.pathsep + os.environ["PATH"]},
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Installation requires Linux", result.stderr)
            self.assertNotIn("unexpected_sudo", result.stderr)


if __name__ == "__main__":
    unittest.main()
