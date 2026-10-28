# Testbed safety

The experiment may need root to create network namespaces and configure Linux
traffic control. Development and ordinary CI must not require root.

Only use dedicated lab interfaces or project-owned namespaces. Setup must refuse
the host's default-route interface unless an explicit, reviewed testbed profile
proves it is isolated. Record ownership before changing state. Cleanup must
remove only resources created by the current run and tolerate interruption.
Never flush host-wide firewall or routing tables.

Traffic must remain between authorized endpoints. Cap rate, runtime, child
process count, and output size. Do not use public targets or replay personal,
campus, employer, or production traffic. A borrowed machine needs its owner's
permission before configuration changes.

Credentials, private notes, and unreviewed captures stay local. Commit only small,
reviewed reference bundles containing synthetic traffic. Validate request IDs,
lengths, version fields, numeric finiteness, and file paths at each boundary.
Incomplete evidence must fail validation rather than produce a success plot.

CI uses hosted runners with read-only repository permissions. It does not
deploy or reconfigure hardware. Privileged tests run separately on an isolated
Linux testbed with recorded permission, configuration, and cleanup evidence.

The optional linux_namespaces input enables a separate manual job on a
disposable GitHub-hosted Ubuntu runner. Dispatch it only for a trusted source
revision. It has read-only repository access and no deployment credentials.
Its privileged commands create project-owned namespaces and leave host NICs,
routes, and firewall rules alone. Pull-request events cannot enable this job.
