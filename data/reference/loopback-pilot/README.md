# Loopback development reference

This is measured synthetic traffic, not invented fixture data. Six consecutive
diagnostic runs produced summary.csv and requests.csv. The provenance file
records their hashes, run count, and request count. Each summary also carries
its source commit, source content hash, and original manifest hash.

All 6,000 scheduled requests are included, including the 17 not sent in run 2.
Every run remains ineligible for primary analysis. These observations say
nothing about Linux queue-policy performance or physical NIC behavior.

See the [diagnostic report](../../../docs/pilot-readiness.md) for environment,
interpretation, limitations, and the command to reproduce the figure. Raw
bundles stay outside version control; this export is a small public reference
for plotting and inspection.
