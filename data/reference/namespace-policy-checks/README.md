# Namespace queue observations

These 20 JSON records come from source 7ffb4fc and the
[manual Linux run](https://github.com/srgangaram-swe/networks_project/actions/runs/40634717534).
They contain synthetic traffic measurements on a disposable Ubuntu namespace
testbed. The seven privileged tests passed. The subsequent randomized pilot
failed on its first attempted cell because iperf reported inconsistent receiver
interval boundaries. No primary data was collected, and the workflow as a whole
failed. Keep that distinction when citing these records.

Eight capacity checks, two per policy, delivered 95.099 to 96.619 Mb/s of UDP
payload at 200 Mb/s offered demand. The observed range was 1.520 Mb/s, within
the predeclared 3 Mb/s diagnostic tolerance. This supports the candidate
shaping setup on this runner; it does not establish statistical equivalence
or physical NIC performance.

All twelve marking probes passed. For bounded CAKE, 500 matching low-rate
packets arrived with EF marks, while 500 unrelated packets with forged EF
marks arrived as best effort. The 5,000-packet overload probe delivered 1,157
EF packets and 3,843 best-effort packets, within the declared token budget.
Other profiles cleared incoming marks. Each record includes received DS-field
counts and an eight-packet tcpdump sample from the synthetic testbed.

Reproduce with the privileged policy tests in docs/namespace-pilot.md. The
first complete cross-policy pilot and its figure are still pending. Primary
collection remains a no-go, and no team review is implied by these checks.
