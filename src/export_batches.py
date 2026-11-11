"""Resolve bounded diagnostic export batches without following directory aliases."""

import hashlib
from pathlib import Path

from src.artifacts import digest, parse_json, read_bytes

MAX_EXPORT_BATCHES = 128
MAX_ANALYSIS_RUNS = 400


def export_inputs(directories: list[Path]) -> list[tuple[Path, dict]]:
    """O(B) metadata reads for at most 128 batches; request data stays on disk."""
    if not 1 <= len(directories) <= MAX_EXPORT_BATCHES:
        raise ValueError("analyze between one and 128 bounded exports")
    result = []
    for directory in directories:
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("export must be a real directory")
        if (directory / "index.json").exists():
            result.extend(_indexed_inputs(directory))
        else:
            result.append((directory, {}))
        if len(result) > MAX_EXPORT_BATCHES:
            raise ValueError("analysis exceeds 128 export batches")
    return result


def _indexed_inputs(directory: Path) -> list[tuple[Path, dict]]:
    data = read_bytes(directory / "index.json", 65536)
    index = parse_json(data)
    if (
        index["schema_version"] != 1
        or type(index["schema_version"]) is not int
        or index["kind"] != "diagnostic_export_batches"
        or index["state"] != "completed"
        or index["eligible_for_primary"] is not False
        or not isinstance(index["batches"], list)
        or not 1 <= len(index["batches"]) <= MAX_EXPORT_BATCHES
    ):
        raise ValueError("unsupported or incomplete export index")
    for name in ("attempts", "versions"):
        if digest(directory / f"{name}.json") != index[f"{name}_sha256"]:
            raise ValueError(f"campaign {name} hash does not match export index")
    result = []
    for number, entry in enumerate(index["batches"], 1):
        if entry["directory"] != f"batch-{number:03d}":
            raise ValueError("export batch directories must be sequential relative names")
        child = directory / entry["directory"]
        if child.is_symlink() or not child.is_dir():
            raise ValueError("export batch must be a real directory")
        result.append(
            (
                child,
                {
                    "provenance_sha256": entry["provenance_sha256"],
                    "campaign_ledger_sha256": index["attempts_sha256"],
                    "export_index_sha256": hashlib.sha256(data).hexdigest(),
                },
            )
        )
    return result
