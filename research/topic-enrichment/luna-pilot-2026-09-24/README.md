# GPT-6 Luna API pilot

The user authorized 100 topics on September 24, 2026, using `gpt-6-luna` and
their existing local API key, with exactly one topic per independent researcher
request. This pilot saves drafts for quality and price assessment. It does not
accept, import, publish, or deploy content.

## Selection and execution

`manifest.json` fixes a reproducible, category-stratified sample of 100 of the
939 unenriched topics with at least two original tournament source IDs. The
sample seed is 20260924. Original questions are disambiguation context, not
factual evidence. The wider unenriched backlog was 5,676 topics when selected.
Most of that backlog has only one original source, so extrapolations from this
sample are provisional.

`scripts/luna_topic_pilot.py` calls the Responses API with the requested model,
medium reasoning, the standard service tier, web search, strict structured JSON,
at most 12 tool calls, and at most 6,000 output tokens. Eight requests run
concurrently in the bulk phase. Each has its own topic and fresh input; no
conversation history is shared. Every request asks for an original 80–130-word
overview, four to six facts, credible supporting sources, and researcher
self-checks. The complete request payload and response are retained per topic.

The API key is read from the ignored, untracked, mode-0600 `.env` file. It is not
saved in request artifacts or logs. TLS certificate verification remains enabled.
The macOS system CA bundle resolved an initial pre-API certificate failure.

## Attempts, checks, and cost

An initial paid Viola preflight revealed citations without explicit page-open
actions. Its response is archived under `attempts/`. The prompt and validator
were tightened to require an `open_page` action for every cited reference, then
Viola was rerun once. The final 100-topic set uses this second prompt. Thus the
pilot includes 101 paid requests for 100 distinct topics, plus an unbilled TLS
setup attempt. Both paid preflights are included in the total cost estimate.

The per-reference open-action rule is stricter than the regular queue's
minimum of reading one credible source per topic. A missing action is a research
trace flag, not proof of a factual error. Checks also cover model and topic IDs,
word length, fact count, citation consistency, retrieval timestamps, unresolved
researcher concerns, and dataset preservation. Passing them is not an independent
factual endorsement. Raw drafts are kept even when checks fail; no silent repairs
or repeat generation are used to improve the reported success rate.

`audit-plan.json` preselects 12 topics for a limited factual and citation-support
assessment: one per represented category plus one extra science topic. This is
a pilot assessment, not a return to routine coordinator review of every draft.
The audit does not prove the accuracy of unexamined topics.

Costs use returned input, cached input, cache-write, and output token usage plus
recorded search actions. Reasoning tokens are already included in output tokens.
Current standard rates are $0.10/$0.01/$0.125/$0.50 per million tokens,
respectively, and $0.01 per search action. Page-open actions are not counted as
additional search fees. These are usage-derived estimates, not an invoice.
See [model pricing](https://developers.openai.com/api/docs/models/gpt-6-luna),
[tool pricing](https://developers.openai.com/api/docs/pricing), and the
[web search guide](https://developers.openai.com/api/docs/guides/tools-web-search).
The $30 pre-dispatch guardrail is a local estimate, not a server-enforced billing cap.

## Artifacts and resumption

- `responses/`: one saved final attempt per topic, including raw output and checks.
- `attempts/`: archived setup/preflight attempts; costs remain in totals.
- `summary.json`: completion, automatic validation, costs, and data-hash checks.
- `draft-content.json`: only drafts passing all automatic checks, normalized to
  site format; these remain unaccepted and unimported.
- `review.html`: all 100 drafts, old descriptions, facts, sources, and check flags.
- `audit-*.json`: the limited independent factual sample and supporting evidence.
- `REPORT.md`: completed pilot findings and cost projections.

Read-only status and rendering, from the repository root:

```sh
.venv/bin/python scripts/luna_topic_pilot.py status
python3 scripts/render_luna_pilot.py
```

The runner holds `.run.lock` while executing. Wait for it to finish before
requesting runner status; `summary.json` can be read while requests are active.
Existing response files are skipped on resume, including failed drafts.
Do not launch additional paid requests or erase responses to force retries.

The existing `enrich-remaining-study-topics` heartbeat was paused to avoid
overlapping Sol work. Leave it paused pending the user's pilot assessment.
No pilot IDs were claimed or accepted in the regular queue. Site JSON hashes
must match the manifest; student history and original detailed pages remain intact.

## Later status

After the pilot report, the user accepted its observed quality and authorized the
other 839 eligible two-source topics. All 100 pilot drafts and 839 subsequent
drafts, with targeted corrections applied to normalized copies, have now been
accepted into the site data. The historical pilot metrics and pre-acceptance
statements above describe the pilot at the time of its assessment. The local
Django import and preservation checks passed; see the subsequent run's
[completion report](../luna-two-source-2026-09-24/REPORT.md). No deployment has
occurred, and the Sol heartbeat remains paused.
