# Work-item acceptance audit

The batch covers ten work items, #2 through #11. Four components meet their
implementation and verification criteria: topology (#5), foreground workload
(#7), bulk workload (#8), and bundle validation (#10). Issue closure follows
their integration into dev. The six remaining items stay open with the gaps
below. Repository promotion publishes the verified development software; it
does not approve the primary experiment or complete either research milestone.

## Completed components

### #5: Isolated topology and cleanup

The namespace fallback creates only journaled client, router, and server
resources. It does not accept host NIC names. Unit tests cover ownership
replacement, collisions, locking, cleanup failures, and command planning.
Real Linux tests verify both endpoint routes through the router, endpoint
offloads, and reply RTT above 18 ms and below 200 ms in both directions for
the specified 20 ms path. These broad smoke-test bounds detect missing delay
and gross scheduling faults; they are not calibration tolerances.

The Linux suite also interrupts an active trial, injects setup failure after
real namespace and veth creation, repeats cleanup, and checks that an unrelated
namespace retains its original identity. Every normal profile run validates
its bundle and finishes with an empty ownership journal. Environment and
topology records label these runs as virtual testbed observations. Physical
equipment acceptance and protocol review remain separate in #2, #3, and #11.

### #7: Paced foreground workload

The 512-byte UDP contract and 500-request/s schedule retain explicit request
identifiers, scheduled and actual send times, replies, and deadline outcomes.
State, event logs, message lengths, duration, and child lifetime are bounded.
Framing and accounting tests cover malformed payloads, duplicates, lost and
late replies, stalls, cancellation, and shutdown. Process CPU time and sender
lag remain available for overhead assessment. This component reached dev in
MR #27; issue #7 was already closed.

### #8: Bulk-load control

Allocation tests cover the 50, 90, and 110 Mb/s aggregate requests. The command
divides each target across one or eight reverse TCP streams. Reports preserve
requested demand, actual flow count, receiver bytes and duration, calculated
goodput, tool version, and exit status. Real loopback tests cover both flow
counts, an occupied server port, and refused client connections. Invalid or
partial reports fail instead of becoming successful runs.

On the hosted Linux FIFO topology, the above-capacity check requested 110 Mb/s
and observed 93.681 Mb/s with one stream and 93.677 Mb/s with eight streams.
Queue-byte counters increased by 49,794,439 and 50,746,116 respectively, covering
warmup and collection. Each trial checked the foreground request rate and slot
count and left no owned namespace. These short checks establish workload
execution through the shaped path, not final rate calibration or exact window
alignment. Primary experiment acceptance remains in #9 and #11.

### #10: Independent bundle validation

The schema-v1 validator rejects missing fields, unsupported units and versions,
non-finite values, duplicate identifiers, impossible timestamps, incomplete
states, artifact-hash mismatches, and inconsistent outcomes. It checks requested
load and flow allocation against configuration, recomputes goodput from receiver
bytes and duration, reconciles interval totals, and compares the receiver window
duration with the configured duration. A regression demonstrates rejection even
when altered byte, duration, and goodput fields agree with one another.

The fixture generator writes complete valid and invalid examples with explicit
synthetic labels. The invalid example has a duplicate identifier and recomputed
hashes, so its rejection demonstrates semantic validation. CLI tests also reject
partial and truncated manifests without modifying them. Diagnostic export
refuses synthetic fixtures and incomplete bundles. Integrity and scientific
eligibility remain separate; every current bundle is ineligible for primary use.

## Remaining items

| Item | Evidence already present | Missing criterion |
|---|---|---|
| #2 | Candidate protocol, metric definitions, request contract, worked examples, randomization and estimator choices | Team protocol review, acceptance of the remaining choices, calibrated tolerances and final tool pins |
| #3 | Inventory checklist, read-only inspection, supported hosted namespace fallback | Actual equipment owners and availability, NIC compatibility, booking, capture tooling, and reviewed permission/inventory |
| #4 | Four checked primary references, related-work comparison, workload rationale, deliverable checklist | Official rubric and dates, followed by the required second-reader check |
| #6 | Executable profiles, recorded queue snapshots, positive traffic counters, fresh-topology reset | Effective shaping equivalence, packet/counter cross-checks, and verification of the accepted bounded-priority rule |
| #9 | Explicit lifecycle, source/configuration provenance, saved randomized schedule, real trials for every policy | Integrated matrix execution and replacement tracking, exact window alignment, and final primary-run evidence collection |
| #11 | Six preserved local diagnostics, reproducible figure, Linux lifecycle checks, documented no-go | Calibrated cross-policy pilot, repeated full-duration measurements, independent packet/data review, and a team readiness decision |

## Verification evidence

At revision 21b069ae2b0f3c9a8689d31afc4f45627b904e72, the
[manual Linux run](https://github.com/srgangaram-swe/networks_project/actions/runs/40630299245)
passed 84 unit tests, 42 ordinary integration tests, and all five privileged
Linux tests. The latter exercised four queue profiles plus failure recovery,
bidirectional path checks, and above-capacity demand. The ordinary check group
explicitly skips privileged tests; the separate manual job actually ran them.
Branch coverage was 476/520, or 91.54%, above the unchanged 90% floor.

The same 84 unit and 42 integration tests passed on macOS. Formatting, Ruff
with maximum McCabe complexity 10, repository hygiene, and ShellCheck passed.
The [fixture instructions](../tests/fixtures/README.md),
[operating guide](running-experiments.md), and
[pilot report](pilot-readiness.md) provide reproduction commands and limits.
