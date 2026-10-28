# Diagnostic run bundles

Each attempt owns a new directory. Its manifest uses schema version 1 and records
a random run identifier, UTC start time, source commit and content hash, dirty
working-tree flag, topology mode, queue policy, phase history, artifact hashes,
units, errors, and the primary-eligibility decision. Files are published
atomically; a second attempt cannot reuse the directory.

## Files in a completed bundle

| File | Contents |
|---|---|
| configuration.json | Resolved mode, policy, durations, flow count, aggregate demand in bit/s, and service ports |
| environment.json | Operating system, kernel release, Python version, and measurement kind; no hostname |
| foreground.json | Workload configuration, monotonic phase times, every scheduled request, event counts, and detailed bounded event log |
| bulk.json | iperf3 version, requested aggregate and per-stream rates, actual receiver flow set, bytes, receiver duration, intervals, and goodput |
| cpu.json | Linux shared-host busy and I/O-wait percentages, or explicit unavailable values on unsupported systems |
| queues-before.json and queues-after.json | Namespace inspection and qdisc snapshots, or an explicit unchanged-loopback record |

The manifest hashes exactly these seven artifacts. Hashes detect changes; they
do not authenticate who collected the observations. The independent validator
also checks exact schemas, units, source identifiers, timestamp ordering, phase
arithmetic, request identifiers, event totals, flow allocation, receiver byte
totals, and topology claims. Valid JSON alone is not enough.

## Time and failure semantics

Request timestamps are monotonic nanoseconds from one host. UTC identifies the
attempt; it is not used to calculate RTT. The foreground records scheduled send,
actual send, and reply times separately. A not-sent slot is retained with its
reason. An application timeout is not proof of transport packet loss. Replies
after the deadline remain available during drain.

Receiver TCP goodput uses iperf3's own measurement duration and decimal Mb/s.
Its window currently overlaps the foreground measurement but is not exactly
aligned. The bulk record states this explicitly. CPU scope is shared_host,
because Linux network namespaces share the host CPU; it is not router-only CPU.

The normal lifecycle is preflight, setup, warmup, measurement, drain, collection,
validation, teardown, then completed. Failed and cancelled attempts preserve
their manifest and any available component output. Cleanup failures are retained
alongside the original error. A partial bundle is never accepted as completed
evidence, and a replacement uses a new directory.

## Integrity is separate from experimental acceptance

Successful validation returns integrity_valid as true. Every current diagnostic
still has eligible_for_primary set to false. Loopback does not apply a queue
policy, and namespace attachment checks do not establish rate calibration or
priority isolation. Protocol acceptance, aligned windows, and the Linux pilot
remain prerequisites for primary collection.

Use the [operating guide](running-experiments.md) to collect, validate, export,
and plot a run. The invented captures in tests/fixtures are validator examples,
not network measurements.
