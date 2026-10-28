# Testbed and pilot work status

This table covers the ten work items in roadmap order, #2 through #11. Code
integration and scientific acceptance are separate. The earlier branches for
the protocol, course planning, and foreground workload were consolidated in
[MR #27](https://github.com/srgangaram-swe/networks_project/pull/27). Their original
commits are ancestors of dev. The superseded branches were removed after that
check; their history remains in dev.

| Item | Implemented or preserved | Remaining acceptance evidence |
|---|---|---|
| #2: Protocol and contracts | Candidate transport, framing, timing, queue profiles, metric definitions, block design, and strict request contract | Scientific protocol acceptance, calibrated load tolerances, and final Linux version pins |
| #3: Equipment and access | Read-only inventory command, Linux prerequisites, isolated namespace fallback, and hardware handoff procedure | Equipment arrival, owner permission, NIC and kernel checks, booking, and inventory review |
| #4: Course requirements and related work | Four published references, comparison, workload rationale, and a requirements-to-evidence checklist | Official final rubric and dates, plus the second-reader source check |
| #5: Topology | Namespace-only plans, private ownership journal, inode checks, rollback after partial setup, inspection, and idempotent cleanup | Execution on the authorized Linux host and independent route/offload inspection |
| #6: Queue profiles | Four fixed candidate profiles, matched nominal rate, endpoint receive delay, DS-field sanitation, and bounded-priority filter plan | Linux attachment and effective-setting checks, traffic/counter verification, rate calibration, and forged-mark tests |
| #7: Foreground workload | Paced UDP client and responder, complete slot accounting, bounded framing, deadlines, and real-socket regression tests | Closed after its implementation and tests reached dev; full-system pilot checks remain in #11 |
| #8: Bulk workload | One/eight reverse TCP streams, exact aggregate rate allocation, checked receiver reports, bounded child lifetime, and real loopback integration | Intended-bottleneck and above-capacity demand evidence on Linux |
| #9: Trial runner | Portable and namespace adapters, explicit phases, failure preservation, source/configuration hashes, CPU scope, queue snapshots, and saved randomized schedules | Exact bulk/foreground window alignment, primary matrix execution, replacement reconciliation, and Linux lifecycle evidence |
| #10: Bundle validation | Independent schema, hash, timestamp, event/count, phase, load, flow-set, and topology-mode checks with corruption tests | Acceptance of the final primary-run schema after #2 and #9 are settled |
| #11: Pilot readiness | Local diagnostic workflow, per-run summaries, reproducible plots, and an explicit refusal to admit diagnostic runs as primary evidence | Cross-policy Linux pilot, bottleneck and overhead calibration, cleanup inspection, and recorded scientific go/no-go decision |

No approved Linux testbed or official final rubric was available on October 27,
2026. The code merge does not fill those gaps. The hardware is expected later;
the same checkout can run the namespace workflow once Linux prerequisites and
permission are in place.

## What the checks establish

Unit tests cover parsing, arithmetic, scheduling, state transitions, ownership,
and failure mapping. Integration tests use real UDP sockets, real TCP streams,
real child processes, CLI boundaries, cancellation, and atomic artifact
publication. Linux tests are a separate explicit group and remain unrun here.
Mocked Linux commands test the adapter's decisions; they do not validate kernel
behavior.

The local diagnostic report records all selected observations, including missed
send slots. It is evidence that the development workflow runs and preserves
failure information. It is not evidence for any queue policy's latency or
goodput benefit.

## Before primary collection

Resolve the pending acceptance criteria in #2, #3, #6, #9, and #11. Verify the
actual bottleneck, both delay placements, CUBIC and ECN behavior, offloads,
receiver-window alignment, NetEm drops, generator overhead, and bounded-priority
behavior. Record every exclusion and the review decision. Until then, the
collector and validator report eligible_for_primary as false.
