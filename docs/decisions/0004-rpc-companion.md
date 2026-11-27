# RPC as a separate diagnostic phase

Status: implemented for diagnostic collection. Issue #41.

Chris's branch provides a bounded RPC state machine, UDP connector, metrics
and concurrent workload. Its bookkeeping edits were based on an older trial
format. The current runner already has UDP/TCP foreground selection, checked
unloaded baselines, retained receiver reports and physical endpoint support.

We keep that experiment format and integrate the RPC workload as an optional
phase after each foreground measurement. The original contributor commits
remain in the merge history. The bookkeeping conflicts resolve to the current
format; they do not introduce SCTP into the accepted TCP-background experiment.
The original library entry point remains available.

Replacing the foreground client would change both the wire protocol and the
meaning of latency. RPC retries make a successful call's duration different
from the existing request RTT. Its ephemeral client ports also fall outside
the current bounded classifier. We therefore keep separate files, a separate
background transfer and separate descriptive analysis. The classifier stays
unchanged, and the documentation identifies RPC as best-effort traffic.

The integration reuses process deadlines, artifact hashes, isolated endpoint
checks, owned topology cleanup and physical retrieval. It adds regression tests
for stale duplicate replies and real loopback/namespace RPC behavior. Existing
bundles and schema-v1/v2 campaign plans remain readable. New campaign plans use
schema version 3 to record the RPC option explicitly.

Disabling --rpc-diagnostics restores the original trial sequence. Rolling back
the integration does not require deleting measurements or changing a host's
network configuration. Retain new RPC bundles with the reader version that
understands them.
