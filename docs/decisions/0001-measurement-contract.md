# 0001: Foreground measurement and testbed contract

Status: proposed for team review. Related issue: #2. Contract version: 1.
The constants and record validator are implemented; the workload, topology,
runner, and analysis are not. Acceptance of this decision, equipment checks,
and a successful pilot are required before primary collection.

## Workload and timing

Use IPv4 UDP for the foreground request-response workload and TCP CUBIC for
background traffic. UDP lets the experiment distinguish request timeouts
from TCP retransmission delays. This is a synthetic control-message workload,
not a model of reliable inference delivery. A TCP foreground comparison is
outside the primary matrix and would need its own decision.

Each request is one 512-byte UDP payload and the responder echoes the entire
payload without changing it. The first 24 bytes are a four-byte ASCII magic
value NQL1, a four-byte unsigned contract version, an eight-byte unsigned
request ID, and an eight-byte unsigned scheduled timestamp. All integer
fields use network byte order. The remainder is deterministic padding.
These 512 bytes include the header, not the IP or UDP headers. Validate the
source endpoint, length, version, ID, timestamp, and payload before accepting
a reply. Bind only to the configured isolated address, never all interfaces.

Use foreground UDP port 42000 and background TCP ports 5201 through 5208.
These are testbed-local defaults, not permission to contact other hosts.
Maintain one foreground socket per run and never reuse a request ID within
that run. Start IDs at zero for warmup and continue into measurement.
If a selected port is occupied, fail rather than silently choosing another.

Warm up for 10 seconds, measure for 60 seconds, then drain for 2 seconds.
Start the foreground and background workloads before warmup. Stop creating
requests and stop background senders at the measurement boundary. Retain
all measurement replies received during drain. Exclude warmup requests from
measurement summaries, even when their replies arrive during measurement.

The client schedules requests every 2 ms on its monotonic clock, independently
of response arrival. Retain both scheduled time and actual send completion
time. The latter is the timestamp immediately after a successful nonblocking
datagram send returns. Never reuse a missed slot or send a catch-up burst.
If a slot is over 1 ms late, the socket would block, or 1024 requests are
already outstanding, record a not-sent request and its reason. Continue
the schedule; do not wait for a reply to schedule the next request.

Timeout is 1 second after actual send completion. A valid reply exactly at
the deadline counts as on time. A later reply remains a timeout for the
deadline rate but retains its arrival timestamp. Expiration releases the
in-flight slot; keep enough request history to recognize late and duplicate
replies through drain. Each scheduled request has one final record. Extra
replies and parse failures go in a separate bounded event log with counts.

## Record and metric definitions

The v1 request JSON object has exactly five fields: schema_version,
request_id, scheduled_ns, sent_ns, and received_ns. Timestamps are integer
nanoseconds on the same client clock. A null sent_ns means not sent and
requires a null received_ns. A null received_ns with a valid send means no
valid reply arrived before collection ended. Event records explain not-sent
and malformed cases. Records belong to a run bundle, not a global ID space.

The collector should pass deserialized records through
RequestRecord.from_mapping in src/measurement_contract.py. The validator
rejects booleans, floats, invalid versions, extra fields, impossible clock
ordering, and timestamps that leave no room for the timeout. It validates
individual records; issue #10 must validate cross-record uniqueness, phase
membership, request counts, and event-log consistency.

- Application RTT is receive time minus actual send completion time. It
  includes responder processing and is not a pure network propagation time.
- Scheduled completion time is receive time minus scheduled time. Report
  this alongside RTT so generator delay cannot disappear from the analysis.
- Timeout rate is sent requests without an on-time reply divided by sent
  requests. Late replies count in the numerator. Report not-sent requests
  separately as a fraction of all scheduled requests. A zero denominator
  produces an unavailable metric, not zero.
- Main RTT quantiles use on-time valid replies, with the timeout rate shown
  beside them. Also report late-reply counts and their RTTs separately. If
  more than 1 percent of sent requests time out, the successful-reply p99
  cannot describe the full request population's p99. Flag that limitation.
- Use the nearest-rank quantile: sort n observations and select rank
  ceiling(p times n), counting from one. No interpolated request timestamps.
- Jitter is the median absolute difference between consecutive on-time RTTs
  in scheduled request-ID order. Use only adjacent IDs; do not bridge missing
  requests. Report the number of pairs. This is an application RTT statistic,
  not the one-way IP delay-variation metric in RFC 3393.
