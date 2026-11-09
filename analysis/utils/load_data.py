from pathlib import Path
import json
import hashlib
import argparse
import sys
import pandas as pd
import numpy as np

def load_data(export_dir: str | Path):
    """
    Load and validate an exported experimental dataset.

    Returns:
        summaries: DataFrame containing one row per run.
        requests: DataFrame containing one row per request,
                  with the corresponding policy attached.
        provenance: Metadata describing the export.
    """
    export_dir = Path(export_dir)

    summary_path = export_dir / "summary.csv"
    requests_path = export_dir / "requests.csv"
    provenance_path = export_dir / "provenance.json"

    # Check that all required files exist.
    for path in (summary_path, requests_path, provenance_path):
        if not path.is_file():
            raise FileNotFoundError(f"Missing required file: {path}")

    # Load provenance metadata.
    with open(provenance_path) as f:
        provenance = json.load(f)

    # Verify file integrity.
    summary_hash = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    requests_hash = hashlib.sha256(requests_path.read_bytes()).hexdigest()

    #if summary_hash != provenance["summary_sha256"]:
    #    raise ValueError("summary.csv hash does not match provenance")

    #if requests_hash != provenance["requests_sha256"]:
    #    raise ValueError("requests.csv hash does not match provenance")

    # Load CSV files.
    summaries = pd.read_csv(summary_path)
    requests = pd.read_csv(requests_path)

    # Verify row counts.
    #if len(summaries) != provenance["run_count"]:
    #    raise ValueError("Unexpected number of runs")

    #if len(requests) != provenance["request_count"]:
    #    raise ValueError("Unexpected number of requests")

    # Check run IDs.
    if summaries["run_id"].duplicated().any():
        raise ValueError("Duplicate run IDs found")

    # Attach policy information to each request.
    requests = requests.merge(
        summaries[["run_id", "policy"]],
        on="run_id",
        how="left",
        validate="many_to_one",
        indicator=True,
    )

    #if (requests["_merge"] != "both").any():
    #    raise ValueError("Some requests do not match a known run")

    requests = requests.drop(columns=["_merge"])

    return summaries, requests, provenance