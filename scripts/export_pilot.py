"""Export validated pilot observations and account for every attempted cell."""

import argparse
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.artifacts import atomic_json, digest, read_json  # noqa: E402
from src.diagnostics import export_diagnostics  # noqa: E402
from src.processes import run_command  # noqa: E402


def export(campaign: Path, output: Path) -> None:
    plan = read_json(campaign / "plan.json", 65536)
    progress = read_json(campaign / "progress.json", 262144)
    if digest(campaign / "plan.json") != progress["plan_sha256"]:
        raise ValueError("retained campaign plan changed")
    attempts, directories = [], []
    if not isinstance(progress["attempts"], list) or len(progress["attempts"]) > 120:
        raise ValueError("invalid attempt count")
    for index, attempt in enumerate(progress["attempts"]):
        cell = attempt["cell_id"]
        if cell not in {row["cell_id"] for row in plan["schedule"]["cells"]}:
            raise ValueError("attempt does not belong to the planned schedule")
        name = f"attempt-{index + 1:03d}-{cell}"
        if attempt["directory"] != name:
            raise ValueError("invalid attempt directory")
        if attempt["status"] == "completed":
            if digest(campaign / name / "manifest.json") != attempt["manifest_sha256"]:
                raise ValueError("completed attempt digest changed")
            directories.append(campaign / name)
        attempts.append(attempt)
    if directories:
        export_diagnostics(directories, output)
    else:
        output.mkdir(mode=0o755)
    atomic_json(
        output / "attempts.json",
        {
            "schema_version": 1,
            "campaign_state": progress["state"],
            "attempts": attempts,
            "plan": plan,
            "progress_sha256": digest(campaign / "progress.json"),
            "primary_eligible": False,
            "excluded_from_primary": "pilot_review_and_window_alignment_pending",
        },
    )
    versions = {}
    for name, args in (
        ("iproute2", ("tc", "-V")),
        ("iperf3", ("iperf3", "--version")),
        ("tcpdump", ("tcpdump", "--version")),
        ("ethtool", ("ethtool", "--version")),
    ):
        result = run_command(args, limit=8192)
        versions[name] = (result.stdout or result.stderr).decode("utf-8").splitlines()[0][:512]
    atomic_json(
        output / "versions.json",
        {
            "system": platform.system(),
            "kernel": platform.release(),
            "python": platform.python_version(),
            "tools": versions,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        export(args.campaign, args.output)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(f"Pilot export failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