- Packet loss is not inferred from application timeouts. Report qdisc drops
  as counter differences; packet-loss rates require captures and a defined
  capture boundary, sequence matching, and capture-drop checks.
- Bulk goodput is eight times receiver application bytes during the exact
  60-second window, divided by 60 and 1,000,000, in Mb/s. Do not count TCP/IP
  headers or warmup bytes. Align receiver interval boundaries in the runner;
  do not proportionally split an interval that overlaps the boundary.
- Router CPU use is 100 times the change in user, nice, system, IRQ,
  softirq, and steal ticks divided by the change in total ticks. Include
  idle and iowait in total, but do not double-count guest ticks already in
  user/nice. Report iowait separately. On a namespace host this is shared
  host CPU use, not isolated router-process utilization.

See [RFC 3393](https://www.rfc-editor.org/rfc/rfc3393) for the distinction
between one-way packet delay variation and this experiment's RTT statistic.

## Topology and queue profiles

Keep three logical roles: client, router, and server. Requests travel from
client to server. Responses and all bulk TCP data travel from server to
client. Shape only router egress toward the client to 100 Mb/s. The reverse
path is unshaped. Each underlying link must exceed the shaped rate.

Apply fixed 10 ms delay at each endpoint's receive ingress through a dedicated
IFB and NetEm, with a 10,000-packet limit and no configured random loss,
duplication, or reordering. This gives 20 ms of configured round-trip delay,
plus serialization and processing. Keep delay emulation on the endpoint IFBs,
separate from the router policy's qdisc hierarchy. Any NetEm-limit drop
invalidates the run. Receiver
placement avoids the sender-side TCP Small Queues limitation documented in
the [NetEm manual](https://man7.org/linux/man-pages/man8/tc-netem.8.html).

Use MTU 1500, disable TSO, GSO, GRO, and LRO on the owned test interfaces,
and record requested and effective settings. Disable TCP ECN on endpoints
for this comparison. Verify CUBIC on each bulk socket, not merely as the
host default. Pin the actual kernel and tool versions in the reviewed
equipment inventory before pilot collection. An unsupported setting fails
setup rather than silently substituting a profile.

Candidate router-egress profiles:

| Policy | Hierarchy and parameters |
|---|---|
| FIFO | HTB root and one class, rate and ceil 100 Mb/s, burst and cburst 16 KiB, quantum 1514 bytes; bfifo leaf limited to 250,000 bytes |
| FQ-CoDel | Same HTB class; fq_codel leaf with limit 1024 packets, flows 1024, quantum 1514, target 5 ms, interval 100 ms, noecn, memory_limit 4 MiB |
| CAKE best effort | CAKE root with bandwidth 100 Mb/s, besteffort, flows, nonat, raw, rtt 20 ms, memlimit 4 MiB, no-ack-filter |
| CAKE bounded | Same CAKE root parameters except diffserv3; classify only the foreground flow into the Voice tin |

CAKE uses its own shaper; the first two profiles use HTB. This therefore
compares complete queue-management profiles, not schedulers under identical
shaping internals. The FIFO byte limit is one 100 Mb/s by 20 ms bandwidth-delay
product: 100,000,000 times 0.020 divided by 8 equals 250,000 bytes.
FQ-CoDel and CAKE memory bounds are safety bounds, not equivalent queue delay.
Verify effective settings and unloaded behavior in issue #6 before accepting
these profiles. Raw accounting omits Ethernet wire overhead in this primary
model; do not describe the configured rate as physical wire capacity.

At router ingress, clear endpoint-supplied DSCP. Only responses matching the
controlled foreground source, destination, protocol, and port may be marked
EF for the bounded profile. Police that eligible traffic to 5 Mb/s with a
16 KiB burst; reclassify excess to Best Effort rather than giving it priority.
Bulk traffic remains Best Effort even when it forges EF. This bounds priority
eligibility, not total foreground throughput. CAKE's own tin threshold is
not a hard bandwidth cap. Verify counter changes and forged-mark behavior
in issues #6 and #16 before calling the treatment bounded.

The [CAKE manual](https://man7.org/linux/man-pages/man8/tc-cake.8.html) describes
its shaper, isolation modes, and tin thresholds. The
[FQ-CoDel manual](https://man7.org/linux/man-pages/man8/tc-fq_codel.8.html)
documents its packet, memory, and timing parameters.

## Schedule, matching, and statistical unit

Keep configs/primary.json as the proposal's matrix, separate from this
candidate measurement contract. In each of ten repetition blocks, shuffle
the four policies with Python's random.Random seeded once with 561. For
each policy, shuffle seven conditions: one unloaded baseline and the six
load/flow combinations. Save the complete schedule before executing it,
with Python version and seed; the saved schedule is the reproduction input.

Reset workload processes and queue state between every run. Match each loaded
run to its policy's unloaded run from the same block. A failed run does not
silently disappear: record its failure, then schedule a separate replacement
with a new run ID and the original pairing identity. Define the replacement
rule before primary collection. Use the first valid attempt for a scheduled
cell, retain all attempts, and stop for review after two failed replacements.

For a given load/flow cell, compare matched policy and FIFO added p99 values
within each block. Report all ten block values and their arithmetic mean.
Use 10,000 bootstrap resamples of the ten complete paired blocks, with seed
562, and percentile endpoints at 2.5 and 97.5 percent. Resample whole blocks
across policies and conditions so reuse of an unloaded baseline is preserved.
Do not treat requests as independent replicates. Missing paired baselines
prevent that paired comparison until the scheduled cell is resolved.

The percent reduction is 100 times one minus mean policy added p99 divided
by mean FIFO added p99. Report it only when the denominator is positive and
alongside the absolute difference. Bootstrap replicates with nonpositive
denominators make the relative interval unavailable; do not discard those
replicates. The goodput ratio uses the corresponding mean policy and FIFO
goodputs, with the same positive-denominator rule. Small-sample uncertainty
and shared-baseline correlation remain limitations even with bootstrapping.

The proposal supplies the four treatments, matrix, 60-second windows, ten
repetitions, and the 50 percent latency / 90 percent goodput targets. It does
not supply the transport, timeout, warmup, queue bounds, or statistical
details chosen here. Those are reviewable design choices, not measured optima.

## Validity and example

Require verified topology and queue settings, complete provenance, exactly
30,000 measurement slots, no duplicate request IDs, no not-sent slots, and
no malformed or wrong-peer replies. Timeouts, legitimate late replies, and
policy drops are outcomes and do not invalidate a run by themselves. Record
duplicate replies without including them twice in statistics. Missing or
truncated event evidence invalidates the run rather than hiding events.

At 50 and 90 percent load, the pilot must show that the background generator
can supply its configured application pacing target. At 110 percent, require
continuously backlogged senders and evidence of the intended bottleneck,
not 110 Mb/s delivered goodput. Record per-flow pacing settings and achieved
rates in every run. Freeze numerical load-verification tolerances in the
pilot decision after instrument calibration, before primary collection.
They are not yet a tested capability of the codebase.

An example plan has block 1, FIFO, load fraction 0.9, eight flows, 100 Mb/s,
20 ms configured base RTT, 10-second warmup, 60-second measurement,
2-second drain, 512-byte request and reply, and 30,000 measurement requests.
Its aggregate background target is 90 Mb/s, or 11.25 Mb/s per flow. Across
280 runs, the nominal warmup/measurement/drain time is 20,160 seconds, or
5 hours 36 minutes, before setup, reset, and retries. This is a calculation,
not a completed experiment.

For request 7, scheduled at 1,000,000,000 ns, sent at 1,000,100,000 ns,
and received at 1,023,100,000 ns, RTT is 23 ms, scheduled completion is
23.1 ms, and send delay is 0.1 ms. The unit test checks these values. A
loaded p99 of 45 ms and matched baseline p99 of 23 ms would give 22 ms
added latency; these example values are not results.

## Downstream contracts and acceptance

Issue #5 owns isolated topology and cleanup; #6 owns the executable queue
profiles and counter evidence; #7 consumes the request-record contract;
#8 owns bulk pacing and interval measurements; #9 records schedules and
manifests; #10 validates complete bundles; #14 implements the estimators.
Each run manifest must identify contract version, source and configuration
hashes, schedule cell, baseline pairing, attempt, topology profile, tool
versions, phase boundaries, artifact hashes, and validity reasons. Issue #10
must turn this manifest contract into a strict validator before collection.

Alternative choices include a TCP foreground workload, a common external
shaper for all policies, and a closed-loop request generator. The proposed
choices keep deadline outcomes visible and use CAKE's native shaping, while
accepting the profile-level comparison and UDP-workload limitations.

Team review is still required. Kernel/tool version pins depend on issue #3;
calibrated validity tolerances depend on the pilot. Do not label this record
accepted or issue #2 complete until the review and remaining choices are
resolved. A change after acceptance needs a superseding decision and contract
version, with the affected data identified. No primary results exist yet.
