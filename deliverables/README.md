# Course deliverables

The report and presentation are working drafts for CS 585. They contain a
clearly labeled toy simulation, the earlier Linux namespace pilot and the
November 26 real Mac loopback and RPC measurements. The
NucBox and MacBook experiment has not yet been collected. A successful pipeline
run does not by itself settle calibration, workload timing or the study's targets.

- report.pdf is the compiled report. report.tex, sections and references.bib
  are its sources. The figure is linked to the existing simulation gallery.
- project-presentation-reviewed.pptx has 12 main slides and five hidden analysis slides.
  Charts, tables and the topology diagram are editable. The appendix includes
  K-means, t-SNE, Ward, DBSCAN, Ridge and Lasso views.
  Slide 9 shows measured loopback foreground RTT and separate RPC call duration.
  Eight native charts retain embedded editable workbooks. The original seven
  workbooks are preserved. Chart workbooks store values to six decimal places; the reference CSV files
  retain the original precision.
- The presentation's build files are local and are not tracked.

## Before the physical run

Follow [the MacBook and NucBox guide](../docs/macos-testbed.md). Confirm wired
adapters, the separate management connection, interface names and SSH access.
Use the same tested commit on all three computers. The example profile contains
placeholders; keep the completed profile under .local and out of Git.
For a NucBox controller, start with configs/macos-remote-profile.example.json.
Every role must have an SSH alias that resolves from both the controller and
the client Mac. The trial clock remains on the client.

    sh scripts/run_pipeline.sh --topology macos --transport udp \
      --profile .local/macos-profile.json --preflight
    sh scripts/run_pipeline.sh --topology macos --transport udp \
      --profile .local/macos-profile.json --authorized-isolated-host --rpc-diagnostics \
      --output runs/macos-udp-pilot-01

The second command collects, validates, exports, analyzes and plots the pilot.
It retains source identity, failed-run evidence and request accounting. A
16-trial pilot has two blocks, so Ridge/Lasso appropriately reports that there
are too few independent blocks. The larger diagnostic matrix has ten blocks
and can support grouped regression if its evidence is valid. Add
--diagnostic-matrix only after reviewing the pilot, its runtime and its limits.
Keep UDP and TCP experiments separate.

For a real local socket check before connecting the hardware:

    sh scripts/run_pipeline.sh --topology loopback --transport udp \
      --rpc-diagnostics --output runs/loopback-rpc-01

This collects four trials and automatically writes separate foreground and
RPC tables and figures. Keep the complete output directory, including raw
bundles, manifests and failed attempts. The November 26 reference is in
[the loopback evidence directory](../data/reference/mac-loopback-2026-11-26/README.md).

For the reproducible toy example, run:

    sh scripts/run_pipeline.sh --topology local --workers 4 \
      --output runs/local-example-01

This produces 48 trials and 240,000 measured slots, three times the earlier
16-trial pilot, using bounded multiprocessing. It does not exercise Ethernet.

## Replace preliminary examples after collection

Read status.json, analysis/report.json, analysis/diagnostic_summary.txt and
analysis/insights.txt first. Investigate omissions, timeouts, achieved load,
queue attachments and cleanup. Preserve unfavorable results and failed runs.
Inspect every plot at full size before choosing figures for the report.

| Content to update | Pipeline output | Location in deliverables |
|---|---|---|
| Policy effects and block counts | analysis/policy_comparisons.csv | Report findings; presentation slides 5 and 6 |
| Scheduled, unsent, timed-out and late requests | analysis/diagnostic_summary.txt and run summaries | Report findings; slide 7 |
| Cluster labels and coordinates | analysis/run_clusters.csv and cluster_diagnostics.csv | Hidden slides 13 through 16 |
| Loopback and RPC outcomes | analysis/runs.csv and rpc-analysis/rpc-summary.csv | Report loopback subsection; slide 9 |
| Held-out predictions and errors | analysis/regression_predictions.csv and report.json | Hidden slide 17; report findings |
| Environment, versions and source | plan.json, collection bundles and report.json | Report technical section and figure captions |
| Costs and equipment | Actual receipts and recorded setup details | Report cost section |

In PowerPoint, use Edit Data on each chart and paste the corresponding reviewed
values. Preserve series/category order, units and noise labels. For tables,
replace the numbers and the evidence label together. Do not relabel an existing
simulation chart as measured. The simulation appendix can remain as a separate
software example if clearly labeled.

Update findings, introduction and conclusion together so their claims agree.
Record the physical topology's different delay placement and native Mac TCP.
Add actual equipment, tool versions, tested workload, costs and limitations.
The report's eight scholarly citations point to published versions; verify
any added references before submission.

## Compile and rehearse

Install a TeX distribution with the IEEEtran bibliography style, Latin Modern,
microtype, enumitem, booktabs, geometry, graphicx, xcolor, parskip, hyperref and
tabularx. Then run from the repository root:

    sh scripts/build_report.sh

Auxiliary files stay in .local/report-build. The script rejects missing
citations and overfull content. CI recompiles the same source on Linux.
Review the resulting PDF visually after changing prose, numbers or figures.

The suggested speaking plan totals ten minutes. Notes carry timing and source
details. Each person should rehearse their section and adjust the handoffs:

| Speaker | Main slides | Suggested time |
|---|---|---|
| Saif Ryan Gangaram | 1 through 3 | 2 minutes 30 seconds |
| Christopher Ong | 4 through 6 | 2 minutes 30 seconds |
| Jonathan Lloyd | 7 through 9 | 2 minutes 30 seconds |
| Alejandro Magana Guillen | 10 through 12 | 2 minutes 30 seconds |

Jonathan's title and employer remain pending confirmation. Confirm everyone's
program of study for the report. Submit the presentation by December 1 at
10:59am and be ready to present December 1 or December 3. The final report is
due December 8 at 11:59pm. Check the instructor's complete submission checklist
and review the final documents with the team before submitting.
