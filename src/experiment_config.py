"""Validate planned inputs without configuring a network or generating traffic."""

import math
from dataclasses import dataclass
from typing import Any

POLICIES = frozenset({"fifo", "fq_codel", "cake_best_effort", "cake_bounded"})
TRANSPORTS = frozenset({"tcp", "sctp"})
FIELDS = frozenset(
    {
        "schema_version",
        "policies",
        "transports",
        "link_rate_mbps",
        "base_rtt_ms",
        "foreground_message_bytes",
        "foreground_requests_per_second",
        "background_load_fractions",
        "background_flow_counts",
        "repetitions",
        "measurement_seconds",
        "unloaded_repetitions_per_policy",
        "random_seed",
    }
)


def bounded_number(value: Any, name: str, low: float, high: float) -> float:
    """Reject booleans and non-finite values before accepting a numeric field."""
    if type(value) not in (int, float) or not low <= value <= high:
        raise ValueError(f"{name} must be a finite number in [{low}, {high}]")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return float(value)


def bounded_integer(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def unique_list(value: Any, name: str) -> list:
    if not isinstance(value, list) or not value or len(value) > 20:
        raise ValueError(f"{name} must contain between 1 and 20 entries")
    if any(value[:index].count(item) for index, item in enumerate(value)):
        raise ValueError(f"{name} must not contain duplicates")
    return value


@dataclass(frozen=True)
class ExperimentConfig:
    """Validated planning configuration; this is not an executable topology."""

    policies: tuple[str, ...]
    transports: tuple[str, ...]
    link_rate_mbps: float
    base_rtt_ms: float
    foreground_message_bytes: int
    foreground_requests_per_second: int
    background_load_fractions: tuple[float, ...]
    background_flow_counts: tuple[int, ...]
    repetitions: int
    measurement_seconds: int
    unloaded_repetitions_per_policy: int
    random_seed: int

    @classmethod
    def from_mapping(cls, raw: Any) -> "ExperimentConfig":
        if not isinstance(raw, dict) or raw.keys() != FIELDS:
            raise ValueError("configuration must contain exactly the documented schema fields")
        bounded_integer(raw["schema_version"], "schema_version", 2, 2)
        policies = unique_list(raw["policies"], "policies")
        if any(not isinstance(policy, str) or policy not in POLICIES for policy in policies):
            raise ValueError("policies contains an unsupported queue policy")
        # NEW: Validate transport protocols
        transports = unique_list(raw["transports"], "transports")
        if any(
            not isinstance(transport, str) or transport not in TRANSPORTS
            for transport in transports
        ):
            raise ValueError("unsupported transport protocol")
        config = cls(
            policies=tuple(policies),
            transports=tuple(transports),
            link_rate_mbps=bounded_number(raw["link_rate_mbps"], "link_rate_mbps", 1, 10000),
            base_rtt_ms=bounded_number(raw["base_rtt_ms"], "base_rtt_ms", 0, 1000),
            foreground_message_bytes=bounded_integer(
                raw["foreground_message_bytes"], "foreground_message_bytes", 1, 65536
            ),
            foreground_requests_per_second=bounded_integer(
                raw["foreground_requests_per_second"], "foreground_requests_per_second", 1, 100000
            ),
            background_load_fractions=tuple(
                bounded_number(value, "background_load_fractions", 0.01, 2)
                for value in unique_list(
                    raw["background_load_fractions"], "background_load_fractions"
                )
            ),
            background_flow_counts=tuple(
                bounded_integer(value, "background_flow_counts", 1, 128)
                for value in unique_list(raw["background_flow_counts"], "background_flow_counts")
            ),
            repetitions=bounded_integer(raw["repetitions"], "repetitions", 2, 100),
            measurement_seconds=bounded_integer(
                raw["measurement_seconds"], "measurement_seconds", 1, 3600
            ),
            unloaded_repetitions_per_policy=bounded_integer(
                raw["unloaded_repetitions_per_policy"], "unloaded_repetitions_per_policy", 2, 100
            ),
            random_seed=bounded_integer(raw["random_seed"], "random_seed", 0, 2**32 - 1),
        )

        # Ensure the planned configuration matches the implemented testbed.
        if (
                config.link_rate_mbps != 100
                or config.base_rtt_ms != 20
                or config.foreground_message_bytes != 512
                or config.foreground_requests_per_second != 500
        ):
            raise ValueError("configuration does not match the implemented testbed")

        if any(flows not in (1, 8) for flows in config.background_flow_counts):
            raise ValueError("the runtime supports only 1 or 8 background flows")

        if not 2 <= config.measurement_seconds <= 120:
            raise ValueError("measurement duration must be between 2 and 120 seconds")

        for load in config.background_load_fractions:
            requested_bps = config.link_rate_mbps * 1_000_000 * load
            aggregate_bps = round(requested_bps)

            if abs(requested_bps - aggregate_bps) > 1e-6:
                raise ValueError("requested bitrate must be an integer")

            if not 8_000_000 <= aggregate_bps <= 200_000_000:
                raise ValueError("bulk bitrate must be between 8 and 200 Mbps")

            if any(aggregate_bps % flows for flows in config.background_flow_counts):
                raise ValueError("bulk bitrate must divide evenly among flows")

        if config.total_runs > 10000:
            raise ValueError("configuration exceeds the 10000-run planning limit")
        return config

    @property
    def loaded_runs(self) -> int:
        return (
            len(self.policies)
            * len(self.transports)
            * len(self.background_load_fractions)
            * len(self.background_flow_counts)
            * self.repetitions
        )

    @property
    def unloaded_runs(self) -> int:
        return len(self.policies) * self.unloaded_repetitions_per_policy

    @property
    def total_runs(self) -> int:
        return self.loaded_runs + self.unloaded_runs

    @property
    def measurement_seconds_total(self) -> int:
        return self.total_runs * self.measurement_seconds
