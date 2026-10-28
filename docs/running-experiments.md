# Running development checks and Linux pilots

The portable workflow runs on macOS or Linux with Python 3.12 or newer and
iperf3. It generates real UDP and TCP traffic on loopback by default. Linux
namespace mode adds the proposed topology and queue profiles inside resources
created for that run. Physical-interface configuration is not implemented.

Every current run is a development diagnostic. The runner always records
eligible_for_primary as false. The foreground window uses an explicit monotonic
start time, while iperf3 owns its receiver window. They overlap but are not
aligned exactly. That limitation must be resolved and reviewed before using
these runs for the primary comparison.

## Install and check

On macOS, install iperf3 with Homebrew. On Debian or Ubuntu, install the listed
packages through the distribution package manager. These are operator commands,
not actions performed automatically by the experiment runner.

    brew install iperf3

    sudo apt-get update
    sudo apt-get install python3-venv iperf3 iproute2 ethtool iputils-ping tcpdump

From the repository root:

    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements-dev.txt
    sh scripts/check.sh

The check runs formatting, lint, McCabe complexity, unit tests, real socket and
subprocess integration tests, and coverage. Combined coverage and branch
coverage each have a 90% floor. Linux namespace tests are listed as skipped
unless explicitly enabled on an authorized host. An absent iperf3 causes the
TCP integration cases to report a skip; install it before treating local
verification as complete. CI installs iperf3 and runs those cases.

Plotting is an optional dependency group:

    .venv/bin/python -m pip install -r requirements-plots.txt

The core experiment code uses the Python standard library. The plotting lock
contains Seaborn and its transitive dependencies. The development lock contains
Ruff and coverage.py. See [engineering standards](engineering-standards.md) for
the dependency audit and complexity requirements.

## One local diagnostic

Choose a new directory for every attempt. The parent directory must exist.

    mkdir -p runs
    .venv/bin/python scripts/trial.py --output runs/local-one --seconds 2 --flows 1
    .venv/bin/python scripts/trial.py --output runs/local-eight --seconds 2 --flows 8
    .venv/bin/python scripts/validate_bundle.py runs/local-one

The default aggregate TCP demand is 8 Mb/s, split across one or eight streams.
Use --aggregate-bps to change the aggregate, not the per-stream rate. UDP
requests remain 512 bytes at 500 requests per second. The responder listens on
UDP 42000; iperf3 listens on TCP 5201. Loopback service ports can be changed with
--foreground-port and --bulk-port. An occupied port fails; the program does not
silently switch to another service port.

The validator reports integrity_valid separately from eligible_for_primary.
Integrity means the artifacts, hashes, timestamps, counts, flow set, and
declared configuration reconcile. It does not mean the generator met every
deadline or the experiment is scientifically ready. Read not_sent and the
timeout counts as well as latency. A lower successful-reply p99 can hide
deadline misses if those counts are omitted.

Ctrl-C or SIGTERM requests cancellation. Owned child processes are terminated
and reaped, and the run keeps its manifest and available component output.
Failed and interrupted runs remain discoverable. The validator rejects them
as completed data; rerun into a new directory without replacing the failure.

## Plan before changing a Linux host

These commands are read only and also work on macOS:

    .venv/bin/python scripts/inspect_testbed.py
    .venv/bin/python scripts/testbed.py plan --policy fifo --token 012345abcdef
    .venv/bin/python scripts/testbed.py plan --policy cake_bounded --token 012345abcdef
    .venv/bin/python scripts/schedule.py configs/primary.json --output runs/schedule.json

Inspection reports unsupported_platform on macOS with exit status 2. This is
expected, not a missing macOS implementation of Linux traffic control. A saved
schedule contains all 280 primary cells, their seed, and same-block baseline
pairings. Saving it generates no traffic and does not authorize collection.
The current runner executes one diagnostic at a time; primary schedule execution
and replacement-attempt reconciliation remain part of issue #9.

## Move to the experiment machine

Pull the same reviewed source revision on the Linux machine and recreate the
Python environment there. Do not copy the Mac virtual environment. First
complete the equipment checklist, including permission, kernel support,
effective offloads, tool versions, and an isolated host. No interface on the
host is selected by name or changed by the namespace adapter.

Run a short namespace diagnostic only after those prerequisites are met:

    sudo .venv/bin/python scripts/trial.py --mode namespace --policy fifo --seconds 2 --warmup-seconds 1 --output runs/linux-fifo --authorized-isolated-host

The policies are fifo, fq_codel, cake_best_effort, and cake_bounded. Each trial
gets a fresh topology and removes it afterward. Namespace foreground ports
are fixed at server 42000 and client 42001 to match the classification rule.
The proposed shaping rate is fixed at 100 Mb/s with 10 ms of receive delay at
each endpoint. Namespace results describe a virtual testbed, not physical NIC
performance.

On that authorized Linux host, run the explicitly privileged test group:

    sudo env NETWORKS_RUN_PRIVILEGED=1 .venv/bin/python -m unittest discover -s tests/linux -v

This group runs all four profiles, checks attachment, checks observed delay,
and verifies the cleanup journal is empty afterward. Unsupported qdiscs or
failed commands fail the test. The group does not establish rate calibration,
bounded-priority abuse resistance, or primary collection readiness by itself.

## Inspect and recover

The testbed command can manage a standalone topology for inspection:

    sudo .venv/bin/python scripts/testbed.py setup --state runs/manual-topology --policy fifo --authorized-isolated-host
    sudo .venv/bin/python scripts/testbed.py inspect --state runs/manual-topology --authorized-isolated-host
    sudo .venv/bin/python scripts/testbed.py cleanup --state runs/manual-topology --authorized-isolated-host

Each private state directory contains a locked ownership journal with the
namespace device and inode identities. Cleanup is idempotent. It refuses
replaced namespaces and namespaces containing live processes. Stop the specific
owned workload first, then retry cleanup. Never substitute a broad process kill
or a prefix-based namespace deletion.

For a failed trial, use its topology subdirectory as --state. A process killed
between namespace creation and journal publication can leave an unrecorded
resource. Inspect that resource and its provenance manually; automatic cleanup
does not guess ownership. Keep the original failure and journal until recovery
is understood.

## Export and plot

An export validates every input, strips absolute request clocks and machine
identifiers, and records the originating run and source hashes. It includes
every measurement request and every run-level summary in the selected inputs.
At most 20 runs and 200,000 request rows may enter one export.

    .venv/bin/python scripts/export_diagnostics.py runs/local-one runs/local-eight --output runs/local-export
    .venv/bin/python scripts/plot_diagnostics.py runs/local-export --output runs/local-diagnostics.png

The figure shows every run's p99 RTT, sender delay, missed-slot fraction, and
receiver goodput. It makes no queue-policy comparison or confidence-interval
claim. Keep raw runs local. Review exported fields and the rendered figure
before adding reference evidence to the repository.

## Return codes and limits

Ordinary CLI success returns 0. Validation, setup, or collection failure returns
2; trial cancellation returns 130. Namespace operations require root on Linux
and explicit acknowledgement of the authorized host. Commands have bounded
runtime and output, and subprocesses use argument arrays without a shell.
The complete resource and complexity bounds are in
[engineering standards](engineering-standards.md).
