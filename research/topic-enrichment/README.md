# Topic enrichment

The user authorized the full backlog on September 24, 2026, using GPT-6 Sol
(`gpt-6-sol`) subagents, small topic batches, and internet-grounded research.
The starting inventory was 7,072 topics, 1,006 detailed pages, and 6,066 missing
pages. The queue has 612 batches of at most ten topics. Related subjects in
different categories remain separate topics and must fit their category context.

The coordinator uses up to three GPT-6 Sol researchers concurrently. Spawn them
with the explicitly requested model and a fresh context (`fork_turns="none"`), or
reuse existing Sol researchers. Researchers own factual and source checks; the
coordinator validates batches and investigates reported problems before acceptance.
At the user's request on September 24, 2026, routine coordinator prose review,
peer review, and independent source sampling are no longer required.
The regular queue uses Codex subagents. On September 24, the user separately
authorized a 100-topic API pilot using `gpt-6-luna`, with one topic per independent
request and the existing ignored `.env` key. After accepting the pilot's observed
quality, the user authorized the remaining 839 unenriched topics with at least
two original tournament sources using the same process. See
[`luna-pilot-2026-09-24/README.md`](luna-pilot-2026-09-24/README.md). This does not
authorize an API run of the remaining one-source backlog or introduce an AI
service into the website. The continuation run is documented in
[`luna-two-source-2026-09-24/README.md`](luna-two-source-2026-09-24/README.md).

A continuation schedule named **Enrich remaining study topics** is attached to
the originating Codex task, with automation ID `enrich-remaining-study-topics`.
It resumes one wave of up to three batches, validates and imports accepted work,
and stops when coverage is complete. The schedule is currently paused for the
Luna run; inspect its saved configuration for the current interval and status.
Luna outputs are accepted only through the dedicated validated integration
helper, including honest API provenance and partial-batch queue reconciliation.
A future heartbeat must not regenerate externally accepted Luna topics. The local
project, running desktop app, and network must remain available. Inspect the
existing automation before changing it; do not create duplicate schedules.

## Credential handling

Web-search results can contain signed download URLs even when no personal
credential was supplied to the source site. The Luna writer now removes AWS
signing parameters before saving or returning records. Normalization and
integration reject unsanitized material and require reviewed source repair if
redaction affected generated research content. Artifact hashes identify the
saved, potentially sanitized bytes. See [the cleanup report](SECURITY-CLEANUP.md).

Before committing research artifacts, run:

```sh
python3 scripts/scan_research_credentials.py
python3 scripts/scan_research_credentials.py --staged
```

The first checks working files; the second checks the staged snapshot. Results
show file paths and counts only. These checks do not purge historical commits.

## Resume and assign

From the repository root:

```sh
python3 scripts/enrich_topics.py status
python3 scripts/enrich_topics.py claim --worker researcher-name
```

`claim` returns the exact assignment and results paths. Each researcher owns only
that result file. The assignment includes the topic, category, aliases, short
description, and original tournament questions for disambiguation. These clues
are context, not verified evidence. Do not change quizzes as part of enrichment.

If a prior worker was interrupted, inspect its assignment and existing output
before resuming. Reuse its worker name to reclaim unfinished work. Do not release
a batch while its researcher is active. The helper serializes claims and accepts
using a file lock. No automatic expiration reassigns active work.

## Researcher instructions

For every assigned topic, use internet search and actually read at least one
credible source; aim for two independent sources when feasible. Prefer official
institutions, universities, museums, archives, authors, publishers, primary texts,
and government educational material. Technical/scientific claims must rely on
primary or official educational sources. Search snippets alone are insufficient
for an entire topic. If a source cannot be opened, find another readable source
and record the limitation honestly. Never invent a citation, retrieval time,
license, or evidence claim.

Write one original paragraph of 80–130 words (validator tolerates up to 150) and
4–6 concise facts for ages 12–18. Explain what the topic is, its significance,
and useful distinguishing facts. Keep the prose readable and avoid padding,
repetition, quiz-writing commentary, or instructions about how the page was made.
Every overview claim needs evidence, just as every key fact does. Verify or remove
uncertain claims; a caveat in the research notes does not excuse unsupported copy.
Attribute religious narratives to their tradition/text, distinguish disputed
historical interpretations, and avoid volatile statistics unless essential and
dated. Respect source-specific paraphrase/quotation limits across the whole batch.

Write a JSON object with the assigned `batch_id`, `topics` keyed by exact topic
ID, and `research` keyed by the same IDs. Each `topics` entry has:

- `overview`: one block with `id: "o1"`, `text`, and supporting `source_urls`.
- `key_facts`: blocks with sequential IDs `f1` … `f6`, `text`, and supporting
  `source_urls`.
- `source.references`: one entry per cited URL, with the actual `title`, `url`,
  `publisher`, and UTC ISO `retrieved_at`. Include `license` and `license_url`
  only together and only if verified. Omitting them does not grant a license.

Each `research` entry contains `queries` (actual searches), `sources` (objects
with `url` and precise `supports` evidence/section notes), and `notes` for
uncertainty or problematic source clues. Every reference must have evidence notes;
every block URL must be a listed reference. Initial accepted result files provide
examples of this format.

Save to a temporary file, then rename atomically to the assigned results path
only when all assigned topics are complete. As part of writing, check factual
support, topic identity, attribution, and source-specific summary limits. Resolve
problems you can fix and clearly flag any remaining concern in your completion
message. Do not ask another worker to perform a routine second review. Validate
and report completion:

```sh
python3 scripts/enrich_topics.py validate --batch BATCH_ID
```

## Validate and integrate

Trust the researcher's completed factual and source checks. Read the completion
report and run the validator; do not routinely reread every paragraph or evidence
note, assign peer review, or reopen source samples. The existing automatic checks
cover assignment IDs, paragraph length, fact counts, citation presence and
reference consistency, research records, and preservation of existing content.

Investigate only concerns the researcher flags, validation failures, or concrete
problems noticed during integration. Ask for targeted fixes when needed. Automatic
validation checks structure and integrity, not factual truth; factual grounding
remains the researcher's responsibility. Record the actual acceptance basis in
the existing review fields, without claiming an independent factual review:

```sh
python3 scripts/enrich_topics.py accept --batch BATCH_ID --reviewer coordinator --notes 'Researcher self-check reported complete; automatic validation passed; no unresolved issues reported. No independent factual review.'
```

Adapt the notes when a reported issue required a targeted check or correction.

Acceptance refuses conflicting existing content, preserves hashes of all 1,006
original pages, validates the complete merged dataset before writing, and records
the accepted result hash. It can be retried after interruption. The original
import manifest remains a historical snapshot; it is not rewritten to new counts.

After accepting a wave, run `python3 -m unittest discover -s tests` and the Node
tests. Use the bundled Node executable if `node` is absent from PATH. Import into
the local application with `.venv/bin/python manage.py import_content`; existing
quiz sessions retain their pinned historical revisions. Only import validated,
accepted content. Do not deploy or publish as part of this task.

For code changes to this workflow, also run the focused importer/history checks:

```sh
.venv/bin/python manage.py test scholars.tests.ImportTests scholars.tests.FullContentTests --settings=classroom.test_settings --noinput
```

Completion means all queued topics are accepted, all 7,072 topics have complete
study content, all original pages are unchanged, validation passes, and the local
application has imported the final data. Until then, report the actual accepted
count and remaining count; do not describe the full backlog as finished.
