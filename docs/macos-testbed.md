# NucBox router with two MacBooks

Use the first MacBook as client, the NucBox as Linux router,
and the second MacBook as server. Either the client Mac or the NucBox can launch
the pipeline. Each experiment link needs a wired Ethernet
adapter and cable. Keep Wi-Fi for management on all three machines. The NucBox
needs two dedicated Ethernet ports plus a separate management connection.
Adapter compatibility and actual interface names still need equipment checks.

If wired links are unavailable, run the namespace experiment on the NucBox.
It collects real traffic on a virtual Linux testbed. Local mode produces toy
simulation data and cannot substitute for hardware or namespace evidence.

## Prepare the computers once

Install the same tested dev commit on all three computers and keep their
working trees clean. On the NucBox, follow [first boot and SSH](nucbox-setup.md),
then run scripts/setup_nucbox.sh --install. On both Macs:

    brew install python@3.12 iperf3
    sh scripts/setup_environment.sh
    command -v iperf3

Use the returned absolute iperf3 path in the private profile. Apple Silicon
Homebrew commonly uses /opt/homebrew/bin/iperf3; Intel installations commonly
use /usr/local/bin/iperf3. SSH need not have Homebrew on its PATH.

Enable Remote Login on the server Mac for the account that owns its checkout.
Confirm its owner's permission and allow Python and iperf3 through the macOS
application firewall for this isolated experiment. Configure SSH aliases
experiment-router and experiment-server on the client Mac. Verify host keys
and test both aliases. The router helper needs noninteractive sudo. Mac
endpoint helpers run as the checkout owner without sudo. The pipeline does
not install credentials or weaken host-key checks.

Copy configs/macos-profile.example.json to .local/macos-profile.json. Replace
every repository path, alias, adapter name and iperf3 path with observed values.
Do not publish that profile. With this example, launch from the client Mac.
The trial coordinator always runs on that client and uses its monotonic clock.

To launch from the NucBox, use configs/macos-remote-profile.example.json instead.
Set all three roles to SSH aliases, including experiment-router for the NucBox
itself. The aliases, verified host keys and authentication must work from both
the NucBox and the client Mac. Enable Remote Login on both Macs. Do not mark the
router local: that profile also reaches the Mac client, where local means the
Mac. Preflight rejects this ambiguous arrangement. If the profile selects an
SSH configuration file, its absolute path must work on both coordinators.

Once the machines are prepared, launch the following on the NucBox. The NucBox
retains the retrieved bundles and runs analysis locally; the client also keeps
its original bundles under .local/physical-runs.

    sh scripts/run_pipeline.sh --topology macos --transport udp \
      --profile .local/macos-remote-profile.json --rpc-diagnostics \
      --authorized-isolated-host --output runs/macos-rpc-pilot-01

Keep the terminal session alive during collection, or use a persistent terminal
session on the NucBox. Keep both MacBooks awake and connected to power.

## Configure dedicated links

Identify adapters with networksetup -listallhardwareports on each Mac and
ip -brief link on Linux. Confirm each physical port by disconnecting only the
experiment cable. Never select a management/default-route interface.

| Host | Address | Peer route |
|---|---|---|
| Client Mac | 10.203.0.2/30 | 10.203.0.6 through 10.203.0.1 |
| NucBox, client side | Assigned in owned namespace | Cable to client |
| NucBox, server side | Assigned in owned namespace | Cable to server |
| Server Mac | 10.203.0.6/30 | 10.203.0.2 through 10.203.0.5 |

Configure each Mac's dedicated network service manually with subnet mask
255.255.255.252, MTU 1500 and no default router or DNS server. Keep Wi-Fi
connected. Add only the explicit peer host route. For example, after confirming
that en7 really is the dedicated adapter on that particular Mac:

    # Client Mac only
    sudo ifconfig en7 inet 10.203.0.2 netmask 255.255.255.252 up
    sudo route -n add -host 10.203.0.6 10.203.0.1
    # Server Mac only
    sudo ifconfig en7 inet 10.203.0.6 netmask 255.255.255.252 up
    sudo route -n add -host 10.203.0.2 10.203.0.5

These are setup examples, not interface discovery. A route-exists error needs
inspection with route -n get; do not replace an unrelated route. If the given
addresses overlap an existing network, stop and revise the protocol and code
together. Record the adapters' original settings before setup.

Leave the NucBox's experiment interfaces down, without addresses, routes,
bridge membership or custom queues. Its network manager must not configure
these ports automatically. The helper refuses nonblank interfaces, moves them
into a private router namespace for each trial, and restores their original
names, MTU and offload settings with both interfaces down afterwards.

Mac preflight checks the wired adapter, exact address and mask,
MTU, peer route, separate default route, source revision and iperf3. It rejects
configuration changes during collection. Carrier is checked before each workload,
after the router ports are up; a down router can make the initial link inactive.
The pipeline never changes macOS interfaces,
routes, firewalls or TCP sysctls.

## Check, then run

    sh scripts/run_pipeline.sh --topology macos --transport udp \
      --profile .local/macos-profile.json --plan
    sh scripts/run_pipeline.sh --topology macos --transport udp \
      --profile .local/macos-profile.json --preflight
    sh scripts/run_pipeline.sh --topology macos --transport udp \
      --profile .local/macos-profile.json --authorized-isolated-host \
      --output runs/macos-udp-pilot-01

The last command collects the 16-trial randomized pilot and then validates,
exports, analyzes and plots it. Read analysis/insights.txt, report.json and
the request-outcome plots. Keep the entire run directory. Every attempt needs
a new output name.

Use --transport tcp for a separate foreground TCP experiment. Linux TCP_INFO
and AF_PACKET counters are unavailable on macOS and remain absent. Optional
--shadow-forecast uses application events without observed ACK features and
never changes queue policies. Background TCP uses the Mac sender's native
congestion control; iperf3 does not receive the Linux-only selection option.

The mixed topology applies 20 ms of delay on router egress toward the server
and the queue treatment on egress toward the client. It is a separate testbed,
recorded as macos_testbed. Analysis refuses to pool it with other topologies.
See [the design decision](decisions/0003-macos-endpoints.md).

Check unloaded RTT, achieved load, queues, omissions and cleanup on the actual
equipment. Confirm the protocol with the team before the larger run. Add
--diagnostic-matrix for 280 trials, requiring at least 4 hours 40 minutes of
measurement plus warmup, setup and analysis. Both modes remain diagnostic:
exact bulk/foreground window alignment, router CPU measurement and hardware
calibration remain limitations. Mac endpoint CPU is not reported as router CPU.

## Interrupted runs

Ctrl-C stops the coordinator. Remote helpers handle SSH hangup and bound each
workload's lifetime. A disconnected host can retain a lease. Reconnect and
inspect collection/trial-NNN/remote-request.json and the role's
.local/physical-TOKEN-ROLE/lease.json. Run the helper's cleanup action with
the same role, token and item. Never delete ownership journals or kill by
process name. Mac cleanup waits for active workers and refuses a replaced
lease; Linux cleanup verifies namespace and process identities. Retain failed
output even after cleanup.

After all experiments, remove only the peer host routes you added and restore
the dedicated Mac network services from their recorded settings. The pipeline
leaves those operator-configured services intact.

Use [the deliverable update guide](../deliverables/README.md) after collection.
The current report and slides distinguish simulated examples from the earlier
namespace pilot and pending physical evidence.
