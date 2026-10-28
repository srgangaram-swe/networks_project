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
