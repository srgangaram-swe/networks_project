# Running the namespace pilot

The pilot exercises the four queue policies on a disposable Linux host. It
is a development experiment. Its results cannot authorize primary collection
or establish physical NIC performance.

Start from a clean checkout with the tools listed in README.md, including
tcpdump for the packet checks. Run the ordinary checks first. Then, on an
isolated Linux host where you may create project-owned namespaces:

    sudo env NETWORKS_RUN_PRIVILEGED=1 NETWORKS_EVIDENCE_DIR=.local/policy-checks \
      .venv/bin/python -m unittest discover -s tests/linux -v
    sudo .venv/bin/python scripts/campaign.py --config configs/pilot.json \
      --output .local/campaign --authorized-isolated-host
    sudo .venv/bin/python scripts/export_pilot.py .local/campaign \
      --output .local/pilot-export

The manual CI namespace job runs these steps on a disposable Ubuntu runner.
It retains the synthetic reference export and policy-check observations for
30 days. The ordinary MR checks do not run privileged experiments.

## Schedule and attempts

The fixed pilot has two randomized blocks, four policies, and an unloaded
and saturated single-flow case per policy: 16 trials. Each trial has 10 seconds
of foreground warmup, 10 seconds of measurement, and 2 seconds of drain.
The saturated case requests 110 Mb/s of TCP demand on the 100 Mb/s link.
The seed is 561. Baselines match policy and block. This is a short mechanics
pilot; two blocks cannot establish precise treatment effects.

The runner saves the complete configuration, source identity, seed, order,
and baseline mapping before starting traffic. Every attempt gets an exclusive
directory. A lock prevents two processes from advancing the same campaign.
Completed cells are never replaced. The runner stops on the first failed or
interrupted trial and retains its evidence.

Inspect the failure and its ownership journal before continuing. If cleanup
was interrupted, use the documented testbed cleanup command for that exact
journal. A remaining owned namespace prevents continuation. Once the cause is
understood, continue the same source revision explicitly:

    sudo .venv/bin/python scripts/campaign.py --output .local/campaign --resume \
      --replacement-reason 'Describe the observed failure and its resolution' \
      --authorized-isolated-host

A replacement points to the previous attempt and records the reason. The
previous observations and manifest digest stay in the ledger. Each cell has
at most three attempts. A source or schedule change requires a separate
campaign. The executable pilot is capped at 40 cells; the 280-cell primary
plan remains disabled pending protocol and pilot acceptance.

## Policy checks and predeclared tolerances

The capacity check sends 200 Mb/s of reverse UDP demand with 1,200-byte
payloads, one second of warmup, and eight measured seconds. It repeats twice
per policy. Receiver intervals must report 90 to 100 Mb/s of payload goodput,
and the largest difference among the eight runs must be below 3 Mb/s.
These broad diagnostic tolerances detect a wrong shaper or gross mismatch;
they are not confidence intervals or an equivalence test for the research
comparison. Packet headers explain why payload goodput is below 100 Mb/s.
Queue bytes must exceed measured payload bytes and saturated queues must
record drops. Propagation delay is checked separately in both directions.

The packet check sends unrelated UDP traffic with a forged EF mark, matching
foreground traffic below the priority budget, and matching traffic above it.
Received DS fields and an eight-packet tcpdump sample check the wire behavior.
Only the bounded policy may mark matching traffic EF. Other traffic must be
best effort, and excess matching traffic must return to best effort. EF bytes
must fit the 5 Mb/s token budget plus the declared 16 KiB burst and one packet
of boundary allowance. At least 90% of probe packets must arrive so a broken
receiver cannot make an empty observation pass. These tests do not establish
application identity: a process that can impersonate the allowed tuple can
consume the bounded budget.

## Interpreting observations

The exporter retains every completed attempt and lists failed attempts and
unexecuted schedule cells. Keep timeout and unsent-slot counts beside latency
percentiles. The CPU measurement covers the shared host, because a network
namespace has no independent CPU counter. The loaded iperf receiver window
still differs from the foreground measurement window. Do not interpret their
values as a precisely synchronized primary comparison.

Primary collection remains a no-go until those timing and attribution limits,
the final protocol, equipment or fallback booking, and independent team review
are resolved. A successful CI run establishes the mechanics it actually tests.

