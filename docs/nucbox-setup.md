# NucBox setup with the available equipment

Related work items: #2 and #3. Updated November 7, 2026.

Saif has received a GMKtec NucBox, two Monoprice Cat6 outdoor patch cables,
and two 2.5 Gb/s USB Ethernet adapters. The mini PC is believed to be the G9;
check its label before treating the requested model as the delivered model.
It has just been unboxed and Linux has not been installed or configured by
the team. The two separate Linux endpoint computers are not available yet.

Use the Mac for editing, reviewing plans, and controlling the NucBox. Use the
NucBox as one Linux host containing separate client, router, and server network
namespaces. That runs the existing queue-management code with the equipment
available now. It measures a virtual testbed with shared CPU resources, not
the performance of either Ethernet adapter or cable.

## First boot and Linux preparation

1. Check the mini PC model, supplied power adapter, and storage configuration.
   Use a local keyboard and display for first boot, or an already configured
   management connection. These are setup aids, not extra experiment nodes.
2. Inspect any preinstalled operating system before changing storage. The
   [manufacturer's G9 page](https://www.gmktec.com/products/intel-twin-lake-n150-dual-system-4-bay-nas-mini-pc-nucbox-g9)
   lists dual 2.5 Gb/s Ethernet and Windows plus Ubuntu, but that does not
   establish this unit's exact model, installed release, or driver support.
3. The repository's tested Linux baseline is Ubuntu 24.04 LTS with Python
   3.12 or newer. If installing Linux, follow the
   [Ubuntu installation guide](https://ubuntu.com/tutorials/install-ubuntu-server)
   and review the disk selection before confirming it. Installation requires
   boot media, commonly a USB flash drive. Nothing in this repository installs
   an operating system, repartitions storage, or changes firmware.
4. Verify the installed release with cat /etc/os-release and the kernel with
   uname -r. Check the [Ubuntu support dates](https://ubuntu.com/about/release-cycle).
   A factory installation is not proof that a release is still supported.
5. On Ubuntu, install the development and network tools below. Keep any
   management connection separate from the eventual physical experiment links.
   Local console use is sufficient for the namespace setup.

    sudo apt-get update
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
      git python3-venv iproute2 iperf3 ethtool iputils-ping tcpdump kmod shellcheck

If a required qdisc or IFB is unavailable, inspect the running kernel's module
packages and distribution documentation before proceeding. Some Ubuntu kernel
variants put additional modules in linux-modules-extra for that exact kernel.
Do not assume that a successful package install or modinfo lookup proves that
a qdisc can attach; the isolated setup check below tests actual attachment.

## Obtain the working code

Run these commands on the NucBox after Linux is ready:

    git clone https://github.com/srgangaram-swe/networks_project.git
    cd networks_project
    git switch feat/6-9-11-pilot-evidence
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements-dev.txt
    sh scripts/check.sh

Record git rev-parse HEAD before running a test. This branch contains the
unmerged pilot work and the equipment setup additions. After it is merged,
use the reviewed dev revision instead of assuming a moving branch is a fixed
experiment version. Keep local observations under .local or runs.

## Inspect without changing the network

The following commands are safe to plan on the Mac. Hardware inspection
reports unsupported_platform there and exits 2; that is expected.

    .venv/bin/python scripts/verify_testbed_contract.py
    .venv/bin/python scripts/nucbox_smoke.py plan
    .venv/bin/python scripts/inspect_hardware.py

On Linux, inspection reports kernel and architecture, bounded tool-version
tokens, module discovery, and physical-interface driver, carrier, link speed,
and MTU. It also identifies interfaces seen on IPv4 or IPv6 default routes.
A route lookup failure produces an unknown result, not an assertion that
an interface is safe. No interface is authorized for changes by this report.

Inspection never loads modules, creates namespaces, opens workload sockets,
changes routes, or configures a device. It omits MAC addresses, IP addresses,
serial numbers, full command banners, and sysfs paths. Interface names remain
in this local report; review and redact it before publishing any evidence.
Exit 0 means the inspection completed, not that all tools or hardware passed.
Missing values and failed probes require investigation. Linux without visible
sysfs, an unreadable inventory, or more than 32 interfaces produces an error.

Each of 13 command probes has a three-second deadline and a 16 KiB output cap.
NIC inspection reads at most 32 interfaces and 256 bytes per numeric attribute.
Module discovery can fail for built-in features that nevertheless work. Only
the subsequent namespace test establishes attachment on the running kernel.

## Run the unloaded setup check

On the NucBox, after confirming permission to create isolated namespaces:

    mkdir -p .local
    sudo .venv/bin/python scripts/nucbox_smoke.py run \
      --output .local/nucbox-smoke-01 --authorized-isolated-host

This executes four two-second foreground measurements, one per queue policy,
with a two-second drain per trial. Each trial uses fresh owned namespaces.
There is no bulk traffic and no warmup. This is an unloaded setup and cleanup
check; it does not exercise or resolve the known iperf warmup-reporting defect.
It changes no physical NIC, host route, or host-wide forwarding setting.

The output directory must not exist, and its parent must already exist.
It is created with owner-only permissions. The command prints a completed
summary only after all four run bundles pass validation. Each bundle contains
foreground observations, queue snapshots, source/configuration hashes, CPU
scope, lifecycle records, and the namespace ownership journal. The summary
and plan remain in the output directory. All trials remain ineligible for
primary collection, including when the setup check passes.

Inspect the result on the NucBox:

    sudo cat .local/nucbox-smoke-01/summary.json
    sudo .venv/bin/python scripts/validate_bundle.py .local/nucbox-smoke-01/fifo

The smoke wrapper stops on the first failure and never retries silently.
It preserves completed observations and the failed trial. Ctrl-C or SIGTERM
requests cancellation; the trial runner stops owned children and removes
owned namespaces. If cleanup fails, inspect that trial's ownership journal
and use the existing cleanup command for that exact directory:

    sudo .venv/bin/python scripts/testbed.py cleanup \
      --state .local/nucbox-smoke-01/fifo/topology --authorized-isolated-host

Replace fifo with the actual failed policy. Never delete namespaces by name
pattern. Correct the cause, retain the failed output, and choose a fresh
directory for a new smoke check. Consult [the operating guide](running-experiments.md)
for recovery details. The full randomized pilot still has the documented
timing blocker in [the pilot notes](namespace-pilot.md).

## When two Linux endpoint computers become available

The intended physical wiring is:

    Linux client -> USB Ethernet adapter -> Cat6 -> NucBox port 1
    NucBox port 2 -> Cat6 -> USB Ethernet adapter -> Linux server

The two received cables fill both active links. The third requested cable
was a spare. A separate backup software router was optional. No switch is
needed for this direct two-link layout.

Confirm the delivered adapter models. The requested
[Plugable USBC-E2500](https://plugable.com/products/usbc-e2500) supports Linux
and USB-A/USB-C connections; these specifications do not verify an unidentified
delivered adapter. Use USB 3.0 or faster for the intended 2.5 Gb/s connection.
Check negotiated speed, driver, MTU, and effective offloads on each endpoint.
Each underlying link must exceed the planned 100 Mb/s shaped bottleneck.

The current automatic backend deliberately accepts no host NIC names and does
not deploy a distributed physical topology. Before adding that backend, record
approved test interfaces and management interfaces, implement physical-device
ownership and rollback, and have the team review the mapping. Simply renaming
the namespace interfaces to physical NIC names is not a supported deployment.
The Mac can remain the development and management computer throughout.

## Acceptance still needed

For #2, review the recorded candidate commands and the measurement contract
with the team, pin actual software versions, and calibrate the remaining
tolerances. For #3, verify the model, installed Linux, drivers, qdisc support,
permissions, and booking on the NucBox, then arrange endpoint availability
and independent inventory review. A hosted Linux setup check verifies the
software path but does not satisfy those device-specific criteria.
