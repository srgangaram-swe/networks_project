# Engineering standards

Keep the system small enough that another team member can inspect and reproduce it.

## Code and interfaces

Use narrow, typed interfaces with explicit units and bounded inputs. Separate
parsing, validation, process control, measurement, and analysis. Validate before
opening sockets, allocating large buffers, or changing host state. Errors should
identify the failed operation and preserve useful context without exposing secrets.

Comments explain invariants and non-obvious choices. Avoid silent fallbacks,
unbounded retries, global mutable state, and unnecessary abstractions.
Record protocol and toolchain decisions before they affect multiple components.

Ruff enforces a maximum McCabe complexity of 10; aim for 5 where the function's
responsibility permits it. Split functions around real responsibilities rather
than adding indirection only to reduce a score. The metric describes control
flow, not overall design quality. See the
[Ruff rule](https://docs.astral.sh/ruff/rules/complex-structure/).

## Failure behavior and resource ownership

Validate before mutation. Catch errors at the boundary that can report or
recover from them. Preserve the cause and failed operation. An expected input
error should produce a useful CLI message; an unexpected programming error
should remain visible during development.

Commands use argument arrays without a shell, separate stdout and stderr,
bounded output, and a deadline. Cancellation targets only the launched process
session. Reap children before removing their resources. Keep cleanup failures
in the manifest without erasing the original failure. Never retry a failed
measurement silently.

Run directories are exclusive. Artifact publication uses a temporary file,
fsync, and atomic replacement inside that run's directory. Another run cannot
overwrite existing observations. JSON readers reject duplicate keys, non-finite
values, oversized files, final-component symlinks, and special files. Check
versions, units, schemas, and cross-record invariants separately.

Namespace ownership uses recorded device and inode identities in a private
locked journal. Names alone are not proof of ownership. Cleanup refuses live
processes and replaced resources, preserves the journal on failure, and can be
retried. Host routes and management interfaces are outside the adapter's scope.

## Time and space bounds

These are implementation bounds. Operating-system suspension can delay
scheduling and cleanup, so they are not real-time guarantees.

| Component | Time | Additional memory and limits |
|---|---|---|
| Foreground accounting | O(N log W) deadline maintenance for N requests and W retained deadline entries; O(1) indexed reply lookup | O(N + W + E); at most 90,000 records, 1,024 active requests, 4,096 detailed events, and bounded rate and duration |
| Command output | O(B) for B output bytes | O(B), with a 1 MiB default combined-output cap and 32 MiB absolute cap; every command has a deadline |
| Topology and policy planning | O(1) for the fixed three-role topology | Fixed commands and resources; no arbitrary host-interface input |
| Trial schedule | O(C) for C cells | O(C), at most 10,000 configured cells |
| Bundle validation | O(N + E + B) for records, events, and artifact bytes | O(N + E + B); each JSON artifact is at most 32 MiB, with smaller manifest and configuration limits |
| Per-run diagnostic statistics | O(N log N) | O(N); each metric is sorted once within a run |
| Diagnostic export | Sum of per-run validation and summary costs | At most 20 runs and 200,000 exported request rows |

Do not substitute offered demand for achieved throughput or an asymptotic bound
for a measurement. Profile before optimizing, state the input size and workload,
and preserve correctness and failure behavior in the comparison.

## Verification

The baseline check runs formatting, lint, unit tests, CLI integration tests,
branch coverage, and repository hygiene. Branch coverage must remain at least
90% for the Python core. A separate check enforces that floor on branch coverage
itself, so a high statement count cannot hide untested decisions. Coverage is a
floor, not evidence that every case is correct.

Add corruption, timeout, malformed-input, cleanup, and partial-output cases where
they apply. Network integration tests must exercise real sockets or isolated
namespaces and carry hard deadlines. A skipped hardware test must state the
missing resource and link its tracking issue. CI must not relabel that skip as a
successful performance experiment.

Each fixed defect needs a regression case for the behavior that failed. Current
cases include corrupted receiver intervals, duplicate identifiers, child
cancellation after pipe closure, namespace replacement, and partial setup with
cleanup failure. Keep tests bounded and assert outcomes, not only that a function
was called. Do not suppress checks or weaken thresholds to accommodate a change.

Changes involving Rust require formatting, Clippy with warnings denied, and
locked dependency tests. C++ changes require warnings, sanitizer runs where
supported, and a reproducible build. Bash changes require ShellCheck. Introduce
these checks in the same MR as the corresponding component.

## Evidence

Keep raw observations immutable. Include source SHA, resolved configuration,
kernel and tool versions, topology, qdisc statistics, workload seed, timestamps,
units, and run validity. Never overwrite an existing run directory.
Retain failed runs and explain exclusions before interpreting the results.

Generate plots through Seaborn using recorded inputs, with readable units,
sample counts, uncertainty, and an accessible palette. Review rendered figures.
Do not hand-edit plotted values. Fixtures and dry runs must be labeled as such.

A milestone that collects measurements must include a reproducible evidence
figure or table. A setup-only milestone reports verified configuration and test
outcomes, not invented performance data.

## Security and review

Use synthetic traffic only and equipment the team controls. Follow
[the testbed safety rules](security.md). Pin external CI actions by full commit
SHA and give jobs only the permissions they need. Do not expose secrets to MR
code or run untrusted jobs on a lab machine with privileged network access.

Document dependency purpose and licenses; commit lock files. Review advisories
when dependencies change and before release. A clean dependency resolver is not
a vulnerability audit. Keep private notes and credentials outside tracked files.

The optional plotting environment is pinned in requirements-plots.txt from
requirements-plots.in. The core runtime uses the standard library; iperf3 is an
external tool whose version is retained in each bulk report. Review Python
advisories with pip-audit against both requirements files and record the date and
outcome in the MR. Distribution and kernel packages need their own host-specific
review before collection. A successful Python audit does not audit those tools.

The direct tools use MIT (Ruff), Apache-2.0 (coverage.py), and BSD (Seaborn)
licenses. Matplotlib uses its PSF-based license; NumPy and pandas include BSD
terms. Dependencies are installed from their distributions rather than vendored;
preserve their packaged notices when redistributing an environment.

Documentation should describe current behavior, usable commands, errors, and
limits in plain language. Use descriptive names and comments about invariants
or intent rather than narrating obvious statements. Review every figure against
its data and make the environment, units, sample counts, and exclusions visible.