The traffic options follow the [iperf3 documentation](https://software.es.net/iperf/invoking.html).
The queue profiles follow the [CAKE manual](https://man7.org/linux/man-pages/man8/tc-cake.8.html)
and the [iproute2 policing interface](https://kernel.googlesource.com/pub/scm/linux/kernel/git/leon/iproute2/+/refs/tags/v4.9.0/man/man8/tc-police.8).

## Current verification result

The [first manual run](https://github.com/srgangaram-swe/networks_project/actions/runs/40634717534)
passed all seven privileged tests, including the capacity and packet checks.
Its 16-cell campaign stopped at the first attempted cell: the iperf receiver
intervals had a gap after warmup. A separate local run with ten seconds of
warmup reproduced inconsistent interval boundaries. The parser correctly
rejected that report, and its regression fixture remains rejected.

The collector now disables periodic reports with -i 0 while retaining warmup,
measurement duration, pacing, and stream count. It requires the final receiver
interval to agree with its declared duration and the end summary. Real local
one-flow and eight-flow regressions with ten seconds of warmup passed. See
[the reporting decision](decisions/0002-bulk-final-report.md) for the evidence
and limits. A new campaign is required because the source has changed.

The [retained policy observations](../data/reference/namespace-policy-checks/README.md)
include the earlier successful checks and identify that failed campaign.

## Complete hosted pilot, November 7, 2026

[Run 42433714699](https://github.com/srgangaram-swe/networks_project/actions/runs/42433714699)
passed at 3e27a2792df3ed180d2e7adac7c4181a4da1d915. The job exercised the
NucBox installer on Ubuntu 24.04, then passed 114 unit tests, 51 integration
tests, and all seven explicitly privileged Linux tests. Branch coverage in
the portable group was 92.79%. The ordinary group skipped privileged tests;
the separate Linux group actually ran them.

All 16 campaign attempts completed without replacement, and no planned cell
was left unattempted. The downloaded export has matching digests and source
revision, 16 run summaries, and 80,000 distinct measurement request rows. Those
rows reconcile to 76,973 on-time replies and 3,027 unsent slots, with no timeout
or late replies. The exported data and attempt ledger were checked locally,
and the complete pilot figure was rendered and visually inspected.

Each loaded condition has only two ten-second observations:

| Policy | Loaded on-time p99 RTT range (ms) | Bulk receiver goodput range (Mb/s) |
|---|---:|---:|
| FIFO | 39.104 to 39.208 | 93.552 to 93.617 |
| FQ-CoDel | 20.303 to 20.337 | 93.033 to 93.110 |
| CAKE best effort | 20.172 to 20.181 | 79.141 to 81.605 |
| CAKE bounded | 20.171 to 20.182 | 83.524 to 83.540 |

These are diagnostic observations, not accepted treatment-effect estimates.
In particular, lower CAKE TCP goodput must remain visible alongside latency;
it is not evidence that the goodput-retention target was met. The shared-host
generator missed 3.78% of measurement slots overall. Investigate calibration,
generator overhead, and measurement-window alignment on the actual testbed.
Do not tune policy parameters merely to obtain a favorable outcome.

The run used Python 3.12.16 and iperf 3.16; the local warmup regressions also
passed with iperf 3.22. This verifies two observed environments, not every
kernel or tool version. Physical NIC performance and NucBox readiness remain
unverified. Every bundle is still ineligible for primary collection.

The namespace-pilot-evidence artifact retains the export for 30 days. Download
it while available and redraw into a fresh path after installing the plotting
dependencies:

    gh run download 42433714699 --repo srgangaram-swe/networks_project \
      -n namespace-pilot-evidence -D runs/hosted-pilot-42433714699
    .venv/bin/python -m pip install -r requirements-plots.txt
    .venv/bin/python scripts/plot_pilot.py runs/hosted-pilot-42433714699/pilot \
      --output runs/hosted-pilot-42433714699.png

Archive observations locally before artifact expiration. A new execution is
an additional observation and will not reproduce identical timing values.
MR #32 remains a draft while measurement-window alignment, calibration, and
scientific acceptance remain unresolved.
