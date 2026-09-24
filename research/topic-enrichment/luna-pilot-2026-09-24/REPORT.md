# GPT-6 Luna pilot — September 24, 2026

All **100 topics** produced complete structured drafts using **`gpt-6-luna`**,
one topic per independent API request. The estimated API charge is **$2.2966**,
including one extra paid preflight. The 99-request bulk phase took **8 minutes
25 seconds** with eight concurrent requests. Setup and the separate quality
assessment are excluded from that generation time.

[Browse all drafts](review.html) · [Machine-readable metrics](metrics.json) ·
[Protocol and resumption notes](README.md)

## Cost and scaling

| Component | Estimated USD |
| --- | ---: |
| Model tokens, all paid attempts | $0.4466 |
| 185 web search actions | $1.8500 |
| Total pilot, including preflight | **$2.2966** |
| Final 100-topic set, excluding archived preflight | $2.2716 |
| Average per new topic | **$0.02272** |

The records contain 3,575,282 input tokens (480,942 cached and 85,865 cache-write
tokens) and 260,445 output tokens. Output already includes 151,498 reasoning
tokens. Each actual response reported the requested model. All 100 final
responses completed; there were no HTTP failures or requests with uncertain
billing. An earlier TLS setup failure occurred before the API call and was
unbilled. The pilot used 101 paid requests for 100 distinct topics because the
Viola preflight was repeated once after a prompt adjustment.

