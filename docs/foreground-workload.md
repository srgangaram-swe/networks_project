# Foreground workload

Issue #7 provides a UDP client and echo responder for the proposed measurement
contract in [MR #24](https://github.com/srgangaram-swe/networks_project/pull/24).
The protocol still needs team approval. This component can be tested on
loopback; it does not set up a bottleneck, generate bulk TCP traffic, or validate
the full experiment.

## Why this design?

A request generator that waits for each reply reduces its own load when the
network slows down. That would change the experiment precisely when queues
grow. Here, requests follow a fixed schedule regardless of replies. If the
client cannot send a scheduled request, it records that slot as not sent.
It never replaces the missed slot with a later request or a catch-up burst.

UDP exposes application deadline misses without TCP retransmissions hiding the
underlying arrival pattern. It also means a timeout does not identify where a
packet was lost, or even prove packet loss: a delayed reply can miss the same
deadline. This workload measures small synthetic control messages, not a
reliable RPC implementation.

## Wire format and timing

Every request and reply is exactly 512 bytes of UDP payload. The first 24 bytes
contain NQL1, version 1, an unsigned 64-bit request ID, and an unsigned 64-bit
scheduled timestamp, in network byte order. The remaining 488 bytes repeat
byte values 0 through 255. The responder echoes the entire validated message.
The client checks the source address and port, header, request ID, scheduled
timestamp, and padding before accepting a reply.

The primary settings are 10 seconds of warmup, 60 seconds of measurement,
and 2 seconds of drain, at 500 requests per second. IDs continue across warmup
and measurement. That produces 5,000 warmup records and 30,000 measurement
records, with one scheduled request every 2 ms. Warmup membership follows the
request's scheduled slot even if its reply arrives during measurement.

All client timestamps come from the same monotonic nanosecond clock. Send time
is sampled immediately after a successful nonblocking sendto call. Receive
time is sampled immediately after recvfrom, before parsing. Application RTT is
receive time minus send time; scheduled completion time also includes generator
delay. These timestamps include application and kernel scheduling costs. They
are not hardware timestamps or synchronized one-way measurements. See the
[Python clock documentation](https://docs.python.org/3.12/library/time.html#time.monotonic_ns)
and [socket documentation](https://docs.python.org/3.12/library/socket.html#socket.socket.recvfrom).

| Condition | Recorded behavior |
|---|---|
| A slot is more than 1 ms late | Do not send; record generator_late |
| Send would block | Do not retry; record send_would_block |
| In-flight limit reached | Do not send; record in_flight_limit |
| No valid reply within 1 second of send completion | Keep the deadline miss; release the in-flight slot after the inclusive deadline |
| First valid reply arrives after that deadline | Retain its timestamp and classify the record as late |
| Another valid reply arrives for the same request | Count duplicate_reply without replacing the first timestamp |
| Malformed, changed, stale, or unexpected reply | Count the corresponding event; do not accept it as a response |
| Cancellation or socket failure | Keep all planned slots, mark the run incomplete, and close the socket |

For deadline-miss rates, both late and timeout records belong in the numerator.
Not-sent records are a separate generator-failure category. Do not infer packet
loss from either count. A cancelled run can contain unexpired requests; the
incomplete_deadlines field identifies that case. Its outcome counts are
diagnostic and must not be used as completed-run statistics.

## Run locally

From the repository root, create an output directory:

    mkdir -p runs

Start the responder in one terminal:

    .venv/bin/python scripts/foreground.py responder

It prints a readiness message after binding to 127.0.0.1:42000. In another
terminal, run a short smoke test:

    .venv/bin/python scripts/foreground.py client --warmup-ms 0 --measurement-ms 1000 --output runs/foreground-smoke.json

For the primary foreground schedule, omit the two duration overrides and
choose a new output filename. The responder runs for 90 seconds by default;
start the client soon after the readiness message. This tests the foreground
component only. Loopback observations are not queue-policy results.

The client binds port 42001 by default. Port 0 explicitly requests an ephemeral
client port for local tests; occupied explicit ports fail without fallback.
The responder CLI requires a nonzero port. Stop either process with Ctrl-C.
The client saves partial evidence on SIGINT or SIGTERM and exits with code 130.
Socket errors exit with code 2. Code 0 means collection finished, not that a
run passed scientific validity checks.

The output file is published only after its JSON is complete, using a hard link
that refuses to replace an existing destination. Choose a local filesystem
that supports hard links. The CLI does not create parent directories. Raw
output belongs under the ignored runs directory.

## Bounds and safety

Default traffic stays on loopback. Private IPv4 testbed addresses require
--allow-isolated on both endpoints; public, multicast, wildcard, and DNS-name
targets are rejected. This flag acknowledges permission already obtained from
the equipment owner. It cannot establish isolation or ownership by itself.
The responder accepts only the configured peer address, but that check is not
authentication and does not protect against spoofing on a hostile network.

Workload limits are 500 requests per second, 60 seconds of warmup, 120 seconds
of measurement, 10 seconds of drain, and 1,024 in-flight requests. At most
90,000 request records and 4,096 detailed events are retained. Event counts
continue after the detailed log fills; a nonzero events_dropped value makes
the evidence incomplete. The responder has a 200-second maximum lifetime and
a 1,000-packet/s validation budget with a 32-packet burst. Excess packets are
counted and not echoed. It never amplifies a request into a larger reply.

The client handles at most 32 received datagrams before revisiting scheduling
and cancellation. Waits are capped at 50 ms, and at 0.5 ms when a send deadline
is within 5 ms. Short waits reduce timer coalescing without busy spinning;
the operating system can still delay the process. Runtime and cancellation
bounds are cooperative, not real-time guarantees under process suspension.

## Overhead and remaining validation

Client process CPU time covers collection, including warmup and drain, but
excludes final record assembly and JSON publication. It is process-wide, so
use a separate client process when measuring it. It is not router CPU usage.
For each sent request, sent_ns minus scheduled_ns exposes pacing delay.
The output also records the clock's reported resolution.

Before primary collection, the pilot must check these costs on the chosen
Linux system at 500 requests per second, with the real responder and bulk
load. Compare unloaded and loaded scheduling delays, inspect responder drops,
and retain the configured durations and all event counts. A successful run
with fewer than the planned requests sent is not sufficient. Completed status,
zero incomplete deadlines, and a complete event log are necessary but do not
replace the full run validator in issue #10.

The trial runner attaches source hashes, topology snapshots, tool versions,
configuration, and phase boundaries. Exact alignment with the iperf3 receiver
window remains in issue #9. This JSON file is a component capture; see the
[bundle format](bundle-format.md) for the enclosing experimental record.

## Tests

Run the ordinary repository checks:

    sh scripts/check.sh

Unit tests cover framing, deterministic round trips, scheduling stalls,
deadline boundaries, in-flight expiry, phase membership, event limits, and
backpressure. Real loopback tests cover echoing, bad replies, wrong peers,
duplicates, dropped and late replies, cancellation, and exclusive output
publication. Injected socket failures check partial sends and cleanup.
The tests require no elevated privileges and make no external connections.
