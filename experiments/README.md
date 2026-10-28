# Trial orchestration

The scripts/trial.py command runs one diagnostic with a paced UDP foreground
and one or eight reverse TCP streams. It bounds child processes, retains failed
attempts, refuses an existing run directory, and records hashes and phase times.

The planned primary matrix is in configs/primary.json. The scripts/schedule.py
command saves its 280 randomized cells and baseline pairings without generating
traffic. Executing that full schedule and reconciling replacement attempts are
still pending. Current diagnostics are always ineligible for primary analysis.

See [running experiments](../docs/running-experiments.md) for working commands
and [implementation status](../docs/implementation-status.md) for open criteria.
