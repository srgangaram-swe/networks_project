# Diagnostic topology and foreground transport selection

Status: implemented for diagnostics. Primary protocol acceptance remains pending.
Work item: #37.

The launcher selects local toy simulation, Linux namespaces, or dedicated physical
Linux roles. Every run retains its topology, source, schedule and foreground
transport. UDP remains the candidate default in decision 0001. Selecting TCP
creates a separate treatment with the same 512-byte application frame, fixed
schedule and request deadline, explicit stream framing and TCP_NODELAY.

TCP socket counters and passive ACK candidates are separate evidence. TCP_INFO
does not provide duplicate cumulative ACK counts. The passive parser observes
both foreground and reverse bulk directions, retains capture quality, and never
turns retransmissions, duplicate ACKs or application timeouts into a packet-loss
label. The original UDP reference remains immutable.

An optional shadow process predicts future application outcomes using past
windows and delayed labels. It does not alter the fixed queue treatment or
send schedule. Nonblocking events and drop counters separate model throughput
from traffic pacing. A slow or failed observer remains visible in the evidence.

The physical path reuses the reviewed namespace command plan inside owned
per-host namespaces. It moves only blank dedicated interfaces, records their
original state and returns them on cleanup. Verified SSH host keys, matching
source and explicit isolation are required before mutation. The one-host
namespace path is available while separate Linux endpoints are unavailable.

Keeping UDP alone would preserve the smallest collector but omit the requested
TCP observations. Inferring duplicate ACKs from TCP_INFO retransmissions would
mislabel different events. Immediate model-driven queue changes would confound
the current policy comparison, so control remains advisory.

Portable tests cover framing, counters, delayed labels, ownership and failures.
The explicit hosted physical check uses disposable veth links and loopback SSH;
it cannot substitute for actual NICs or several physical hosts. Inspect observer
cost, generator omissions, timing and calibration on the NucBox before primary
collection. See [the run guide](../topology-pipeline.md) and
[TCP evidence definitions](../tcp-measurements.md).
