# NucBox setup with the available equipment

Related work items: #2 and #3. Updated November 11, 2026.

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

## Control the NucBox from the Mac

Borrow a monitor or TV with HDMI and a USB keyboard for the first boot. Power
the NucBox with its supplied adapter. A normal HDMI or USB cable between the
two computers does not turn the Mac into a display or establish a terminal.
Once remote access works, the monitor and keyboard can be disconnected.

For the initial management connection, connect one NucBox Ethernet port to
your home router and keep the Mac on the same local network. This connection
is for setup and SSH; the namespace experiment does not send its workload
through that physical port. Guest Wi-Fi or client isolation may prevent the
computers from reaching each other.

After logging into Ubuntu at the NucBox console, follow the
[Ubuntu OpenSSH instructions](https://ubuntu.com/server/docs/how-to/security/openssh-server/):

    sudo apt-get install --yes openssh-server
    sudo systemctl enable --now ssh
    whoami
    ip -4 -brief address show scope global
    sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub

Keep the username, local Ethernet address, and host-key fingerprint at hand.
In Terminal on the Mac, replace both placeholders below with those actual
values. Omit the slash and prefix length shown after the address.

    ssh LINUX_USERNAME@NUCBOX_LAN_IP

Compare the displayed ED25519 fingerprint with the console before accepting
the first connection. Enter the Linux account password when prompted; Terminal
does not display password characters. Run the project commands in that SSH
session. Keep the local console available until a second connection succeeds.
Use local access only; no router port forwarding is needed.

A direct link is also possible using Mac -> USB Ethernet adapter -> Cat6 ->
NucBox, but it needs compatible addresses on both ends and an already running
SSH server. Merely plugging that cable in does not configure a newly unboxed
computer. The home-router connection avoids that extra initial configuration.

## Obtain the working code

Run these commands on the NucBox after Linux is ready:

    git clone https://github.com/srgangaram-swe/networks_project.git
    cd networks_project
    git switch dev
    sh scripts/setup_nucbox.sh --plan
    sh scripts/setup_nucbox.sh --install

Run the installer as your ordinary Linux account. It requests sudo for the
distribution packages, prepares this checkout's .venv, and runs the portable
checks. Package update, installation, and pip each have a five-minute deadline;
a failed step stops the script. Apt may retain installed packages after an
interruption; inspect the error before rerunning the same idempotent setup.
The script supports Ubuntu 24.04 LTS and Python 3.12 or newer. Other releases
need manual preparation and verification. Use --plan on the Mac. Installation
never starts a privileged experiment, modifies physical NICs, or installs an OS.
Its tests send local loopback traffic. The installer also installs C++ build
tools, builds Chris's retained prototype, and runs its sanitizer-backed checks.

Record git rev-parse HEAD before running a test. Use the reviewed dev revision
and keep that checkout unchanged during a campaign. A moving branch is not a
fixed experiment version. Keep local observations under .local or runs.

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
check. The separate loaded pilot exercises the
[final-report workaround](decisions/0002-bulk-final-report.md) for iperf's
warmup-reporting defect.
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
for recovery details. See [the pilot notes](namespace-pilot.md) for the loaded
campaign and its remaining measurement limits.

## Run the complete initial experiment

After installation and local inspection, plan the complete diagnostic path:

    .venv/bin/python scripts/nucbox_experiment.py plan

Then, on the authorized NucBox Linux host:

    mkdir -p runs
    sudo .venv/bin/python scripts/nucbox_experiment.py run \
      --output runs/nucbox-pilot-01 --authorized-isolated-host

The destination must be new. This runs read-only hardware inspection, four
unloaded setup checks, the recorded 16-trial loaded/unloaded campaign, checked
export, paired statistical comparisons, K-means clustering, PCA, and t-SNE.
Expect roughly ten minutes for this diagnostic path, depending on the host.
All workload traffic remains inside owned namespaces. The existing limitations
on physical NIC measurements and primary eligibility still apply.

Results are under hardware.json, setup/, campaign/, export/, and analysis/.
The analysis directory contains CSV tables, report.json, and a plots subdirectory
with PNG and SVG policy, delivery, RTT-quantile, and available cluster figures.
The [plot guide](../analysis/plots/README.md) explains each view. Read status.json for the
last stage and final state. The run directory is owned by root with mode 700;
use sudo to inspect it locally rather than relaxing permissions on unrelated
directories. After review, copy the export and analysis files to the Mac for
further work. They contain synthetic experiment traffic, not personal traffic.

A failed stage stops the workflow and retains earlier outputs. Ctrl-C cancels
owned collection. Correct the cause and use a new top-level output directory;
never rerun into an existing one. Individual campaign recovery still uses the
retained attempt ledger and exact namespace ownership journal. Missing analysis
dependencies mean the installer has not completed; do not skip the checks.

The analysis also writes diagnostic_summary.txt and writeup_table.tex. Use
these with the checked CSV tables, figures, and report.json when drafting the
results and limitations. They retain failed targets and missing intervals.

## Plan the larger diagnostic matrix

The default remains the 16-trial pilot. An explicit option uses the 280-cell
planning matrix, with ten blocks, 60-second measurements, and ten-second
warmups. It remains diagnostic, with primary eligibility set to false.
Review [the completion checklist](project-completion.md) before scheduling it.
Warmup and measurement alone require about 5 hours 27 minutes, plus setup,
drain, validation, export, and analysis. Keep power and the controlling session
available throughout. Do not use a long collection as a substitute for calibration.

    .venv/bin/python scripts/nucbox_experiment.py plan --diagnostic-matrix
    sudo .venv/bin/python scripts/nucbox_experiment.py run --diagnostic-matrix \
      --output runs/nucbox-matrix-01 --authorized-isolated-host

The exporter divides the 8.4 million measured request slots into 47 batches
of at most six runs. Each batch stays below 200,000 request rows. The export
root retains the full attempt ledger and a hash-bound index. Analysis accepts
that root directly and validates one batch's requests at a time:

    sudo .venv/bin/python -m analysis.policy_comparison \
      runs/nucbox-matrix-01/export --output runs/nucbox-matrix-analysis-02

Do not pass both the root and its batch directories; that duplicates runs.
An incomplete export index is rejected. Retain it, investigate the failed
operation, then export the unchanged campaign into a fresh directory.
For an interrupted campaign, inspect owned resources first, correct the cause,
and resume the retained plan without changing source or configuration:

    sudo .venv/bin/python scripts/campaign.py --resume \
      --output runs/nucbox-matrix-01/campaign \
      --replacement-reason "Describe the investigated interruption and correction" \
      --authorized-isolated-host

Completed cells are skipped; a failed cell gets a new recorded attempt, with
at most three attempts per cell. After recovery, run scripts/export_pilot.py
with the campaign path and a fresh --output directory, then analyze that export.
The top-level status.json retains the original failure; the campaign ledger
and new export document the recovery. No command promotes observations to
primary evidence. Exact workload timing, calibration, and protocol review
remain necessary before the primary experiment.

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
