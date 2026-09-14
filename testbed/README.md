# Linux testbed

Setup and reset automation belongs here. The implementation is a scheduled work
item, not part of the initial repository setup.

Keep inspect, apply, verify, and cleanup operations separate. Use only owned
namespaces or explicitly approved interfaces. Record the qdisc hierarchy and
counters after applying a configuration. A successful command alone does not
prove that traffic crosses the intended bottleneck.

See docs/security.md before running privileged commands.
