# Analysis container

The Docker image runs the existing analysis CLI against an export. Collection
uses native Linux because the kernel, qdiscs, privileges, and timing are part
of the measured environment. Docker Desktop is not a substitute for the
NucBox's native networking stack.

The root [README](../README.md#run-analysis-with-docker-compose) has the complete
Compose command. Install Docker with the Compose plugin first. The
[Docker documentation](https://docs.docker.com/compose/gettingstarted/)
describes that prerequisite.

## Environment and inputs

Dockerfile pins the Python 3.12 slim base by image digest. During the build,
scripts/setup_environment.sh creates /opt/venv and installs the pinned
analysis requirements. Git records source provenance; C++ and OpenMP runtime
libraries support the numerical wheels. Distribution
package indexes can change between builds; the Python lock and base digest
do not promise identical OS package bytes. Keep the image ID with experiment
reproduction notes.

The image contains the environment. Compose mounts the current checkout at
/workspace read-only, so Python runs the code being reviewed and Git can
record its actual revision and dirty state. This includes the local Git
metadata; use a checkout you trust. The image build context is an allowlist
of the bootstrap code and requirements, and excludes repository history,
experiment outputs, and machine configuration.

Compose requires four non-secret environment values:

| Value | Meaning |
|---|---|
| LOCAL_UID | Your numeric user ID from id -u |
| LOCAL_GID | Your numeric group ID from id -g |
| INPUT_DIR | Existing export directory, mounted read-only at /inputs/export |
| OUTPUT_DIR | Existing writable output parent, mounted at /outputs |

The default analysis destination is /outputs/analysis. It must not exist.
Input exports may be flat, indexed batches, or the published example with
compressed requests. Hashes are checked against the expanded CSV bytes.

## Runtime limits

The container has a read-only root filesystem, no runtime network, no added
capabilities, and no privilege escalation. It runs as the supplied user/group.
Only /outputs and a 256 MiB temporary filesystem are writable. Compose caps
memory at 2 GiB and process count at 128. Numerical thread pools use one
thread. The input and analysis bounds in analysis/README.md still apply.

No ports are exposed. The Docker socket is not mounted, and the container
cannot configure the host's qdiscs or namespaces. Building the image requires
network access to download the base and packages; running the analysis does not.

## Common failures

- A missing environment value means the Compose configuration is incomplete.
  Run all four export commands from the root README in the same terminal.
- A missing mount path stops Compose. Create the output parent yourself and
  check the input path instead of letting Docker create an empty input directory.
- Permission denied usually means the selected UID/GID cannot read the export
  or write the output parent. Root-owned NucBox results need a deliberate copy
  or ownership handoff. Do not open unrelated directories or run the container
  with broad privileges to work around the error.
- An existing analysis directory is retained. Choose a fresh output parent or
  a new destination name; the pipeline refuses to overwrite observations.
- Git provenance errors require a real checkout with accessible metadata.
  Exported source archives without Git history are not supported by this image.
- A failed analysis keeps partial output and its failed report. Correct the
  cause, preserve that directory, and use a new destination.

CI validates Compose, builds the image, runs the published export with the
same read-only mounts and restrictions, and checks all output hashes and
policy point estimates. It compares numbers with explicit tolerances rather
than requiring identical raster pixels across platforms.
