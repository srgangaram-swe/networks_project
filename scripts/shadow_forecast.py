"""Run an advisory online model beside a local client process."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.shadow_runtime import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
