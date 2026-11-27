"""Causal next-window forecasts, trained only after request cohorts have settled."""

import math
from collections import Counter

from src.online_regression import OnlineRidge

SECOND = 1_000_000_000
MIN_TRAINING_WINDOWS = 5


def percentile99(values):
    ordered = sorted(values)
    return ordered[math.ceil(0.99 * len(ordered)) - 1] if ordered else None


class ShadowForecast:
    """At most 190 windows, 1,024 live requests, and 500 RTTs per cohort.

    A forecast issued in window K targets requests sent in K+1. Labels wait
    until that cohort has closed and its one-second request deadline passed.
    Models observe application outcomes, not physical packet-loss labels.
    """

    def __init__(self, start_ns):
        self.start_ns = start_ns
        self.windows = {}
        self.pending = {}
        self.forecasts = {}
        self.models = {name: OnlineRidge(9) for name in ("p99_ms", "timeout_fraction")}
        self.last_window = -1
        self.late_events = 0

    def _window(self, index):
        if not 0 <= index <= 190:
            raise ValueError("forecast window exceeds its time budget")
        return self.windows.setdefault(index, {"counts": Counter(), "rtts": []})

    def observe(self, event, now_ns):
        observed = event.get("observed_ns")
        if type(observed) is not int or not self.start_ns <= observed <= now_ns:
            raise ValueError("forecast event needs a past client monotonic timestamp")
        index = (observed - self.start_ns) // SECOND
        window = self._window(index)
        if index < self.last_window - 2:
            self.late_events += 1
            return
        kind = event.get("kind")
        if kind == "tcp_window":
            for key in ("foreground_duplicate_ack_candidates", "bulk_duplicate_ack_candidates"):
                value = event.get(key, 0)
                if type(value) is not int or not 0 <= value <= 2_000_000:
                    raise ValueError("invalid observed ACK count")
                window["counts"]["duplicate_ack_candidates"] += value
            window["counts"]["tcp_windows"] += 1
        elif kind == "send":
            self._send(event, index, window)
        elif kind in {"reply", "deadline"}:
            self._outcome(event, window)
        else:
            raise ValueError("unsupported forecast event")

    def _send(self, event, index, window):
        request_id = event["request_id"]
        if type(request_id) is not int or not 0 <= request_id < 90_000:
            raise ValueError("invalid forecast request ID")
        if request_id in self.pending or len(self.pending) >= 1024:
            raise ValueError("forecast request accounting exceeds its bound")
        if window["counts"]["sent"] >= 500:
            raise ValueError("forecast cohort exceeds its rate budget")
        self.pending[request_id] = (index, event["observed_ns"])
        window["counts"]["sent"] += 1

    def _outcome(self, event, arrivals):
        pending = self.pending.pop(event["request_id"], None)
        if pending is None:
            return
        index, sent = pending
        cohort = self._window(index)
        rtt_ms = (event["observed_ns"] - sent) / 1_000_000
        if event["kind"] == "deadline" or rtt_ms > 1000:
            cohort["counts"]["timeouts"] += 1
            arrivals["counts"]["deadline_events"] += 1
        else:
            cohort["rtts"].append(rtt_ms)
            arrivals["counts"]["replies"] += 1
            arrivals["counts"]["arrival_rtt_sum_ms"] += rtt_ms

    def advance(self, now_ns):
        index = (now_ns - self.start_ns) // SECOND
        self._window(index)
        if index <= self.last_window:
            return
        self.last_window = index
        self._settle(index)
        # Predict the next full second even if event processing crossed a boundary.
        target = index + 1
        if target > 190:
            return
        previous = self._window(max(0, index - 1))["counts"]
        features = [
            1.0,
            previous["sent"] / 500,
            previous["replies"] / 500,
            previous["deadline_events"] / 500,
            previous["arrival_rtt_sum_ms"] / max(1, previous["replies"]) / 1000,
            len(self.pending) / 1024,
            previous["duplicate_ack_candidates"] / 1000,
            float(previous["tcp_windows"] > 0),
            float(previous["sent"] == 0),
        ]
        predictions = {
            name: model.predict(features) if model.samples >= MIN_TRAINING_WINDOWS else None
            for name, model in self.models.items()
        }
        if predictions["timeout_fraction"] is not None:
            predictions["timeout_fraction"] = min(1, max(0, predictions["timeout_fraction"]))
        if predictions["p99_ms"] is not None:
            predictions["p99_ms"] = max(0, predictions["p99_ms"])
        self.forecasts[target] = {
            "target_window": target,
            "issued_ns": now_ns,
            "target_start_ns": self.start_ns + target * SECOND,
            "features": features,
            "training_windows": {name: model.samples for name, model in self.models.items()},
            "prediction": predictions,
            "actual": None,
            "advice": advice(predictions),
        }

    def _settle(self, current):
        for index, forecast in self.forecasts.items():
            if forecast["actual"] is not None or index + 2 >= current:
                continue
            window = self._window(index)
            counts = window["counts"]
            settled = len(window["rtts"]) + counts["timeouts"]
            if counts["sent"] == 0 or settled != counts["sent"]:
                forecast["actual"] = {}
                continue
            actual = {
                "p99_ms": percentile99(window["rtts"]),
                "timeout_fraction": counts["timeouts"] / counts["sent"],
            }
            forecast["actual"] = actual
            for name, value in actual.items():
                if value is not None:
                    self.models[name].update(forecast["features"], value)

    def report(self):
        return {
            "schema_version": 1,
            "mode": "shadow_only_no_policy_changes",
            "target": "next_full_second_send_cohort_on_time_p99_and_application_timeout_fraction",
            "method": "online_ridge_unit_penalty_fixed_units_delayed_labels",
            "start_ns": self.start_ns,
            "packet_loss_labels_available": False,
            "late_events_ignored": self.late_events,
            "pending_requests": len(self.pending),
            "forecasts": list(self.forecasts.values()),
        }


def advice(predictions):
    timeout, latency = predictions["timeout_fraction"], predictions["p99_ms"]
    if timeout is None or latency is None:
        return "collect_more_windows"
    return "inspect_queue_and_offered_load" if timeout > 0.01 or latency > 50 else "observe"
