"""Paced reverse TCP streams and checked receiver goodput from iperf3."""

from dataclasses import asdict, dataclass
from typing import Any

from src.experiment_config import bounded_integer, bounded_number
from src.foreground_io import endpoint


@dataclass(frozen=True)
class BulkPlan:
    aggregate_bps: int
    flows: int
    measurement_seconds: int
    warmup_seconds: int = 0

    def __post_init__(self) -> None:
        bounded_integer(self.aggregate_bps, "aggregate_bps", 8, 200_000_000)
        if type(self.flows) is not int or self.flows not in (1, 8):
            raise ValueError("bulk traffic requires one or eight flows")
        bounded_integer(self.measurement_seconds, "measurement_seconds", 1, 120)
        bounded_integer(self.warmup_seconds, "warmup_seconds", 0, 60)
        if self.aggregate_bps % self.flows:
            raise ValueError("aggregate rate must divide exactly among flows")

    @property
    def per_flow_bps(self) -> int:
        return self.aggregate_bps // self.flows


def client_command(
    plan: BulkPlan,
    bind: str,
    peer: str,
    port: int,
    *,
    linux: bool = False,
    allow_isolated: bool = False,
) -> tuple[str, ...]:
    endpoint(bind, port, allow_isolated)
    endpoint(peer, port, allow_isolated)
    if not port:
        raise ValueError("iperf3 needs an explicit listening port")
    # iperf3 applies -b to each parallel stream, not to their aggregate.
    command = (
        "iperf3",
        "-c",
        peer,
        "-B",
        bind,
        "-p",
        str(port),
        "-R",
        "-P",
        str(plan.flows),
        "-b",
        str(plan.per_flow_bps),
        "-t",
        str(plan.measurement_seconds),
        "-O",
        str(plan.warmup_seconds),
        "-i",
        "1",
        "-J",
        "--get-server-output",
        "--connect-timeout",
        "2000",
    )
    return command + (("-C", "cubic") if linux else ())


def server_command(bind: str, port: int, *, allow_isolated: bool = False) -> tuple[str, ...]:
    endpoint(bind, port, allow_isolated)
    if not port:
        raise ValueError("iperf3 needs an explicit listening port")
    return ("iperf3", "-s", "-1", "-B", bind, "-p", str(port), "--forceflush")


def _stream_summary(raw: dict, plan: BulkPlan) -> tuple[dict, dict]:
    start, end = raw["start"], raw["end"]
    if not isinstance(start, dict) or not isinstance(end, dict):
        raise ValueError("iperf3 start and end sections must be objects")
    settings = start["test_start"]
    if not isinstance(settings, dict):
        raise ValueError("iperf3 test settings must be an object")
    expected = {
        "protocol": "TCP",
        "num_streams": plan.flows,
        "reverse": 1,
        "duration": plan.measurement_seconds,
        "omit": plan.warmup_seconds,
    }
    if any(
        type(settings.get(key)) is not type(value) or settings[key] != value
        for key, value in expected.items()
    ):
        raise ValueError("iperf3 settings do not match the requested TCP workload")
    if settings.get("target_bitrate") != plan.per_flow_bps:
        raise ValueError("iperf3 per-flow pacing target does not match the request")
    if not isinstance(start["connected"], list) or not isinstance(end["streams"], list):
        raise ValueError("iperf3 flow lists are missing")
    if len(start["connected"]) != plan.flows or len(end["streams"]) != plan.flows:
        raise ValueError("iperf3 did not establish the full flow set")
    if len({stream["socket"] for stream in start["connected"]}) != plan.flows:
        raise ValueError("duplicate iperf3 flow identifiers")
    return start, end


def summarize_bulk(raw: Any, plan: BulkPlan) -> dict:
    """Validate before using totals; parse O(F + I) flow and interval records.

    The receiver window belongs to iperf3. It is not assumed to coincide with
    the foreground window. The trial manifest retains that limitation.
    """
    if not isinstance(raw, dict) or "error" in raw:
        raise ValueError("iperf3 did not report a successful object")
    try:
        start, end = _stream_summary(raw, plan)
        received = end["sum_received"]
        seconds = bounded_number(received["seconds"], "receiver seconds", 0.001, 181)
        byte_count = bounded_integer(received["bytes"], "receiver bytes", 0, 2**53)
        if abs(seconds - plan.measurement_seconds) > 0.25:
            raise ValueError("receiver duration differs from the requested measurement window")
        if not isinstance(raw["intervals"], list) or not 1 <= len(raw["intervals"]) <= 400:
            raise ValueError("missing or excessive receiver intervals")
        intervals = _intervals(raw["intervals"], plan.flows)
        if not intervals:
            raise ValueError("no measured receiver interval")
        version = start["version"]
        if not isinstance(version, str) or not 1 <= len(version) <= 100:
            raise ValueError("invalid iperf3 version")
    except (KeyError, TypeError) as exc:
        raise ValueError("incomplete iperf3 receiver report") from exc
    return {
        "requested": asdict(plan),
        "per_flow_bps": plan.per_flow_bps,
        "actual_flows": plan.flows,
        "receiver_bytes": byte_count,
        "receiver_seconds": seconds,
        "goodput_mbps": 8 * byte_count / seconds / 1_000_000,
        "intervals": intervals,
        "tool_version": version,
        "exit_status": 0,
        "window": "iperf_receiver",
        "foreground_window_aligned": False,
    }


def _intervals(rows: list, flows: int) -> list[dict]:
    result = []
    last = 0.0
    for row in rows:
        summary = row["sum"]
        if not isinstance(summary, dict):
            raise ValueError("receiver interval must be an object")
        if summary["omitted"] is True:
            continue
        if (
            summary["omitted"] is not False
            or summary["sender"] is not False
            or len(row["streams"]) != flows
        ):
            raise ValueError("expected complete receiver intervals")
        start = bounded_number(summary["start"], "interval start", last, 181)
        end = bounded_number(summary["end"], "interval end", start, 181)
        if end <= start or abs(start - last) > 0.01:
            raise ValueError("receiver intervals have a gap or no duration")
        count = bounded_integer(summary["bytes"], "interval bytes", 0, 2**53)
        result.append({"start_seconds": start, "end_seconds": end, "bytes": count})
        last = end
    return result
