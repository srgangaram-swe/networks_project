# macOS endpoints with a Linux router

The available endpoint computers run macOS. We keep Linux queue treatments on
the NucBox and run portable traffic programs on explicitly configured Mac
Ethernet links. The Mac helper checks network configuration without changing
it. An exclusive trial lease and shared worker locks protect collection and
cleanup. Commands have deadlines and output limits. Lost connections retain
requests and leases. The router retains its existing ownership safeguards.

The mixed topology puts 20 ms of NetEm delay on router egress toward the server.
The 100 Mb/s bottleneck and queue policy remain on egress toward the client.
The Linux-only candidate instead puts 10 ms on each endpoint's ingress.
Moving delay changes where TCP sees queues, so macos_testbed is a separate
experiment. Unloaded measurements must confirm actual RTT. Its results must
not be pooled with namespace or all-Linux physical measurements.

macOS uses native background TCP behavior. Linux socket and packet counters
are unavailable; endpoint CPU cannot substitute for router CPU. Shadow
forecasts use application events only. All results remain diagnostic until
the team accepts calibration, protocol choices and workload-window alignment.

The all-Linux topology retains the original instrumentation but requires two
unavailable endpoints. A NucBox namespace test remains the fallback. Local
simulation tests software and supplies no physical networking evidence.
