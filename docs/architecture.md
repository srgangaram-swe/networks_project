# Architecture

The proposal calls for separate client, router, and server roles. The first
implementation should keep their responsibilities explicit even when all three
run in Linux namespaces on one machine.

    client endpoint <-> controlled Linux router <-> server endpoint
    foreground RTT       shaping and queues        foreground responder
    bulk TCP receiver    delay and counters        bulk TCP sender

This diagram shows logical roles. The candidate protocol sends foreground
requests from client to server and responses and bulk TCP data from server to
client. The Linux adapter shapes router egress toward the client and places
receive delay at both endpoints. The command plan is executable but still
requires Linux calibration before scientific acceptance.

## Component boundaries

- Foreground client/server: bounded framing, request IDs, client-clock RTT,
  paced sends, timeout accounting, and orderly shutdown.
- Background controller: configured flow count and aggregate pacing demand;
  capture achieved goodput and process failures.
- Testbed controller: inspect, apply, verify, and clean up only owned topology resources.
- Trial runner: resolved configurations, randomized order, process lifetimes,
  deadlines, validity checks, and a complete run manifest.
- Analysis: consume immutable run bundles, validate units and schema, calculate
  per-run summaries and uncertainty, and generate figures.
- Report and demo: reference frozen evidence and distinguish measurements from fixtures.

Shared configuration validation is implemented in src/experiment_config.py.
The provisional [foreground workload](foreground-workload.md) separates wire
validation, scheduling and accounting, and socket I/O. Its record validator
matches the proposed v1 contract. Portable trial orchestration calls an explicit
testbed adapter; neither validation nor plotting changes network state.
Protocol acceptance is still required before primary collection.

The [candidate v1 decision](decisions/0001-measurement-contract.md) defines
the proposed traffic direction, delay placement, framing, and measurement
semantics. RequestRecord.from_mapping in src/measurement_contract.py checks
individual request records. src/bundle_validation.py independently checks whole
diagnostic bundles, including hashes, phases, counts, flow sets, and units.
The read-only scripts/inspect_testbed.py command supports the equipment
inventory without configuring the machine or claiming it is ready.

The foreground client and iperf3 run as separate, bounded child processes.
Service readiness comes from their output, and shutdown joins the owned child
sessions before topology cleanup. The two measurement windows remain distinct
in the data contract. The runner cannot certify primary evidence until their
alignment and the remaining pilot criteria are resolved.

## Data flow

A versioned configuration becomes a recorded schedule, then a run bundle.
Analysis reads the bundle without changing it. A release identifies the source
commit, configuration, tool versions, and hashes of approved evidence.

No analysis function should configure interfaces. No privileged setup command
should parse arbitrary unvalidated measurement files. Keep these boundaries
testable without elevated privileges.
