# Luna enrichment completion — September 24, 2026

All **839 remaining eligible topics** were researched with `gpt-6-luna`, one
topic per independent API request. These topics and the **100 corrected pilot
topics** have been validated, accepted, rebuilt, and imported into the local
application. **No unenriched topic with at least two distinct original tournament
source IDs remains.** Nothing was deployed.

| Result | Count |
| --- | ---: |
| New topics generated in this run | 839 |
| Pilot topics reused without new API generation | 100 |
| Luna topics accepted and imported | 939 |
| Detailed pages now | 2,335 |
| Total topics | 7,072 |
| Unenriched topics remaining | 4,737 |
| Remaining topics with two or more original sources | 0 |

The remaining 4,737 topics each have one original tournament source ID. They
remain in the durable queue, and the Sol continuation schedule is paused. This
API authorization covered the eligible two-source subset only.

## Usage and speed

Generation took **24 minutes 43 seconds**, with up to 20 concurrent requests.
All 839 requests returned complete responses identifying the requested model.
There were no retries, failed requests, or uncertain billing outcomes in this
run. Setup, normalization, targeted fixes, and import time are excluded from
that generation duration.

| Cost component | Estimated USD |
| --- | ---: |
| Tokens for the 839-topic run | $3.4510 |
| 1,489 web search actions | $14.8900 |
| Additional 839-topic run | **$18.3410** |
| Earlier pilot, including its extra preflight | $2.2966 |
| Combined personal API usage | **$20.6376** |

The new run averaged about **2.19 cents per topic**. Estimates use returned API
usage and recorded search actions at the published
[Luna rates](https://developers.openai.com/api/docs/models/gpt-6-luna) and
[web search prices](https://developers.openai.com/api/docs/pricing), recorded in
the manifest. They are not reconciled account invoices. Codex coordination and
targeted Sol assistance are outside this personal API estimate.

Returned usage was 27,675,889 input tokens, including 4,071,004 cached tokens
and 639,902 cache-write tokens, plus 2,067,610 output tokens. Output includes
1,173,870 reasoning tokens; those are not charged again separately.

## Acceptance and corrections

The user-approved lighter policy relied on researcher factual self-checks and
automatic validation, with targeted investigation of reported concerns and
concrete citation failures. No second full factual audit or new routine sample
audit was performed. The coordinator read all 98 automatically flagged concern
reports from the new run; these included historical uncertainty, interpretation,
source disagreements, and limitations the researcher described handling.

Every accepted topic has a paragraph, four to six facts, listed references,
supporting URLs per block, evidence notes, a completed self-check, and at least
one recorded internet search and direct source open. This baseline does not
require a distinct logged open for every cited reference. Stricter pilot
diagnostics remain in the raw artifacts and are not presented as passed.

Seven new-run topics received targeted citation or reference repairs:
Beethoven's Fifth Symphony, The Thinker, Eroica, Macondo, Tibetan Buddhism,
the theory of evolution, and the Alamo. The known pilot corrections for meat,
Boltzmann, bodybuilding, and the French and Indian War were applied to normalized
copies. These repairs are recorded in exact-match correction files. The generated
research content remains unchanged. A subsequent security cleanup removed AWS
signing parameters from web-search trace URLs in 41 saved responses across the
pilot and new run. See [the cleanup report](../SECURITY-CLEANUP.md); the generated
topic text, actual topic citations, and usage records were unchanged.

Normalization reconciled equivalent citation URLs, redundant unlisted citations,
and retrieval metadata, recording each adjustment. Original model reference
times use the recorded API request time; references added during targeted review
retain their later recorded retrieval time. Conservative source-word warnings
remain available; counting a whole block against each cited source can overstate
its dependence on that source. Automatic checks establish structure and integrity,
not the factual truth of every claim.

## Validation and preservation

All **30 Python tests, 9 Node tests, and 11 Django importer/content tests** passed.
The static build and local import succeeded. The database's 2,335 detailed topic
records exactly match the accepted content file.

Hashes confirm all **1,396 pre-existing detailed pages** are unchanged, including
the original 1,006 pages and 390 Sol enrichments. Topic IDs and non-content source
data are unchanged. Student history and all **11,538 existing question revisions**
were preserved. The importer added 1,878 revisions to snapshot the new study
content for existing questions; their question text matches previous revisions.
The durable queue contains exactly the 4,737 remaining topics without duplication.

The local `.env` remains ignored by Git, untracked, and readable only by its owner.
No API key was found in the task artifacts checked after the run.

The machine-readable trail includes [usage](summary.json),
[acceptance](integration.json), [local import](local-import.json),
[preservation and checks](verification.json),
[coordinator concern dispositions](coordinator-review.json), and the combined
normalized content and correction files in this directory. Raw responses are in
`responses/`; the original pilot records remain in the adjacent pilot directory.
