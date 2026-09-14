# Trial orchestration

The trial runner will resolve configuration, schedule randomized blocks, manage
bounded child processes, collect raw observations, and write a final validity
record. It must refuse to overwrite a run directory and retain failed runs.

The planned primary matrix is in configs/primary.json. Validation is available;
traffic execution is not implemented yet.
