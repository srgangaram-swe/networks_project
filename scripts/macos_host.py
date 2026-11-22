"""Run the portable worker CLI with the macOS endpoint adapter."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import physical_worker
from src.macos_endpoint import act

if __name__ == "__main__":
    raise SystemExit(physical_worker.main(handler=act))
