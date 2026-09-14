"""Reject private files and unreadable prose in the Git index."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    problems = []
    for name in filter(None, tracked):
        path = Path(name)
        if (
            path.name.lower() in {"ai.md", ".env", ".ds_store"}
            or path.suffix.lower() in {".pcap", ".pcapng", ".pem", ".key"}
            or path.parts[0] in {"private", ".local", ".venv", "runs"}
        ):
            problems.append(f"Private or generated file is tracked: {name}")
        if path.suffix == ".md":
            text = (ROOT / path).read_text(encoding="utf-8")
            if not text.isascii():
                problems.append(f"Use ordinary ASCII in prose: {name}")
    if problems:
        print("\n".join(problems))
        return 1
    print("Tracked-file hygiene passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
