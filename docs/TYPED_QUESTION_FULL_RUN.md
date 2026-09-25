# Full typed-question generation, September 25, 2026

The owner subsequently approved this set for production. The final stems and
answers have been copied unchanged into `data/typed-questions.json`, with stable
topic/question IDs. The Django importer now loads it alongside the preserved
multiple-choice bank. See [the deployment guide](../UPDATE_DEPLOYMENT.md).
The run-time figures and unchanged-data statements below describe the generation
stage, before this separate production integration.

Completed: **15,947 questions across all 7,072 topics**, with no failed topics.
The new API cost estimate is **$4.166796**, including generation, automatic reviews,
and five targeted follow-up repairs. Including the previously paid reused pilot
generations, the corpus cost is about **$4.21**.

The detector initially flagged 3,012 questions across 2,606 topics. Follow-up
reviews revised 2,916 questions. After the additional quality repairs, **188
questions (1.18%) retain possible giveaway flags**. These are review candidates,
not 188 confirmed defects. Results and cost are recorded in
`research/typed-questions/full-2026-09-25/summary.json`.
The [question browser](http://127.0.0.1:8776/review.html) provides category/search
filters, answers, original stems, correction history, remaining detector flags,
and the exact readable context supplied for each topic.

## Generation

The full corpus contains 7,072 topics and requests 15,947 questions. The quota is
`max(2, min(5, source_question_count))`. Generation uses the unchanged
[v5 prompt](TYPED_QUESTION_PROMPT_V5.md), readable topic context, `gpt-6-luna`,
`xhigh` reasoning, and a 16,000 output-token limit. Strict structured output
contains only questions and answers. There are no generated aliases, prompt-on
answers, citations, or explanations.

Calls use the synchronous Responses API. The run reuses the 69 identical v5 pilot
generations and generates the other 7,003 topics. Every request, response, original
output, and resulting question list is saved. Production data and existing
multiple-choice questions are unchanged; this is a separate candidate corpus.

## Giveaway review

The lexical detector compares each answer against its stem using normalized
phrases, distinctive overlapping words, and a limited set of word endings.
Generic words and required topic-name overlaps are generally excluded. It caught
all eight giveaways previously flagged in the v5 pilot, but this is a development
sample, not an independent accuracy measurement.

Each flagged topic gets one follow-up using the
[correction prompt](TYPED_QUESTION_CORRECTION_PROMPT.md). The request replays the
original input and the complete model output, including encrypted reasoning and
assistant message metadata, then supplies the automatic flags. The model may
leave harmless matches unchanged. Code enforces the original answers and question
count, and applies changes only to flagged stems. Residual matches remain visible
instead of triggering an indefinite rewrite loop.

These are possible giveaways, not a comprehensive semantic quality check. Shared
words can be harmless, and indirect, translated, or conceptual giveaways can be
missed. The detector has a known overmatch between ordinary “end” and “Endians”.
Counts of revised questions should not be interpreted as counts of proven errors.

Spot-checks found a handful of correction regressions. Additional saved model
turns restored omitted topic names and repaired a Little-Endians clue that had
incorrectly described Big-Endians. Their request/response history is under
`quality-repair/`; applied repair notes appear in the browser. This does not
constitute a factual review of every generated question.

## Validation and artifacts

`audit.json` checks counts, structure, unique IDs, repeated answer strings within
topics, answer preservation, protected stems, and unchanged production-data hashes.
It also reports literal topic-name losses for inspection; inflection or a shorter
unambiguous name can be harmless. `verification.json` checks request hashes and
settings, quotas, context, complete conversation replay, exports, and API usage
totals. The 27 relevant offline tests pass.

Final validation found no missing topics, malformed outputs, duplicate question
IDs, exact repeated answers within a topic, changed answers, or changes to
protected stems. All 2,606 automatic correction conversations preserve the full
previous model output. Saved usage reconciles across 7,003 generation calls,
2,606 correction calls, and five quality-repair calls. No transport failures or
uncertain billing attempts occurred. Production-data and frozen-code hashes match.

The three remaining literal topic-name-loss audit candidates were inspected:
“Rodrick” in an explicit Diary of a Wimpy Kid context, “sandy” for Sand, and
“Chinese” for China. These preserve the intended topic naturally and were retained.
The final browser counts, flag filter, answer display, original stems, and lazy
context loading were verified.

- `typed-questions.json`: flat candidate question set with stable topic/question IDs.
- `giveaway-review.json`: original and final stems with automatic flags.
- `remaining-flags.json`: questions still matching the detector.
- `outcomes/`: per-topic original/final results and usage.
- `generation/`, `correction/`, `quality-repair/`: saved requests and responses.
- `supplied-context/`, `manifest.json`, and prompt snapshots: reproducible inputs.

Cost estimates use actual returned token usage and the documented standard
[GPT-6 Luna rates](https://developers.openai.com/api/docs/models/gpt-6-luna),
including cache writes and reasoning output. New-run cost excludes the previously
paid v5 generations (about $0.039), and includes the follow-up repairs.

The runner is resumable with `.venv/bin/python scripts/typed_question_full.py run`;
completed outcomes are skipped and frozen inputs are checked before dispatch.
Unresolved in-flight markers require inspection to avoid blindly paying twice.
The review page can be served again with
`.venv/bin/python -m http.server 8776 --bind 127.0.0.1 --directory research/typed-questions/full-2026-09-25`.
