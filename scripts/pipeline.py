"""Launch the selected experiment topology and its downstream analysis."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
