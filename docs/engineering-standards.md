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

## Verification

The baseline check runs formatting, lint, unit tests, CLI integration tests,
branch coverage, and repository hygiene. Branch coverage must remain at least
90% for the Python core. Coverage is a floor, not evidence that every case is correct.

Add corruption, timeout, malformed-input, cleanup, and partial-output cases where
they apply. Network integration tests must exercise real sockets or isolated
namespaces and carry hard deadlines. A skipped hardware test must state the
missing resource and link its tracking issue. CI must not relabel that skip as a
successful performance experiment.

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
