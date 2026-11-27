# RPC workload and real loopback collection

Chris Ong's RPC workload is available through the main experiment launcher.
Add --rpc-diagnostics to a loopback, namespace, physical Linux or MacBook run.
The trial runner calls src/basic_rpc_protocol/rpc_workload.py through the same
bounded process and topology adapters as the other workloads.

    sh scripts/run_pipeline.sh --topology loopback --transport udp \
      --rpc-diagnostics --output runs/loopback-rpc-01

Loopback collects real traffic on 127.0.0.1. It runs two blocks, each containing
an unloaded trial and a trial requesting 110 Mb/s of reverse TCP background
traffic. Each foreground measurement lasts ten seconds after two seconds of
warmup. The four trials retain 20,000 foreground slots. Optional RPC adds
another 20,000 scheduled calls. No queue policy or physical NIC is involved.

Local mode is different: it generates 48 simulated trials with 240,000 slots
and runs the statistical and model checks. RPC is real socket traffic and is
therefore rejected in local simulation mode.

## What an RPC phase measures

Each RPC phase follows the ordinary foreground measurement on the same
retained topology. Its TCP background transfer starts afresh, with the same
flow count and requested rate and no warmup. RPC lasts as long as the trial's
measurement, capped at 60 seconds. Enabling it adds that duration and setup
time to every trial, including unloaded baselines. The server has an additional
eight-second lifetime allowance and finishes before its SSH connection closes,
so the final counters reach the bundle. It can roughly double the
measurement time of the full matrix.

The default workload schedules 500 calls per second with 32 worker threads.
A CALL and its echo RESULT each contain a 30-byte header and 482-byte payload.
An ACK adds 30 bytes. Each activity permits one outstanding call, with a
250 ms retry interval, at most three retransmissions and a two-second total
deadline. An occupied worker pool omits a scheduled call instead of adding
unbounded work. Reports retain admitted, omitted and cancelled counts, start
lag, each admitted call's timestamps and outcome, and retransmission counts.

RPC uses UDP port 5300 and ephemeral client ports. The bounded foreground
classifier continues to select the original port pair, so RPC remains best
effort in that treatment. Its duration measures an application call, including
retries and local processing. It is separate from the foreground RTT metric.
The RPC phase has no claim of exact alignment with its background transfer.

The server caches the most recent reply for each activity. Duplicate requests
reuse that reply; acknowledgments release its payload while preserving sequence
history. State is bounded to 1,024 activities in the runner and is lost when the
server stops. This is not a durable exactly-once guarantee. The protocol has no
authentication or encryption and belongs only on the authorized isolated testbed.

## Evidence and analysis

Every completed trial with RPC contains manifest-bound rpc.json,
rpc-server.json and rpc-bulk.json. Loaded phases also retain rpc-bulk-raw.json.
The validator recomputes successful-call quantiles, failure rates and retry
totals from the retained calls and checks background receiver evidence.
Missing or inconsistent files prevent a completed bundle from being accepted.

The pipeline writes rpc-analysis/rpc-summary.csv, findings.txt and a PNG/SVG
figure pair. Its manifest records input and output hashes. Namespace runs keep
that directory under namespace/. Successful-call percentiles exclude failures,
which remain in the table alongside worker-capacity omissions. The descriptive
RPC report does not pool its observations with foreground RTT or infer queue
policy effects from the retry protocol.

Loopback runs also produce export/summary.csv, export/requests.csv and an
analysis directory with descriptive figures and findings. They do not run the
four-policy estimator or clustering against invented queue labels.

Keep the entire output directory, including failed attempts. Every launch needs
a fresh output name. Ctrl-C stops owned children and retains partial evidence.
An RPC error fails the trial without discarding the earlier foreground capture.

## Checks and limits

Portable tests cover packet bounds, malformed input, monotonic timestamps,
sequence exhaustion, duplicate suppression, retry exhaustion, worker capacity,
real UDP calls, loaded and unloaded trial integration, and retained accounting.
A regression checks that an old duplicate RESULT cannot complete a newer call.
The optional Linux suite adds delay, dropped CALLs, dropped RESULTs and a
persistent blackhole. The SSH/veth stand-in exercises RPC through all four
policies alongside both foreground transports.

For N calls and W workers, scheduling and accounting use O(N) storage and
O(N log N) time for latency sorting. At most W calls are active, with W capped
at 256 in the library and set to 32 in the runner. The library caps scheduled
calls at 100,000; a runner phase schedules at most 30,000. A server processes
at most 200,000 packets and retains at most 1,024 activity entries in the runner.
Full output, subprocess and artifact limits still apply.

## November 26 Mac check

The [reviewed loopback reference](../data/reference/mac-loopback-2026-11-26/README.md)
contains four clean-source trials. Of 20,000 foreground slots, 19,947 returned
on time and 53 were not sent; no timeout or late outcome occurred. All 20,000
separate RPC calls completed without retries or worker-capacity omissions.
RPC start lag still reached 12.855 ms. These are local execution checks, and
they do not settle pacing accuracy or physical queue performance.
