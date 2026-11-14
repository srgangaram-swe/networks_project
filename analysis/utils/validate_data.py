"""Check identities, counters, and request-derived metrics before fitting or comparing."""

import math

import numpy as np
import pandas as pd

from src.experiment_config import POLICIES

LATENCIES = ("p50_ms", "p95_ms", "p99_ms", "p999_ms")
METRICS = (
    *LATENCIES,
    "jitter_ms",
    "send_lag_p99_ms",
    "goodput_mbps",
    "timeout_rate",
    "not_sent_rate",
)
COUNTERS = ("scheduled", "sent", "on_time", "timeout_count", "late_count", "not_sent")


def required(frame, columns):
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")


def numeric(frame, columns, nullable=()):
    for name in columns:
        frame[name] = pd.to_numeric(frame[name].replace("", np.nan), errors="raise")
        values = frame[name]
        if np.isinf(values).any() or (values < 0).any():
            raise ValueError(f"invalid nonnegative finite values: {name}")
        if name not in nullable and values.isna().any():
            raise ValueError(f"missing numeric values: {name}")


def validate_summaries(frame, *, allow_simulated=False):
    _validate_transport(frame)
    required(
        frame,
        (
            "run_id",
            "policy",
            "requested_mbps",
            "flows",
            *METRICS,
            *COUNTERS,
            "p99_censored",
            "eligible_for_primary",
            "measurement_kind",
            "source_commit",
            "source_tree_sha256",
            "source_dirty",
            "manifest_sha256",
        ),
    )
    if frame.empty or frame["run_id"].duplicated().any():
        raise ValueError("expected unique, nonempty run summaries")
    for name, size in (
        ("run_id", 32),
        ("source_commit", 40),
        ("source_tree_sha256", 64),
        ("manifest_sha256", 64),
    ):
        if not frame[name].str.fullmatch(rf"[a-f0-9]{{{size}}}").all():
            raise ValueError(f"invalid identity: {name}")
    if not frame["policy"].isin(POLICIES | {"none"}).all():
        raise ValueError("unsupported policy")
    kinds = _measurement_kinds(allow_simulated)
    if not frame["measurement_kind"].isin(kinds).all():
        raise ValueError("simulation requires explicit permission; fixtures are not measurements")
    for name in ("p99_censored", "eligible_for_primary", "source_dirty"):
        if not frame[name].isin(("True", "False")).all():
            raise ValueError(f"invalid boolean: {name}")
        frame[name] = frame[name].eq("True")
    if frame["eligible_for_primary"].any():
        raise ValueError("diagnostic runs cannot assert primary eligibility")
    numeric(
        frame,
        (*METRICS, *COUNTERS, "requested_mbps", "flows"),
        nullable=(*LATENCIES, "jitter_ms", "send_lag_p99_ms", "timeout_rate"),
    )
    _summary_counts(frame)
    if any(name in frame for name in ("cpu_scope", "cpu_busy_percent", "cpu_iowait_percent")):
        required(frame, ("cpu_scope",))
        _cpu(frame)


def _measurement_kinds(allow_simulated):
    observed = ("virtual_testbed", "loopback_diagnostic", "physical_testbed")
    return observed + (("simulation",) if allow_simulated else ())


def _validate_transport(frame):
    if "transport" not in frame:
        frame["transport"] = "udp"
    if not frame["transport"].isin(("udp", "tcp")).all():
        raise ValueError("foreground transport must be udp or tcp")


def _cpu(frame):
    columns = ("cpu_busy_percent", "cpu_iowait_percent")
    required(frame, columns)
    numeric(frame, columns, nullable=columns)
    shared = frame["cpu_scope"].eq("shared_host")
    if not frame["cpu_scope"].isin(("shared_host", "unavailable")).all():
        raise ValueError("unsupported CPU scope")
    if (
        frame.loc[shared, list(columns)].isna().any().any()
        or frame.loc[~shared, list(columns)].notna().any().any()
    ):
        raise ValueError("CPU availability contradicts its scope")
    if (frame[list(columns)].sum(axis=1) > 100 + 1e-9).any():
        raise ValueError("CPU percentages exceed 100")


