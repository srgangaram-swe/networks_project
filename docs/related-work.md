# Related work and workload rationale

The four proposal references explain why we measure foreground latency and bulk
goodput together. Our experiment compares Linux queue policies on one controlled
bottleneck. It does not reproduce the workloads or results of these papers.

## Comparison

The last two columns are our design interpretation, not findings reported by
the cited authors.

| Published work | Relevant finding or mechanism | Use in this experiment | Limit on the comparison |
|---|---|---|---|
| [RED, Floyd and Jacobson (1993)](https://dl.acm.org/doi/10.1109/90.251892) | RED uses average queue size to signal congestion before a queue fills. | Motivate measuring delay as well as throughput when comparing FIFO with active queue management. | RED is background literature, not one of our four treatments. We are not measuring RED against CoDel. |
| [Sizing router buffers, Appenzeller et al. (2004)](https://dl.acm.org/doi/10.1145/1015467.1015499) | Buffer requirements depend on TCP dynamics and how many flows share a link; the paper studies reduced buffering with many multiplexed flows. | Record queue limits, RTT, and flow count rather than treating buffer size as an incidental setting. | One and eight bulk flows do not establish the paper's many-flow regime. Its scaling result is not a ready-made buffer setting for this testbed. |
| [DCTCP, Alizadeh et al. (2010)](https://dl.acm.org/doi/10.1145/1851182.1851192) | Bulk flows can build queues that delay foreground traffic. DCTCP uses ECN feedback to change TCP's response to congestion. | Evaluate latency and goodput under the same load instead of optimizing either in isolation. | DCTCP is not a treatment here. Our 100 Mb/s, 20 ms testbed is not the paper's data-center environment. |
| [CAKE, Hoiland-Jorgensen et al. (2018)](https://ieeexplore.ieee.org/document/8475045/) | CAKE combines shaping, queue management, flow and host isolation, and traffic-class handling. | Compare best-effort CAKE with bounded classification, and test whether bulk traffic can misuse priority. | The comparison measures configured policy packages. It cannot attribute every difference to a single CAKE feature or establish physical NIC performance from namespaces. |

## Why use a synthetic workload?

Small, regularly scheduled requests make it easier to separate queueing effects
from application computation. Bulk TCP supplies sustained competition on the
same bottleneck. Fixing message size and arrival rate also gives us an input
that another team member can reproduce without private traces or a production
service. This is our experimental rationale, not a claim that these papers
validate our exact workload.

The [planning protocol](experiment-protocol.md) specifies 512-byte messages at
500 requests per second, or one request every 2 ms. That is 2.048 Mb/s of
request-message data before transport and link overhead; replies consume
additional bandwidth according to the response size. Response size and framing
must be settled in the protocol decision before measurement. A 60-second run
schedules 30,000 requests, and missed or late requests must remain visible.

One versus eight competing TCP flows tests the effect of sharing the bottleneck
among different numbers of flows. Splitting the same aggregate background target
across them avoids deliberately multiplying the requested load by eight. The
50%, 90%, and 110% targets cover lower load, near-capacity demand, and overload.
Actual goodput and queue statistics must confirm the resulting conditions;
110% offered demand cannot produce 110% of link capacity as delivered traffic.

Fixed-size requests omit production burstiness, variable response sizes, and
application processing. The results will not establish distributed training speedups,
inference performance, trading-system latency, or behavior on every access link.
The planned sensitivity and replication work checks selected assumptions, not
all of these applications.

## Bibliography

Names below use ASCII transliterations. [The BibTeX file](../report/references.bib)
preserves the accented names for a typeset report.

1. Sally Floyd and Van Jacobson. "Random early detection gateways for congestion
   avoidance." IEEE/ACM Transactions on Networking, 1(4), 397-413, 1993.
   [Published record](https://dl.acm.org/doi/10.1109/90.251892).
2. Guido Appenzeller, Isaac Keslassy, and Nick McKeown. "Sizing router buffers."
   Proceedings of ACM SIGCOMM 2004, 281-292, 2004.
   [Published record](https://dl.acm.org/doi/10.1145/1015467.1015499).
3. Mohammad Alizadeh, Albert Greenberg, David A. Maltz, Jitendra Padhye,
   Parveen Patel, Balaji Prabhakar, Sudipta Sengupta, and Murari Sridharan.
   "Data center TCP (DCTCP)." Proceedings of ACM SIGCOMM 2010, 63-74, 2010.
   [Published record](https://dl.acm.org/doi/10.1145/1851182.1851192).
4. Toke Hoiland-Jorgensen, Dave Taht, and Jonathan Morton. "Piece of CAKE:
   A Comprehensive Queue Management Solution for Home Gateways." 2018 IEEE
   International Symposium on Local and Metropolitan Area Networks (LANMAN),
   37-42, 2018. [Published record](https://ieeexplore.ieee.org/document/8475045/).

## Source checks

Checked September 21, 2026. All four Crossref records returned matching titles,
authors, publication years, venues, and page ranges. Publisher-page retrieval
was blocked for ACM and failed for IEEE during this check; that does not establish
that a DOI is broken or that the publisher's full text was inspected. A teammate
should open the published records through the university library before report
submission.

| Paper | Publisher-deposited metadata | Primary material used to check the comparison |
|---|---|---|
| RED | [Crossref record](https://api.crossref.org/works/10.1109/90.251892) | [Author publication page](https://www.icir.org/floyd/papers/red/red.html) and [author prepublication manuscript](https://www.icir.org/floyd/papers/early.twocolumn.pdf) |
| Buffer sizing | [Crossref record](https://api.crossref.org/works/10.1145/1015467.1015499) | [SIGCOMM conference-hosted paper](https://conferences.sigcomm.org/sigcomm/2004/papers/p277-appenzeller1.pdf) |
| DCTCP | [Crossref record](https://api.crossref.org/works/10.1145/1851182.1851192) | [Microsoft Research publication page and abstract](https://www.microsoft.com/en-us/research/publication/data-center-tcp-dctcp/) |
| CAKE | [Crossref record](https://api.crossref.org/works/10.1109/LANMAN.2018.8475045) | [University-hosted accepted manuscript](https://kau.diva-portal.org/smash/get/diva2:1235974/FULLTEXT01.pdf), whose cover identifies the published LANMAN paper |

The author manuscripts support the reading notes; they do not replace the
published citations. No paper PDFs or private course pages are redistributed
here. The second-teammate source review required by issue #4 is still pending.
