# Bulk reporting across warmup

Status: diagnostic implementation decision, November 7, 2026. Primary
measurement-window alignment remains unresolved. Related work: #9 and #11.

## Observation

The first namespace campaign failed because the first non-omitted iperf
interval began about one second after zero. A local iperf 3.22 run with ten
seconds of warmup reproduced the problem. Its first measured interval claimed
start 1.002072, end 1.006888, and duration 2.008960 seconds. These values cannot
describe the same interval. The retained regression fixture remains rejected.

The upstream implementation resets the stream start clock when omission ends,
while periodic intervals can retain the preceding interval's end clock. This
is consistent with the observed failure; it does not establish that every
iperf version has the same defect. See the
[3.22 reset and statistics code](https://github.com/esnet/iperf/blob/3.22/src/iperf_api.c).

## Decision

Use the documented -i 0 option to disable periodic throughput reports. Keep
the requested -O warmup, reverse TCP direction, measurement duration, pacing,
and stream count. The final receiver interval is still required. Validate its
timestamps, declared duration, stream count, byte count, and agreement with
the end summary. Do not repair contradictory timestamps or accept a missing
interval. The bundle validator independently checks interval bytes and duration.

The [iperf manual](https://software.es.net/iperf/invoking.html) documents -i 0
and omission. Real one-flow and eight-flow integration tests retain ten seconds
of warmup and check the final receiver report. The hosted namespace campaign
must also pass before calling the complete pilot verified.

## Consequences

Bulk goodput remains receiver bytes divided by receiver duration. The report
contains the final measurement interval rather than a per-second time series.
The existing summary schema accepts that interval without a version change.
Prior raw reports and failed attempts remain intact; a source change requires
a new campaign rather than resuming the old one.

This change addresses the reporting boundary. It does not synchronize iperf's
measurement clock with the foreground clock, attribute CPU to separate physical
nodes, calibrate the NucBox, or authorize primary collection.
