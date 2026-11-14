# TCP measurements and advisory forecasts

Select --transport udp or --transport tcp on scripts/run_pipeline.sh.
UDP remains the default candidate workload. TCP is a separate diagnostic
treatment; it does not silently change the frozen UDP proposal or its results.
The background workload is TCP in both cases.

## Framing and application timing

Both transports carry the same validated 512-byte application message.
TCP is a byte stream, so the reader assembles complete 512-byte frames across
fragmented reads and handles several frames in one read. TCP_NODELAY disables
Nagle's algorithm. This does not make one application message equal one TCP
segment. Retransmission and stream ordering can delay later responses.

The schedule, IDs, one-second deadline, in-flight bound and unsent accounting
match UDP. TCP send completion is the timestamp after the whole frame enters
the socket. A partial frame must complete within 100 ms; failure invalidates
the run because the stream cannot safely skip its remainder. A send that
would block before writing any bytes leaves that slot unsent.

RTT remains a client application round trip. Neither transport estimates
synchronized one-way packet arrival time.

## Socket and passive observations

foreground-transport.json records the foreground transport and event-stream
delivery counters. On Linux TCP it also retains before/after and roughly
one-second TCP_INFO samples: smoothed RTT and variation, congestion window,
unacknowledged segments, kernel loss state and total retransmissions.
The [Linux TCP structure](https://github.com/torvalds/linux/blob/master/include/uapi/linux/tcp.h)
defines their layout. Unsupported platforms report unavailable values.

TCP_INFO does not supply duplicate cumulative ACK counts. Linux namespace and
physical TCP trials therefore start a separate privileged observer on the
owned client's eth0. It reads at most 160 bytes per packet into a bounded
header parser and writes aggregate counters, never payload captures.
It follows both request and reverse bulk directions.

A duplicate-ACK candidate must acknowledge outstanding observed data, carry
no TCP payload or SYN/FIN/RST, repeat the previous cumulative ACK number, and
repeat the advertised window. These are the header conditions in
[RFC 5681, section 2](https://www.rfc-editor.org/rfc/rfc5681.html#section-2).
Repeated sequence candidates are counted separately. ACK and sequence counters
are split between the foreground port pair and bulk connections.

tcp-observer.json retains one-second processing-clock aggregates, flow counts,
kernel packet/drop statistics and quality status. Capture drops limit what
can be inferred. Duplicate ACKs can reflect reordering, and retransmissions
can be spurious. Neither counter is a ground-truth packet-loss rate.
Application duplicate replies are a different event again.

Summary CSVs export the socket retransmission delta, final congestion window
and smoothed RTT, foreground/bulk duplicate-ACK candidates and capture drops.
These counters cover the complete observed connection, including warmup and
drain, rather than claiming exact alignment with measurement-only quantiles.
Original JSON retains their timing and scope. UDP and legacy rows leave
unavailable transport values empty.

The observer has a two-million-packet, 64-flow, 191-window budget. An exceeded
budget fails collection. Its CPU cost and kernel capture drops must be checked
on the actual host before using it for primary measurements.

## Optional live shadow model

--shadow-forecast starts a separate client-side process. Foreground send,
reply and deadline events reach it through atomic, nonblocking FIFO writes.
The TCP observer also sends aggregate ACK features. A slow reader causes an
explicit dropped-event count instead of delaying traffic.

The model predicts on-time application p99 RTT and timeout fraction for the
next complete one-second send cohort. Features use a closed past window:
send/reply/deadline counts, observed arrival RTT, pending requests, duplicate
ACK candidates and availability indicators. Scaling uses fixed physical units.
No whole-run summary or future response enters the feature vector.

Two small recursive ridge models update only after the target cohort closes,
its request deadlines pass and all observed sends have settled. Predictions
remain unavailable until five labeled training windows exist. A cohort with
no sends, missing outcomes or no on-time RTT does not invent a target.
Every forecast retains its issue time, future target start, features,
training counts, prediction, settled outcome and advisory action.

shadow-forecast.json identifies incomplete streams and pending requests.
Compare predictions with later outcomes in temporal order; do not randomly
split packets from the same run into training and test sets. The ridge penalty,
five-window warmup and advisory thresholds are initial diagnostic choices,
not a validated control policy. No action changes queues or transmission.

This is an application timeout/round-trip forecast, not supervised contention
classification or packet-loss prediction. Those targets need independent
labels, larger campaigns and held-out hardware conditions. Closed-loop policy
changes would require a separate experiment and comparison against fixed
policies. The current observations provide inputs for that work.
