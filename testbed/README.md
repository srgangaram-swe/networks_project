# Linux testbed

The namespace adapter is implemented in src/topology.py,
src/topology_runtime.py, and src/queue_policy.py. The scripts/testbed.py entry
point separates read-only planning from setup, inspection, and cleanup.
It changes only namespaces it creates and records in its private ownership
journal. It does not configure physical interfaces.

Keep inspect, apply, verify, and cleanup operations separate. Use only owned
namespaces or explicitly approved interfaces. Record the qdisc hierarchy and
counters after applying a configuration. A successful command alone does not
prove that traffic crosses the intended bottleneck.

Read [the operating guide](../docs/running-experiments.md) and
[security rules](../docs/security.md) before running privileged commands.
All four profiles passed the manual namespace integration check on a disposable
Ubuntu runner. Calibration and verification on the experiment hardware remain
pending. The [readiness report](../docs/pilot-readiness.md) links the evidence.
