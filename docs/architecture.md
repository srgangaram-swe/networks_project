# Architecture

The proposal calls for separate client, router, and server roles. The first
implementation should keep their responsibilities explicit even when all three
run in Linux namespaces on one machine.

```text
client endpoint <-> controlled Linux router <-> server endpoint
foreground RTT       shaping and queues        foreground responder
bulk TCP sender      delay and counters        bulk TCP receiver
```

The diagram is logical. The architecture issue must pin both traffic directions
and the placement of delay and shaping before it becomes an executable topology.

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

Shared configuration validation is implemented in `src/experiment_config.py`.
The remaining components are planned. Add a decision record before changing
their interfaces or the measurement definition.

## Data flow

A versioned configuration becomes a recorded schedule, then a run bundle.
Analysis reads the bundle without changing it. A release identifies the source
commit, configuration, tool versions, and hashes of approved evidence.

No analysis function should configure interfaces. No privileged setup command
should parse arbitrary unvalidated measurement files. Keep these boundaries
testable without elevated privileges.
