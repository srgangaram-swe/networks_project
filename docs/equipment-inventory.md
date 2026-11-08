# Equipment and local readiness

Related issue: #3. On November 7, 2026, Saif reported receipt of a GMKtec NucBox,
two Monoprice Cat6 outdoor patch cables, and two 2.5 Gb/s USB Ethernet adapters.
The mini PC is believed to be the requested G9, but its model and delivered
configuration have not been verified. Linux has not been installed or configured
by the team. Two Linux endpoint computers are currently unavailable.

Use the [NucBox setup guide](nucbox-setup.md) for the single-host namespace
fallback, with the Mac handling development and control. A disposable hosted
Ubuntu runner has already exercised all four queue profiles, but those checks
do not verify the received hardware. No physical interface list, booking, or
independent inventory review has been supplied. This is not a purchase request.

## Run after cloning

Follow the Python environment instructions in README.md, then run
.venv/bin/python scripts/inspect_testbed.py from the checkout. The command
prints JSON to stdout and never creates namespaces, opens traffic sockets,
loads kernel modules, or changes interfaces. It does not request root.

On Linux it checks whether ip, tc, iperf3, tcpdump, and ethtool can execute
their version command, with a five-second timeout per tool. It discards the
command banners rather than publishing host-specific build paths. Missing,
failed, timed-out, and unavailable commands are reported separately. Exit
zero means inspection completed, not that the machine is ready. On macOS
and other systems it reports unsupported_platform and exits two without
running Linux commands. Development tests still work on macOS.

The report deliberately sets ready_for_experiment to false. A command being
installed does not prove that the running kernel supports a qdisc, that a
NIC is suitable, or that the team has permission to change the machine.
Version values and capability evidence must be reviewed separately below.

## Inventory to confirm with the team

| Candidate | Owner and availability | Required evidence | Current status |
|---|---|---|---|
| Client endpoint | No Linux endpoint currently available | Approved isolated interface, NIC driver, MTU/offloads, Linux and tool versions | Requires a team machine or loaner |
| Router / namespace host | NucBox received by Saif; model believed to be G9 | Confirm model, installed Linux, traffic-control support, CPU capacity, permission and booking | Unboxed; configuration and physical checks pending |
| Server endpoint | No Linux endpoint currently available | Approved isolated interface, NIC driver, MTU/offloads, Linux and tool versions | Requires a team machine or loaner |
| Development / control | Saif's Mac, available | Portable checks; local console or a separately configured connection to the NucBox | Does not provide the missing Linux endpoints |
| USB Ethernet adapters | Two 2.5 Gb/s adapters received by Saif | Exact delivered models, USB connection, Linux driver and negotiated link speed | Received, not yet tested |
| Cat6 cables | Two Monoprice outdoor patch cables received by Saif | Connector condition, length for intended placement and negotiated link speed | Two active links covered; third requested cable is only a spare |
| Single-host namespace fallback | Disposable GitHub-hosted Ubuntu runner; available for bounded manual checks | Owner-authorized project namespaces, veth, IFB, and all four qdiscs | Executed in the linked Linux acceptance run; no primary-run booking |

Record an owner-approved alias instead of serial numbers, MAC addresses,
private IP addresses, employer details, or credentials. Keep any access
instructions outside the public repository. Equipment ownership is not
permission to use someone else's machine or reconfigure a campus interface.

## Evidence needed before issue #3 closes

1. Record each owner's permission, availability window, and the exact isolated
   interfaces or project-owned namespaces approved for changes. Identify the
   management/default-route interface as prohibited.
2. Record Linux distribution, kernel, iproute2, iperf3, tcpdump, and ethtool
   versions. Record NIC model and driver without device identifiers. Check
   the running kernel for FQ-CoDel, CAKE, NetEm, HTB, and IFB support.
3. On an authorized isolated testbed, create disposable resources and verify
   each required qdisc can actually attach. Inspect effective settings and
   test cleanup after both normal completion and an interrupted setup. Do
   not use module files or installed commands as proof of working support.
4. Verify MTU and effective offloads on all test interfaces, and confirm that
   the physical links exceed the 100 Mb/s planned bottleneck. Record any
   unsupported setting for protocol review rather than replacing it silently.
5. Book enough time for at least 5 hours 36 minutes of nominal primary run
   phases plus pilot, setup, resets, review, and retries. Confirm the actual
   booking with its owner; this document does not reserve equipment.
6. Have another teammate review the redacted inventory and capability output.
   Link the review and evidence in issue #3 before marking it complete.

The original proposal budget remains a historical $330 estimate. The later
resource request estimated $341.64 before tax and shipping for a G9, two
adapters, and three cables. Neither figure is a paid invoice. Receipt of the
reported items does not establish final cost or reimbursement. An additional
software-router computer was a backup, not a fourth required active node.
Existing 1-GbE links can support the 100 Mb/s bottleneck if verified; namespace
measurements cannot establish physical NIC performance.

## New equipment checks

Run .venv/bin/python scripts/inspect_hardware.py on Linux for bounded tool
versions, module discovery, physical NIC driver/carrier/speed/MTU information,
and default-route flags. It never changes the machine and never declares it
ready. A failed route lookup leaves protection status unknown. Its local output
omits addresses, MACs, serial numbers, and full command banners; review interface
names and kernel information before sharing. The original inspect_testbed.py
command remains available for a minimal tool-presence report.

The separate nucbox_smoke.py entry point plans four unloaded namespace trials
on any development machine, and runs them only with explicit authorization on
Linux as root. It retains failures, validates each bundle, and uses existing
ownership-aware cleanup. It deliberately does not exercise bulk traffic or the
known long-warmup defect. See the setup guide for exact commands and limits.

## Tests and limits

Unit tests cover tool discovery, command failures, timeouts, missing tools,
and the unsupported-platform path. The integration test runs the actual CLI
and checks the JSON report. These tests validate the inspection code, not
Linux queue behavior. Separate privileged checks verified namespace setup,
routes, offloads, delay, all four queue attachments, traffic, interruption, and
cleanup in [the Linux acceptance run](https://github.com/srgangaram-swe/networks_project/actions/runs/40630299245).
The [namespace pilot instructions](namespace-pilot.md) add capacity and packet
checks. A physical NIC test and another teammate's inventory review remain open.
