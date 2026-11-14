"""Cross-check optional TCP, observer, forecast, and retained bulk evidence."""

from src.experiment_config import bounded_integer, bounded_number
from src.topology import CLIENT_ADDRESS, SERVER_ADDRESS


def _counter(value, name, maximum=2**64 - 1):
    return bounded_integer(value, name, 0, maximum)


def _stream(raw):
    if not isinstance(raw, dict) or raw.keys() != {"sent", "dropped"}:
        raise ValueError("transport event stream must record sent and dropped counters")
    for value in raw.values():
        _counter(value, "event count", 300_000)


def _socket_info(raw):
    if not isinstance(raw, dict) or raw.get("source") != "Linux_TCP_INFO":
        raise ValueError("TCP socket metrics need their Linux source")
    if raw.get("status") not in {"available", "unavailable_platform", "unavailable_socket"}:
        raise ValueError("unsupported TCP socket metric status")
    if raw["status"] == "available":
        for name in ("total_retransmissions", "rtt_us", "rtt_variation_us", "send_cwnd_segments"):
            _counter(raw.get(name), name, 2**32 - 1)


def _foreground(raw, transport):
    if not isinstance(raw, dict) or raw.get("transport") != transport:
        raise ValueError("foreground metrics differ from the requested transport")
    _stream(raw.get("event_stream"))
    if transport == "udp":
        return
    if raw.get("framing_bytes") != 512 or raw.get("nagle_disabled") is not True:
        raise ValueError("TCP framing and Nagle configuration differ from the contract")
    _socket_info(raw.get("before"))
    _socket_info(raw.get("after"))
    samples = raw.get("samples")
    if not isinstance(samples, list) or len(samples) > 190:
        raise ValueError("TCP socket samples exceed their time budget")
    previous = 0
    for sample in samples:
        _socket_info(sample)
        previous = bounded_integer(
            sample.get("observed_ns"), "TCP sample time", previous, 2**63 - 1
        )


def _observer(raw):
    if not isinstance(raw, dict):
        raise ValueError("TCP observer evidence must be an object")
    if raw.get("schema_version") != 1 or raw.get("status") != "completed":
        raise ValueError("TCP observer did not complete")
    _counter(raw.get("observed_packets"), "observed packet count", 2_000_000)
    _counter(raw.get("observed_flows"), "observed flow count", 64)
    dropped = _counter(raw.get("capture_dropped"), "capture drops", 2**32 - 1)
    if raw.get("quality") != ("capture_drops" if dropped else "no_reported_capture_drops"):
        raise ValueError("TCP capture quality disagrees with its dropped-packet counter")
    _stream(raw.get("event_stream"))
    rows = raw.get("windows")
    if not isinstance(rows, list) or len(rows) > 191:
        raise ValueError("TCP observer windows exceed the time budget")
    previous = -1
    for row in rows:
        previous = bounded_integer(row.get("index"), "TCP window index", previous + 1, 190)
        for key, value in row.items():
            if key != "index":
                _counter(value, "TCP window counter", 2_000_000)


def _forecast(raw):
    if not isinstance(raw, dict):
        raise ValueError("forecast evidence must be an object")
    if raw.get("schema_version") != 1 or raw.get("mode") != "shadow_only_no_policy_changes":
        raise ValueError("forecast must remain advisory")
    if raw.get("packet_loss_labels_available") is not False:
        raise ValueError("application forecasts cannot claim packet-loss labels")
    dropped = _counter(raw.get("producer_events_dropped"), "forecast dropped events", 600_000)
    if raw.get("quality") != ("incomplete_event_stream" if dropped else "no_reported_event_drops"):
        raise ValueError("forecast quality disagrees with its producer drop counters")
    forecasts = raw.get("forecasts")
    if not isinstance(forecasts, list) or len(forecasts) > 191:
        raise ValueError("forecast windows exceed their time budget")
    for forecast in forecasts:
        if not 0 <= forecast["issued_ns"] < forecast["target_start_ns"]:
            raise ValueError("forecast was issued after its target window began")
        for name, value in forecast["prediction"].items():
            if value is not None:
                bounded_number(value, name, 0, 1 if name == "timeout_fraction" else 1_000_000)


def validate_transport_artifacts(artifacts):
    config = artifacts["configuration.json"]
    transport = config.get("transport", "udp")
    if "transport" in config:
        _foreground(artifacts.get("foreground-transport.json"), transport)
    if config["mode"] != "loopback":
        capture = artifacts["foreground.json"]
        if capture["bind"] != [CLIENT_ADDRESS, 42001] or capture["peer"] != [SERVER_ADDRESS, 42000]:
            raise ValueError("foreground endpoints differ from the isolated topology")
        if transport == "tcp":
            _observer(artifacts.get("tcp-observer.json", {}))
    if config.get("shadow_forecast", False):
        _forecast(artifacts.get("shadow-forecast.json", {}))
    if "bulk-raw.json" in artifacts:
        from src.bulk import summarize_bulk
        from src.trial import TrialConfig

        actual = summarize_bulk(artifacts["bulk-raw.json"], TrialConfig(**config).bulk_plan())
        if actual != artifacts["bulk.json"]:
            raise ValueError("bulk summary differs from its retained raw receiver report")
