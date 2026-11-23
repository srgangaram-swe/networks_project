"""Convert scheduled experiment cells into executable trial configurations."""

from src.experiment_config import ExperimentConfig
from src.trial import TrialConfig


def trial_from_cell(
        cell: dict,
        experiment: ExperimentConfig,
) -> TrialConfig:
    # Current testbed parameters are hard-coded.
    if (
            experiment.link_rate_mbps != 100
            or experiment.base_rtt_ms != 20
            or experiment.foreground_message_bytes != 512
            or experiment.foreground_requests_per_second != 500
    ):
        raise ValueError(
            "planning parameters differ from the implemented testbed"
        )

    if cell["policy"] not in experiment.policies:
        raise ValueError("unsupported scheduled queue policy")

    transport = cell["transport"]
    flows = cell["flows"]
    load = cell["load_fraction"]

    if transport == "none":
        if flows != 0 or load != 0:
            raise ValueError("invalid unloaded baseline")
        aggregate_bps = 0

    else:
        if transport not in experiment.transports:
            raise ValueError("unsupported scheduled transport")

        if flows not in experiment.background_flow_counts:
            raise ValueError("unsupported scheduled flow count")

        if load not in experiment.background_load_fractions:
            raise ValueError("unsupported scheduled load")

        requested_bps = experiment.link_rate_mbps * 1_000_000 * load
        aggregate_bps = round(requested_bps)

        if abs(requested_bps - aggregate_bps) > 1e-6:
            raise ValueError("requested bitrate is not an integer")

        if aggregate_bps % flows:
            raise ValueError(
                "aggregate bitrate must divide evenly among flows"
            )

    return TrialConfig(
        mode="namespace",
        policy=cell["policy"],
        measurement_seconds=experiment.measurement_seconds,
        warmup_seconds=10,
        flows=flows,
        aggregate_bps=aggregate_bps,
        transport=transport,
    )