The estimate applies the [published Luna rates](https://developers.openai.com/api/docs/models/gpt-6-luna)
and [web search pricing](https://developers.openai.com/api/docs/pricing) to
returned usage. Search content tokens are included at model rates; search
actions cost $0.01 each. The [web search guide](https://developers.openai.com/api/docs/guides/tools-web-search)
distinguishes search actions from page opens. This is an estimate from API
records, not a reconciled account invoice. Codex coordination and the small
Sol review sample were not billed through the personal API key.

| Further generation at the observed average | Estimated USD |
| --- | ---: |
| Other 839 topics with two original tournament sources | $19.06 |
| Other 5,576 backlog topics without pilot drafts | **$126.66** |
| Entire 5,676-topic backlog generated from scratch | $128.93 |

These projections exclude correction passes, retries and any additional quality
assessment. A provisional $150–$200 allowance for generating and correcting the
other 5,576 topics would provide some headroom; correction costs have not been
measured. The sample came from topics with two original tournament source IDs,
whereas most remaining topics have one. Their ambiguity and research effort may
differ. Generation speed and rate limits at larger scale are also untested.

## Automatic checks

Every draft contains an 87–123-word overview and either five facts (96 topics)
or six facts (four topics). Every request searched the web and recorded at least
one page-open action, satisfying the regular workflow's minimum direct-read
trace requirement.

The pilot added a stricter rule after preflight: **every cited reference must
have its own recorded page-open action**. This is stronger than the regular
queue's minimum of reading one credible source per topic. A missing trace does
not establish that the prose is false, that the URL is invented, or that search
results supplied no useful evidence.

| Check result | Topics |
| --- | ---: |
| All automatic checks passed | 1 |
| All checks except the stricter per-reference open trace passed | 77 |
| Only the stricter per-reference trace was flagged | 76 |
| At least one cited reference lacked a matching open trace | 96 |
| A block cited a URL absent from the reference list | 6 |
| Retrieval timestamps lacked a timezone | 9 |
| Researcher supplied a concern/caveat | 9 |

Rows overlap. The strict pass count is **not a factual-accuracy score**. The nine
researcher caveats include historical uncertainty, source disagreement and
carefully limited scope; they are not nine demonstrated content errors. The
validator conservatively flags any nonempty concern field. Ten drafts also have
conservative per-source word-budget warnings: the check assigns an entire block
to every source cited for that block, so it can overcount actual dependence.

Generated drafts remain unchanged, including the flags. A subsequent security
cleanup removed AWS signing parameters from six saved pilot search traces;
see [the cleanup report](../SECURITY-CLEANUP.md). `draft-content.json` contains
only the one draft passing every current automatic check, and it is still
unaccepted and unimported. All 100 drafts can be inspected in `review.html`.

## Factual sample

Twelve topics were selected before the bulk results were assessed: one from each
represented category plus one extra science topic. Three Sol researchers checked
four each against original topic context and directly read sources. The evidence
and precise suggested corrections are retained in `audit-humanities.json`,
`audit-science.json`, and `audit-history.json`. This limited sample cannot
establish the accuracy of the other 88 topics or a reliable population error rate.

| Findings in the 12-topic sample | Topics |
| --- | ---: |
| No content or citation-support issue identified | 7 |
| Minor wording, attribution or citation-list issues only | 4 |
| Substantive factual corrections required | 1 |

These classifications exclude the separate automatic trace/metadata flags.
No critical wrong-topic or central-concept failure was identified. The substantive
errors were both in **French and Indian War**: Québec fell in 1759, but Canada/New
France capitulated in 1760; and the territorial cession in the 1763 treaty
explicitly excepted New Orleans. The date error also appears in the draft's
cited State Department summary, illustrating that credible-source grounding
does not by itself guarantee accuracy. The reviewer cross-checked
[Parks Canada's chronology](https://parks.canada.ca/lhn-nhs/qc/fortchambly/culture/histoire-history/site/conquete-conquest)
and [Treaty of Paris Article VII](https://www.battlefields.org/learn/primary-sources/treaty-paris-1763).

Minor findings concern the plant/fungi distinction in **Meat**, an unlisted but
otherwise supported award citation in **Daft Punk**, the literal tombstone
notation and support for a middle name in **Ludwig Boltzmann**, and labeling
NPC Worldwide rules as IFBB Pro League rules in **Bodybuilding**. The French and
Indian War entry also merits more precise wording about Haudenosaunee alliances.
The audit files contain exact passages, evidence and suggested changes. Drafts
have been preserved as returned for an honest comparison, rather than silently
edited to improve the pilot's measured quality.

Luna looks promising as an inexpensive, fast draft generator. The next production
step should address citation/reference consistency and timestamp generation in
the pipeline, resolve the observed content issues and source-use warnings, and
decide how to handle the stricter page-open rule. This sample supports neither
rejecting most prose because of trace flags nor treating all 100 drafts as
factually verified. No matched Sol-versus-Luna benchmark was run.

## Data, security, and verification

No pilot content was accepted, imported or deployed. All site JSON hashes match
the pre-pilot manifest, including the original 1,006 detailed pages. The accepted
queue remains at **390 new enrichments**, **1,396 total detailed topics**, and
**5,676 unenriched topics**. All 939 previously eligible two-source topics remain
unenriched in the application; 100 now have separate pilot drafts.

The API key remains in `.env`, which is Git-ignored, untracked and mode 0600.
No exact key matches were found in pilot artifacts or the new runner, renderer
and test files. TLS verification is enabled. The key was not added to website
code or sent to research sources.

Validation passed: 15 Python unit tests, 11 focused Django importer/history
checks, nine Node tests, Python compilation and `git diff --check`. The existing
Sol enrichment heartbeat remains paused pending the user's pilot assessment.
No full-backlog API run has been started.

## Later status

The user subsequently accepted the pilot's observed quality and authorized
generation of the other 839 eligible two-source topics. All 100 pilot drafts and
839 subsequent drafts, with targeted corrections applied to normalized copies,
have now been accepted into site data. The quality sample, pilot costs, and
projections above remain the historical pilot report; later actual usage is
recorded with the subsequent run. The local Django import and preservation
checks passed; see the subsequent run's
[completion report](../luna-two-source-2026-09-24/REPORT.md). No deployment has
occurred, and the Sol heartbeat remains paused.
