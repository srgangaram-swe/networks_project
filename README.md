# Protecting tail latency under contention

CS 585 Computer Networks, University of New Mexico, Fall 2026.

We are comparing Linux queue-management policies when short request-response
messages share a bottleneck with bulk TCP traffic. The question is whether we
can reduce long waits for the small messages without giving up much bulk
goodput.

The planned treatments are FIFO, FQ-CoDel, CAKE in best-effort mode, and CAKE
with bounded traffic classification. The primary experiment uses a 100 Mb/s
bottleneck, 20 ms base round-trip time, and 512-byte foreground messages at
500 requests per second. We will test three aggregate background load targets
with one or eight TCP flows. See the [experiment protocol](docs/experiment-protocol.md)
for the full matrix and the decisions we still need to make.

## Current state

This repository contains the project plan, a validated configuration format,
unit and CLI integration tests, and the contribution workflow. The traffic
generators, privileged testbed setup, trial runner, and analysis are scheduled
work. There are no experimental results yet.

The proposal's target is a 50% reduction in foreground p99 added latency under
saturating load while retaining at least 90% of FIFO's bulk goodput. These are
feasibility targets. We will report results that miss them as carefully as
results that meet them.

## Get started

Use Python 3.12 or newer. Development checks run on macOS or Linux; the actual
queue-management experiments need an isolated Linux testbed.

```sh
git clone https://github.com/srgangaram-swe/networks_project.git
cd networks_project
git switch dev
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
sh scripts/check.sh
.venv/bin/python scripts/validate_config.py configs/primary.json
```

The validator checks the planned experiment inputs. It does not configure
interfaces or run traffic. Test fixtures are synthetic and are never evidence
of network performance.

## Pick up work

Start with the [milestones](https://github.com/srgangaram-swe/networks_project/milestones)
and [open issues](https://github.com/srgangaram-swe/networks_project/issues).
Assign an unclaimed issue to yourself before starting, check its dependencies,
and make a short work branch from the latest `dev`.

Open one pull request (MR) per work item back to `dev`. Include the issue
number, tests, and anything the reviewer needs to reproduce. We can resolve
merge conflicts in that MR. Do not branch from `prod` or `main`.

Once every required item in a milestone is complete, we promote `dev` to
`prod`, validate the release candidate, and then promote `prod` to `main`.
Neither promotion is part of the everyday feature workflow.
[CONTRIBUTING.md](CONTRIBUTING.md) has the commands and review checklist.

## Where things belong

| Directory | Purpose |
|---|---|
| `configs/` | Versioned experiment inputs |
| `src/` | Shared contracts and application code |
| `testbed/` | Linux topology and queue setup |
| `experiments/` | Trial scheduling and run collection |
| `analysis/` | Data checks, intervals, and plots |
| `tests/` | Unit, integration, and synthetic fixtures |
| `scripts/` | Development and validation commands |
| `docs/` | Protocol, architecture, safety, and decisions |
| `report/` | Methods, results, and final write-up |
| `presentation/` | Slides, demo instructions, and rehearsal notes |
| `data/reference/` | Reviewed evidence with provenance |
| `runs/` | Ignored local experiment output |

Python, C++, Rust, and Bash are all reasonable choices. Use the language that
fits the component, and discuss additional toolchains before adding them.
We do not need four languages just because four are allowed.

## Team

Saif Ryan Gangaram, Christopher Ong, Alejandro Magana Guillen, and Jonathan Lloyd.

Saif is taking the architecture, foreground workload, trial runner, and release
integration work. The remaining issues are open for the team to claim.
Everyone should review another person's work and take part in an independent
replication, the report, and the presentation.

This is a course project using synthetic traffic on equipment we control.
It contains no employer data and implies no employer endorsement.
