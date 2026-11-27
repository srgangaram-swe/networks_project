"""Create a bounded local environment without changing the system interpreter."""

import sys
from pathlib import Path

from src.artifacts import parse_json, read_bytes
from src.processes import run_command

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = {
    "development": ("requirements-dev.txt", "requirements-analysis.txt"),
    "analysis": ("requirements-analysis.txt",),
}


def environment_plan(directory: Path, profile: str) -> dict:
    if profile not in REQUIREMENTS:
        raise ValueError("environment profile must be development or analysis")
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise ValueError("environment must be a real directory")
    target = directory.absolute()
    if not target.parent.is_dir():
        raise ValueError("create the environment's parent directory first")
    return {
        "venv": str(target),
        "profile": profile,
        "requirements": [str(ROOT / name) for name in REQUIREMENTS[profile]],
        "python_minimum": "3.12",
        "create_timeout_seconds": 60,
        "install_timeout_seconds": 300,
        "system_packages_modified": False,
        "network_changes": False,
    }


def _check_environment(directory, run):
    configuration = read_bytes(directory / "pyvenv.cfg", 8192).decode("utf-8")
    settings = dict(
        line.strip().split(" = ", 1) for line in configuration.splitlines() if " = " in line
    )
    if settings.get("include-system-site-packages") != "false":
        raise ValueError("environment must exclude system site packages")
    result = run(
        [
            str(directory / "bin/python"),
            "-c",
            "import json,sys; "
            "print(json.dumps([sys.prefix,sys.base_prefix,list(sys.version_info[:3])]))",
        ],
        timeout=10,
        limit=8192,
    )
    identity = parse_json(result.stdout)
    if not isinstance(identity, list) or len(identity) != 3:
        raise ValueError("invalid environment identity")
    prefix, base, version = identity
    if (
        not isinstance(prefix, str)
        or not isinstance(base, str)
        or not isinstance(version, list)
        or len(version) != 3
        or any(type(n) is not int for n in version)
    ):
        raise ValueError("invalid environment identity fields")
    if (
        Path(prefix).resolve() != directory.resolve()
        or Path(prefix).resolve() == Path(base).resolve()
        or version[:2] < [3, 12]
    ):
        raise ValueError("interpreter does not identify the requested Python 3.12+ environment")
    return version


def setup_environment(directory: Path, profile: str = "development", *, run=run_command) -> dict:
    """At most four subprocesses, each with a deadline and 1 MiB output budget.

    Partial environments remain for inspection. Existing directories must prove
    their interpreter and isolation before any package installation is attempted.
    """
    plan = environment_plan(directory, profile)
    target = Path(plan["venv"])
    created = not target.exists()
    if created:
        run([sys.executable, "-m", "venv", str(target)], timeout=60)
    version = _check_environment(target, run)
    command = [
        str(target / "bin/python"),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--progress-bar",
        "off",
        "--retries",
        "1",
        "--timeout",
        "30",
    ]
    for path in plan["requirements"]:
        command.extend(["-r", path])
    result = run(command, timeout=300, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).decode("utf-8", errors="replace")[-8192:]
        raise RuntimeError(f"package installation exited {result.returncode}: {detail}")
    run([str(target / "bin/python"), "-m", "pip", "check"], timeout=30)
    return {**plan, "state": "completed", "created": created, "python_version": version}