def _summary_counts(frame):
    if not frame["flows"].isin((0, 1, 8)).all():
        raise ValueError("unsupported flow count")
    if ((frame["flows"] == 0) != (frame["requested_mbps"] == 0)).any():
        raise ValueError("unloaded conditions require zero flows and demand")
    if ((frame[list(COUNTERS)] % 1) != 0).any().any() or (frame["scheduled"] < 1).any():
        raise ValueError("run counters must be positive/integer as appropriate")
    if not (frame["sent"] + frame["not_sent"]).eq(frame["scheduled"]).all():
        raise ValueError("scheduled request counters do not reconcile")
    if not (frame["on_time"] + frame["timeout_count"]).eq(frame["sent"]).all():
        raise ValueError("sent request counters do not reconcile")
    if (frame["late_count"] > frame["timeout_count"]).any():
        raise ValueError("late replies exceed timeout outcomes")


def _same(actual, expected, label):
    if pd.isna(actual) and expected is None:
        return
    if expected is None or pd.isna(actual) or not math.isclose(actual, expected, abs_tol=1e-8):
        raise ValueError(f"request-derived {label} does not match summary")


def quantile(values, fraction):
    """Nearest rank on values already sorted in increasing order."""
    if not values:
        return None
    return values[math.ceil(fraction * len(values)) - 1]


def validate_requests(requests, summaries):
    required(
        requests, ("run_id", "request_id", "elapsed_seconds", "outcome", "rtt_ms", "send_lag_ms")
    )
    if not requests["run_id"].isin(summaries["run_id"]).all():
        raise ValueError("request refers to an unknown run")
    if requests.duplicated(["run_id", "request_id"]).any():
        raise ValueError("duplicate request identity")
    numeric(
        requests,
        ("request_id", "elapsed_seconds", "rtt_ms", "send_lag_ms"),
        ("rtt_ms", "send_lag_ms"),
    )
    if (requests["request_id"] % 1).any() or not requests["outcome"].isin(
        ("on_time", "late", "timeout", "not_sent")
    ).all():
        raise ValueError("invalid request ID or outcome")
    groups = {key: group for key, group in requests.groupby("run_id", sort=False)}
    for row in summaries.to_dict("records"):
        _run_requests(groups.get(row["run_id"], requests.iloc[:0]), row)


def _run_requests(group, summary):
    group = group.sort_values("request_id")
    counts = group["outcome"].value_counts()
    if len(group) != summary["scheduled"]:
        raise ValueError("per-run request count does not match summary")
    expected = {
        "on_time": summary["on_time"],
        "not_sent": summary["not_sent"],
        "late": summary["late_count"],
        "timeout": summary["timeout_count"] - summary["late_count"],
    }
    if any(counts.get(key, 0) != value for key, value in expected.items()):
        raise ValueError("request outcomes do not match counters")
    received = group["outcome"].isin(("on_time", "late"))
    sent = group["outcome"] != "not_sent"
    if (
        not group["rtt_ms"].notna().eq(received).all()
        or not group["send_lag_ms"].notna().eq(sent).all()
    ):
        raise ValueError("request timestamps do not match outcomes")
    good = sorted(group.loc[group["outcome"] == "on_time", "rtt_ms"].tolist())
    for name, q in zip(LATENCIES, (0.5, 0.95, 0.99, 0.999), strict=True):
        _same(summary[name], quantile(good, q), name)
    _same(
        summary["send_lag_p99_ms"],
        quantile(sorted(group.loc[sent, "send_lag_ms"].tolist()), 0.99),
        "send lag",
    )
    _same(summary["not_sent_rate"], summary["not_sent"] / len(group), "unsent rate")
    values = group["rtt_ms"].to_numpy(float)
    on_time = group["outcome"].eq("on_time").to_numpy()
    valid_pairs = on_time[:-1] & on_time[1:]
    jitter = np.abs(np.diff(values))[valid_pairs]
    _same(summary["jitter_ms"], float(np.median(jitter)) if len(jitter) else None, "jitter")
    timeout = summary["timeout_count"] / summary["sent"] if summary["sent"] else None
    _same(summary["timeout_rate"], timeout, "timeout rate")
    if summary["p99_censored"] != (timeout is None or timeout > 0.01):
        raise ValueError("p99 censoring flag contradicts outcomes")
