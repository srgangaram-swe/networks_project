# Equipment and local readiness

Related issue: #3. Physical equipment, funding, and booking remain unconfirmed
as of October 27, 2026. A disposable hosted Ubuntu runner supports the namespace
fallback and has executed all four queue profiles. The owner authorized those
isolated checks. The team has not supplied a physical Linux machine or interface
list. This is not a purchase request.

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
| Client endpoint | Not supplied | Approved isolated interface, NIC driver, MTU/offloads, Linux and tool versions | Unconfirmed |
| Router | Not supplied | Two isolated links, traffic-control support, CPU capacity, owner permission | Unconfirmed |
| Server endpoint | Not supplied | Approved isolated interface, NIC driver, MTU/offloads, Linux and tool versions | Unconfirmed |
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

The budget remains an estimate: $220 for a dual-port router, $80 for two
adapters, and $30 for cables, totaling $330. Funding and current prices are
unconfirmed. Existing 1-GbE equipment may suffice if verified; namespace
measurements cannot establish physical NIC performance.

## Tests and limits

Unit tests cover tool discovery, command failures, timeouts, missing tools,
and the unsupported-platform path. The integration test runs the actual CLI
and checks the JSON report. These tests validate the inspection code, not
Linux queue behavior. Separate privileged checks verified namespace setup,
routes, offloads, delay, all four queue attachments, traffic, interruption, and
cleanup in [the Linux acceptance run](https://github.com/srgangaram-swe/networks_project/actions/runs/40630299245).
The [namespace pilot instructions](namespace-pilot.md) add capacity and packet
checks. A physical NIC test and another teammate's inventory review remain open.
