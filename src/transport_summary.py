"""Export transport evidence without treating retransmissions as packet-loss labels."""

from src.artifacts import read_json

FIELDS = (
    "tcp_total_retransmissions",
    "tcp_send_cwnd_segments_end",
    "tcp_rtt_us_end",
    "tcp_foreground_duplicate_ack_candidates",
    "tcp_bulk_duplicate_ack_candidates",
    "tcp_capture_dropped",
)


def summarize_transport(directory, manifest):
    result = dict.fromkeys(FIELDS)
    names = manifest["artifacts"]
    if "foreground-transport.json" in names:
        metrics = read_json(directory / "foreground-transport.json")
        before, after = metrics.get("before", {}), metrics.get("after", {})
        if before.get("status") == after.get("status") == "available":
            result.update(
                tcp_total_retransmissions=after["total_retransmissions"]
                - before["total_retransmissions"],
                tcp_send_cwnd_segments_end=after["send_cwnd_segments"],
                tcp_rtt_us_end=after["rtt_us"],
            )
    if "tcp-observer.json" in names:
        observer = read_json(directory / "tcp-observer.json")
        for scope in ("foreground", "bulk"):
            name = f"{scope}_duplicate_ack_candidates"
            result[f"tcp_{name}"] = sum(row.get(name, 0) for row in observer["windows"])
        result["tcp_capture_dropped"] = observer["capture_dropped"]
    return result
