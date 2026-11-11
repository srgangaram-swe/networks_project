# Testbed and pilot work status

This table covers the ten work items in roadmap order, #2 through #11. Code
integration and scientific acceptance are separate. The earlier branches for
the protocol, course planning, and foreground workload were consolidated in
[MR #27](https://github.com/srgangaram-swe/networks_project/pull/27). Their original
commits are ancestors of dev. The superseded branches were removed after that
check; their history remains in dev.

The [acceptance audit](acceptance-audit.md) identifies four completed components:
#5, #7, #8, and #10. Their issue closures follow integration into dev. The other
six items retain unmet criteria; promoting this source does not complete them.

| Item | Implemented or preserved | Remaining acceptance evidence |
|---|---|---|
| #2: Protocol and contracts | Candidate transport, framing, timing, queue profiles, metric definitions, block design, strict request contract, and a versioned command snapshot checked before namespace setup | Scientific protocol acceptance, calibrated load tolerances, and final Linux version pins |
| #3: Equipment and access | Received mini PC, two adapters and two cables; bounded read-only hardware inspection; first-boot guide; four-policy unloaded namespace setup check | Linux setup and device checks on the received unit, two Linux endpoint computers, owner permission, booking, and inventory review |
| #4: Course requirements and related work | Four published references, comparison, workload rationale, and a requirements-to-evidence checklist | Official final rubric and dates, plus the second-reader source check |
| #5: Topology | Complete namespace implementation with real Linux checks for both routes and RTT directions, endpoint offloads, cancellation, partial setup rollback, repeated cleanup, and preservation of unrelated namespaces | Physical hardware inventory and experiment calibration remain in #3 and #11 |
| #6: Queue profiles | Four fixed candidate profiles, matched nominal rate, endpoint receive delay, DS-field sanitation, and bounded-priority filter plan; Linux attachment checks passed | Effective-setting and traffic/counter verification, rate calibration, and forged-mark tests |
| #7: Foreground workload | Paced UDP client and responder, complete slot accounting, bounded framing, deadlines, and real-socket regression tests | Closed after its implementation and tests reached dev; full-system pilot checks remain in #11 |
| #8: Bulk workload | Complete rate allocation, receiver parsing, bounded lifecycle, one/eight-flow integration, startup-failure rejection, and above-capacity Linux demand checks through the shaped queue | Full-duration calibrated collection remains in #11 |
| #9: Trial runner | Portable and namespace adapters, explicit phases, failure preservation, source/configuration hashes, CPU scope, queue snapshots, recorded randomized schedules, and a completed 16-trial Linux pilot with an attempt ledger | Exact bulk/foreground window alignment, primary matrix execution, and final primary-run evidence |
| #10: Bundle validation | Complete schema-v1 integrity validator with hash and semantic checks, receiver-duration cross-checks, complete labeled fixtures, and corrupt/incomplete CLI regressions | Primary eligibility stays disabled; future collector schema changes must update the validator with #9 |
| #11: Pilot readiness | Local diagnostic workflow, complete cross-policy Linux mechanics pilot, checked export and rendered figure, per-run summaries, and explicit refusal to admit diagnostic runs as primary evidence | Full-duration bottleneck and generator-overhead calibration, independent data review, and recorded scientific go/no-go decision |

On November 7, 2026, Saif reported that the mini PC, adapters, and two cables
had arrived. Linux has not been installed or configured by the team on the
newly unboxed unit. The two Linux endpoint computers are unavailable, and the
official final rubric remains unconfirmed. The single-host namespace path
can use the NucBox after Linux setup, with the Mac handling development.
Hosted Linux checks do not calibrate that hardware; repeat them on the unit
before collecting experiment data.

The [complete hosted pilot](namespace-pilot.md#complete-hosted-pilot-november-7-2026)
also exercised the Ubuntu installer and the final-receiver-report workaround
for iperf's warmup boundary. All 16 cells completed and exported. The retained
unsent slots and lower CAKE goodput remain reasons to investigate calibration;
successful execution is not acceptance of those performance characteristics.

## What the checks establish

Unit tests cover parsing, arithmetic, scheduling, state transitions, ownership,
and failure mapping. Integration tests use real UDP sockets, real TCP streams,
real child processes, CLI boundaries, cancellation, and atomic artifact
publication. Ordinary checks skip privileged Linux tests. The separate manual
Linux group passed on Ubuntu 24.04, exercising all four profiles, inspecting
attachment and observed delay, validating each bundle, and checking cleanup.
The [readiness report](pilot-readiness.md) links the run. Mocked failure tests
are supplemented by real namespace interruption and partial-setup checks. These
tests do not establish equivalent shaping or readiness on physical hardware.

The [local diagnostic report](pilot-readiness.md) records all selected
observations, including missed send slots. It is evidence that the development
workflow runs and preserves failure information. It is not evidence for any
queue policy's latency or goodput benefit.

## Before primary collection

Resolve the pending acceptance criteria in #2, #3, #6, #9, and #11. Verify the
actual bottleneck, both delay placements, CUBIC and ECN behavior, offloads,
receiver-window alignment, NetEm drops, generator overhead, and bounded-priority
behavior. Record every exclusion and the review decision. Until then, the
collector and validator report eligible_for_primary as false.
