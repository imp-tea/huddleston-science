# Typed-question pilot — September 25, 2026

The direct API pilot completed with **69 GPT-6 Luna requests and 177 new questions**.
Generation cost is **$0.074277385** estimated from API usage. The first prompt is
not ready for an unattended full run: an editorial screen flagged 55 questions
for some form of attention, including wording and answer-policy repairs.

All 10,976 existing multiple-choice questions remain byte-for-byte unchanged.
No application code, database content, runtime grading, or answer banks changed.
No Batch job was submitted. Drafts remain outside the authoritative data files.

## Experiment

- Model: exactly `gpt-6-luna`; Responses API, standard tier, medium reasoning.
- Maximum output: 6,500 tokens per topic; eight concurrent requests after a one-topic smoke check.
- No web tools in generation. Each request received category, every subcategory,
  topic title/aliases, description, all available detailed study text, complete
  related tournament questions, and a map of evidence IDs to supplied passages.
- Source count means distinct original source IDs. A complete bonus counts once.
- Quota: `min(source_count, 5)`; 7,072 topics imply 10,976 questions in a full run.
- Single-source answers must not be the topic identity or any alias of it.
- The pilot additionally limited multi-source topics to one topic-identity answer
  and required distinct target answers. These were design choices, not user requirements.
- Structured output includes the question, canonical answer, accepted/prompt/rejected
  variants, explanation, evidence, difficulty estimate, and writer concerns.
- A slot could report insufficient evidence instead of inventing a question. None did.

The exact executed instructions are in [TYPED_QUESTION_PROMPT.md](TYPED_QUESTION_PROMPT.md).
A frozen copy, request bodies, hashes, response traces, and API usage are retained
in the ignored local workspace `research/typed-questions/pilot-2026-09-25/`.

## Sampling

Seed `20260925`; one uniformly selected topic from each nonempty category × capped
source-count stratum, splitting one-source topics by whether detailed study content exists.
Every one of the 12 categories is represented. All strata have a known population weight.

| Source/content stratum | Population topics | Pilot topics | Pilot questions | Weighted full Batch cost |
|---|---:|---:|---:|---:|
| 1 source, detailed study content | 234 | 12 | 12 | $0.088 |
| 1 source, description only | 4,737 | 12 | 12 | $1.270 |
| 2 sources | 1,111 | 12 | 24 | $0.502 |
| 3 sources | 463 | 12 | 36 | $0.302 |
| 4 sources | 241 | 12 | 48 | $0.197 |
| 5+ sources | 286 | 9 | 45 | $0.283 |
| **Total** | **7,072** | **69** | **177** | **$2.642** |

This is a disproportionate coverage sample, not a population-proportional accuracy
study. It intentionally overrepresents rare enriched single-source topics and
high-count topics. One observation per stratum does not establish a tight error
rate or cost confidence interval. The largest selected source count was seven;
the full population reaches 19, so extreme context lengths need a later check.

## Results and quality

- 69/69 requests completed; all returned `gpt-6-luna`.
- 177/177 requested questions returned; zero insufficient-evidence slots.
- 69/69 topic outputs passed the initial structural checks. This does not certify
  factual accuracy or semantic answerability.
- 24/24 single-source questions avoided the topic identity, including aliases,
  on editorial inspection.
- The model labeled 94 questions easy, 81 medium, and two hard. These are uncalibrated
  self-labels, not student performance measurements.
- Only six questions identify the topic itself; 171 identify a related answer.
- Editorial screen: 55 questions need attention; 122 had no blocking issue noted.
  The latter are candidates for further review, not certified ready-to-publish items.

The root Codex assistant read every stem, canonical answer, accepted-answer list,
and prompt-answer list. Seventeen selected questions received additional comparison
with their supplied evidence; selected factual concerns were checked externally.
There was no exhaustive external factual audit, blind solving pass, human review,
or student trial. The complete per-question ledger is `editorial-review.json`.

### What worked

The single-source rule produced some useful associated-concept questions. The
Weaving topic asks for kente cloth using its Ghanaian makers and construction.
The Binomial coefficient topic asks how many four-digit numbers contain two 7s
and two 8s, correctly answering six. Minecraft produced concise questions about
creepers, redstone, the Ender Dragon, and Bedrock Edition.

Luna also noticed two input errors: a cosine clue used the sine ratio, and a
molality clue confused solute and solvent mass. It recorded both concerns and
avoided relying on the erroneous definitions. This is useful behavior, but it
was not consistent enough to replace verification.

### Problems to address

**Answer leakage.** The clarinet set explicitly names Johann Christoph Denner and
then asks students to name him. Another question names Henry Clerval before asking
for that friend's name. Some leaks involve omitted aliases, such as asking for
Sam Wilson while giving the series title containing Falcon. Lexical checks caught
some direct repetitions but missed semantic or partial-name leaks.

**Missing context.** The Night set refers to “the memoir” without naming it; one
question asks which camp is “paired with Buchenwald,” a reference to unseen study
prose. Other questions refer to “the chapel,” “this hero,” or “the attacks.”

**Overly strict answer policies.** Augustus is marked prompt while Octavian is
accepted. Donner Lake is missing from a question expecting Truckee Lake. A question
asking for NATO's article number accepts Article 5 but does not list 5. These would
reproduce the current typed-answer frustration without a separate answer-policy pass.
Some generic prompts such as Africa or dance are also too broad to merit a retry.

