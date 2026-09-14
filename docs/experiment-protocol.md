# Experiment protocol

Status: planning baseline transcribed from the team's September 10 proposal.
Freeze the unresolved choices in the architecture issue before collecting
primary evidence. Changing the frozen protocol requires a decision record.

## Research question and treatments

How does Linux queue management affect foreground tail latency and background
goodput when small request-response messages share a bottleneck with bulk TCP?

Compare FIFO, FQ-CoDel, CAKE best-effort, and CAKE with bounded traffic
classification. Use a three-node client-router-server topology. The primary
bottleneck is 100 Mb/s with 20 ms base RTT. A single Linux host with network
namespaces is the fallback; label such results as virtual testbed measurements.

## Primary workload

- Foreground: 512-byte messages, 500 requests per second.
- Background: aggregate pacing targets of 50%, 90%, and 110% of the shaped rate.
- Competing TCP flows: one or eight, with the aggregate target split across flows.
- Repetitions: ten independent 60-second measurement runs per condition.
- Ordering: randomized policy order within recorded blocks, with an explicit seed.
- Baselines: ten unloaded runs per policy at matching link and workload settings.

The loaded matrix has 4 policies x 3 load targets x 2 flow counts x 10 runs,
or 240 runs. Forty unloaded baseline runs bring the primary plan to 280 runs.
At 60 seconds each, that is at least 4 hours 40 minutes of measurement, excluding
warmup, reset, validation, and retries. Schedule testbed time accordingly.

A 110% pacing target is offered demand, not a claim that TCP delivers more than
the link capacity. Record requested load, achieved goodput, queue statistics,
and evidence that the intended link is the bottleneck.

## Measurement and analysis

Use a client-side monotonic clock for round-trip time. Record scheduled and
actual send times so a delayed generator does not silently omit slow requests.
Track request IDs, timeouts, late replies, duplicate replies, and malformed data.
Do not report a low latency percentile without the corresponding timeout rate.

Report p50, p95, p99, and p99.9 RTT; an explicitly defined jitter measure; loss
or timeout rate; bulk goodput; and router CPU use. Keep transport packet loss
distinct from application timeouts. Calculate per-run statistics, then use
runs as the replication unit for 95% bootstrap confidence intervals. Do not
treat every request within a run as an independent replication.

Added latency is loaded foreground p99 minus the corresponding unloaded p99.
The feasibility target under saturating load is at least a 50% reduction in this
added latency relative to FIFO while retaining at least 90% of FIFO bulk goodput.
Report absolute values and uncertainty too. If FIFO added latency is zero or
negative, do not divide by it or present a misleading percentage.

At 500 requests per second, a 60-second run schedules 30,000 requests.
The highest percentiles depend on relatively few observations and are secondary
to the main p99 comparison. Report their uncertainty and all validity exclusions.

## Decisions to freeze before the pilot

- Foreground transport, framing, response size, timeout, warmup, and drain period.
- Open-loop pacing implementation, maximum in-flight requests, and overload behavior.
- Congestion-control algorithm, ECN settings, MTU, offloads, kernel, and tool versions.
- The queue hierarchy, FIFO limit, shaping overhead, direction of shaping, and delay placement.
- CAKE classification rules, priority budget, and a test that bulk traffic cannot claim priority.
- Definition of jitter, loss, achieved-load tolerances, and a valid versus invalid run.
- Randomized block design, baseline matching, confidence-interval estimator, and bootstrap seed.
- One-factor sensitivity values for link rate, base delay, and foreground message size.
- The grading rubric and official final deadlines, which are not supplied in the proposal.

Do not start the full matrix until the pilot acceptance criteria pass.
Invalid runs remain in the manifest with reasons. Targeted reruns are additional
records, never silent replacements for inconvenient observations.

## Budget and fallback

The proposal estimates $330: a dual-port 2.5-GbE Linux mini PC ($220), two USB-C
2.5-GbE adapters ($80 total), and three Cat6 cables ($30 total). Team computers,
compatibility, borrowing, funding, and prices still need confirmation. No
purchase is authorized by this plan.

Existing 1-GbE hardware can support the proposed 100 Mb/s bottleneck. A namespace
fallback can test queue behavior but cannot establish physical NIC performance.
