# Run collection and analysis

The shell launcher selects a topology and foreground transport, creates a fresh
recorded run, and carries successful collection through checked export, analysis,
plots, and insights. It creates the pinned Python environment if .venv is missing.
Run it from the repository checkout. Python 3.12 or newer is required.

## Local software check on the Mac

    sh scripts/run_pipeline.sh --topology local --transport udp \
      --workers 4 --output runs/local-udp-01

The default is six blocks, 48 trials and 240,000 scheduled slots, three times
the 16-trial pilot volume. The pool starts at most eight processes; four is the
default on a machine with at least four logical CPUs. Seeded request tables are
identical across worker counts. Collection on a shared Linux testbed stays serial.

Local mode uses an explicit toy queue model to test data handling and analysis.
Its policy factors are assumptions, not measurements. Choosing TCP in local mode
labels a separate software-test dataset; the toy model does not simulate TCP
congestion control, sequence numbers, ACKs, or retransmissions. Unavailable TCP
counters stay empty. Live shadow forecasting requires real namespace or physical
traffic and is rejected in local mode.

## NucBox with one Linux host

Set up Ubuntu and SSH using the [device guide](nucbox-setup.md). This route
works without the two separate Linux endpoints or Ethernet adapters.

    sh scripts/setup_nucbox.sh --plan
    sh scripts/setup_nucbox.sh --install
    sh scripts/run_pipeline.sh --topology namespace --transport tcp --plan
    mkdir -p runs
    sudo -v
    sh scripts/run_pipeline.sh --topology namespace --transport tcp \
      --shadow-forecast --authorized-isolated-host --output runs/nucbox-tcp-01

The launcher uses cached sudo authorization for this explicitly selected Linux
topology. It never prompts from a background process. Run sudo -v again if that
authorization expires. The output is root-owned.

Use --transport udp for the candidate UDP workload. The transport option
changes the foreground client, responder, and bounded CAKE classification.
Background traffic remains reverse TCP iperf3 in both modes. Run each transport
into its own output directory. The analysis rejects mixed foreground transports,
source versions, testbed kinds, and campaign designs.

The default campaign has 16 trials with ten seconds each of warmup and
measurement. Add --diagnostic-matrix to plan or run 280 trials with ten blocks
and 60 measured seconds per trial. Allow several hours. Both plans remain
diagnostic until the protocol, calibration and timing checks are accepted.

## Separate physical Linux endpoints

Use the [profile example](../configs/physical-profile.example.json) as a template
for a private profile under .local. Install the same tested source revision,
Python environment, iproute2, iperf3, ethtool and sudo on every Linux host.
Client, router and server may be reached through preconfigured SSH aliases.
Those aliases must work from the controller and from the client, since the
client coordinates every trial using its own monotonic clock.

SSH requires verified host keys, noninteractive authentication and noninteractive
sudo for the configured trusted helpers. Configure these on the isolated
testbed before running. The launcher does not distribute credentials, change
SSH access rules, install remotely, or accept unknown host keys.

    sh scripts/run_pipeline.sh --topology physical --transport tcp \
      --profile .local/physical-profile.json --plan
    sh scripts/run_pipeline.sh --topology physical --transport tcp \
      --profile .local/physical-profile.json --shadow-forecast \
      --authorized-isolated-host --output runs/physical-tcp-01

Preflight checks source identity and all dedicated interfaces before mutation.
An interface must be Ethernet, down, address-free, unenslaved, absent from all
IPv4/IPv6 routes, and have only kernel-default queues. Never select a management
interface. Different SSH aliases cannot assign the same actual interface twice.

The backend moves only those dedicated NICs into owned per-role namespaces.
It applies the shared routes, delay, offload and queue plan, then restores the
original names, MTU and offload settings with the interfaces down. It does not
flush host routes or firewall rules. Namespace identities, interface MACs, and
worker PID/start identities guard cleanup. A replaced resource, live worker,
connection failure or ambiguous NIC leaves evidence for inspection.

Remote bundles remain on the client under .local/physical-runs. The controller
retrieves only documented manifest-bound artifacts, validates their hashes,
source and treatment, then exports them. If a connection fails, inspect the
retained remote request and journals before retrying. Do not delete a journal
or namespace by prefix. The root helper's cleanup action accepts the retained
role, token and profile request and refuses resources it cannot identify.

The hosted physical check uses owned veth interfaces and private loopback SSH
on one disposable Linux kernel. Actual multi-machine SSH, NIC/USB behavior and
NucBox acceptance still require the configured equipment.

## Files, logs and failures

Local and physical output contains plan.json, status.json, events.jsonl,
timings.json, collection/, export/ and analysis/. Local runs also retain
worker-timings.json with per-trial wall and worker CPU time. Namespace runs
retain their setup, campaign, export and analysis under namespace/. Pipeline
events and stage timings remain at the top level.

The terminal reports stage and physical-trial progress. JSONL events have a
4 KiB record limit and a 4,096-event budget. Stage wall time uses a monotonic
clock; process CPU time belongs to the coordinator. Worker CPU is reported
separately and is not elapsed speedup or router utilization.

Completed analysis includes policy comparisons, request accounting, cluster
assignments, PCA/t-SNE views, Ward agglomerative and DBSCAN views, internal
cluster diagnostics, Ridge/Lasso held-out predictions and coefficients, stage
timing plots, and insights.txt. DBSCAN noise stays in the results. Ridge/Lasso
require at least six independent blocks; smaller inputs get an explicit
unavailable result and explanatory figures.

Ctrl-C or SIGTERM stops owned processes, joins workers and retains partial
evidence. Local simulation has a 120-second deadline. A fresh destination is
required; failed output is never overwritten. Fix the reported cause and use
a new destination. Namespace campaign recovery with an explicit replacement
reason remains available through the [campaign commands](namespace-pilot.md).

## Transport evidence and shadow forecasts

See [TCP measurements](tcp-measurements.md) for framing, ACK definitions,
counter scope, future-window predictions and their limits. Shadow forecasts
are advisory. They never change the fixed policy, pacing or offered load.