**Ambiguity and specificity.** Questions asking for a famous Racine tragedy,
Odin's hall, or a Marxian theory of class conflict lack sufficient distinguishing
clues. Asking for the field astronomy while requiring Indian astronomy is an
answer-line specificity mismatch.

**Inherited factual errors.** The Night study text says the memoir begins in the
Sighet ghetto. USHMM identifies earlier, 1941 events in its opening pages; the
Sighet ghettos were established in 1944. A Hydra question inherits a source's
confusion between burning missiles and cauterizing neck stumps. These are examples
of faithful use of a flawed source, not invented citation IDs.
Sources: [USHMM](https://encyclopedia.ushmm.org/content/en/article/sighet),
[Apollodorus 2.5.2](https://www.theoi.com/Text/Apollodorus2.html).

The missing Donner Lake alias is confirmed by the
[California State Parks brochure, page 4](https://www.parks.ca.gov/pages/503/files/DonnerMemorialSPFinalWebLayout2017.pdf).
The Flight 93 question's qualification about its likely target is appropriate:
[NPS](https://www.nps.gov/flni/learn/historyculture/flight93story.htm) describes the
Capitol as the most likely target. It still needs clearer standalone context.

**Category drift and overemphasis on related details.** The science topic Birds
generated two literature questions. The additional one-topic-answer limit appears
to have encouraged related-detail generation, although this pilot did not isolate
its causal effect. Multi-source topics should be allowed to identify the same
topic through different independent clue sets. Related questions should have a
clear topic connection and category fit.

## Cost and latency

| Usage | Tokens |
|---|---:|
| Total input | 245,272 |
| Cached input | 89,556 |
| Cache-write input | 155,509 |
| Ordinary uncached input | 207 |
| Total output, including reasoning | 107,845 |
| Reasoning subset of output | 67,536 |

Rates checked September 25, 2026: $0.10 ordinary input, $0.01 cached input,
$0.125 cache-write input, and $0.50 output per million tokens. Reasoning is already
included in output and is not billed a second time in this calculation.
[Official GPT-6 Luna documentation](https://developers.openai.com/api/docs/models/gpt-6-luna)
states that Batch rates are half Standard rates.

Estimated cost: **$0.074277385**. This is calculated from returned usage, not reconciled
to an invoice. There were no API web-search charges, retries, or unknown-billing requests.
Editorial work and external research in the Codex task are outside this generation estimate.

From first dispatch to last completion: **212 seconds**, including the gap after
the smoke check. Median request latency was **15.06 seconds**; range **5.01–46.77 seconds**.

Full generation projection: sum each sampled request's cost multiplied by its
stratum population, then apply the 50% Batch factor. This yields **$5.28 Standard /
$2.64 Batch**. At the same sampled token lengths but treating all input as new
cache writes, Batch would be **$3.18**. These are scenarios, not statistical bounds.
Allow a few dollars for generation; plan review, repair, and any independent factual
research separately. Prompt changes and more verbose outputs will change the estimate.

## Recommended second pilot

1. Preserve the single-source restriction. Remove the extra one-topic-answer cap
   for multi-source topics; allow repeated target answers with genuinely different clues.
2. Require category-appropriate targets and an explicit connection to the topic.
   Where supplied tournament context crosses categories, prefer another usable clue.
3. Make answer leakage a repair/rejection condition, including accepted variants.
   Distinguish legitimate descriptive clues from accepting a clue copied from the stem.
4. Explicitly replace context-dependent references and prose-extraction questions.
5. Use a separate answer-policy pass: ordinary surnames, numeric words, conventional
   aliases, and answers already made unambiguous by the stem should receive credit.
6. Give a reviewer the stem without topic labels or intended answers, and request
   an answer plus defensible alternatives. Check evidence separately. A same-model
   reviewer is useful but does not establish independent factual correctness.
7. Rerun the full fixed sample for comparison, add fresh holdout topics, and include
   the longest source contexts before submitting a production Batch job.

The first pilot's prompt and outputs remain unchanged so improvements can be compared
honestly. No corrected drafts have been silently substituted into the reported results.

## Files and rerunning

Run from the repository root:

```sh
.venv/bin/python scripts/typed_question_pilot.py status
.venv/bin/python scripts/render_typed_question_pilot.py
.venv/bin/python -m unittest discover -s tests -p test_typed_question_pilot.py
```

`run` resumes only undispatched topics in the saved manifest. Completed/error responses
are not automatically retried; interrupted/uncertain dispatches stop resumption for
reconciliation. Input-data, prompt, schema, and saved-request hashes protect the run.
The local $2 reservation check is a conservative pilot guardrail, not a provider-enforced
account spend limit. The key is loaded from `.env` only when dispatch is requested.

Local output directory: `research/typed-questions/pilot-2026-09-25/`.

- `review.html`: searchable offline viewer with category and issue filters, answers,
  editorial notes, cited passages, and full supplied context.
- `questions.md`: readable questions and answer policies with editorial notes.
- `editorial-review.json`: question-specific findings and review scope.
- `summary.json`: usage, structural results, and weighted projection.
- `manifest.json`, `requests/`, `responses/`, `prompt.md`: reproducible run record.
- `draft-questions.json`: unimported typed-question drafts with separate pilot IDs.

Research artifacts are ignored by Git and excluded from production packages. Back them
up separately if needed. A future integration must keep multiple-choice and typed banks
distinct, support accepted answers in runtime grading, and preserve pinned historical
revisions. The current importer should not receive these draft records.
