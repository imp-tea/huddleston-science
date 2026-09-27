# Study content and local research

`data/` is the versioned source of truth for imported classroom content. Teacher
question edits and new questions are authoritative in PostgreSQL; see below. Study
paragraphs, facts, supporting URLs, reference titles, publishers, and available
license/retrieval metadata are retained in `data/content.json`. Tournament
questions and their attribution remain in `data/sources.json` and `data/topics.json`.
The application and its importer do not read `research/`.

## Teacher question authoring

The administrator can expand **Quiz Questions** on topic pages to create typed
questions and edit existing typed or multiple-choice questions. Question type and
topic identity cannot change through the editor. Multiple-choice questions retain
four distinct choices and an explanation. New typed answers are limited to 240
characters to match the existing response field. **Source Questions** exposes
original tournament text and answers to the administrator only, as read-only
provenance.

Every content edit creates or reuses an immutable revision. The effective revision
is used by new Study sessions and, later, saved teacher quizzes. In-progress
sessions keep their old revisions and autocomplete banks. Teacher edits refresh
the affected category's bank in the same transaction. Conflicting edits from an
older tab are rejected instead of overwriting a newer change.

Imports update a separate imported baseline. A teacher override stays effective;
if the baseline changes, the topic panel flags it for review. Open **Edit Question**
to compare and save your version, or **Restore Imported Version** to use the latest
baseline again. Original sources and JSON files are never rewritten by the editor.
Teacher-created questions use reserved `teacher-<uuid>` identities and are excluded
from import removal checks. They can be archived/restored locally. Retiring an
imported question or its topic removes it from new selection but preserves history.

After authoring is introduced, JSON plus Git is no longer a full backup of the
question bank. The existing PostgreSQL backup/verified-restore workflow includes
all authoring fields and revisions. For a supplementary portable export:

```sh
python manage.py export_teacher_questions /existing/private/directory/questions-2026-09-26.json
```

The command exclusively creates a mode-600 JSON file and refuses to overwrite an
existing file. It includes authored questions (including archived ones), edited
imported-question histories, effective/baseline/override pointers, timestamps,
author IDs, and pinned source context. It excludes student accounts and responses.
Keep exports outside tracked `data/`; this schema is not accepted by `import_content`.
Restore the complete database backup for normal recovery. There is no automatic
merge/import tool for these supplementary exports in Phase 1.

## Saved quizzes

Saved quiz names, ordered question identities, reviewed revisions, archive status,
and generation settings are stored in PostgreSQL (migration `0009`). Imports do
not rewrite lists. Items follow the question bank's effective revision and flag
changed or retired content for teacher review. Duplication preserves review status.
Archiving a list or removing an item never deletes bank questions or revisions.

The full database backup includes saved lists. For supplementary portable evidence:

```sh
python manage.py export_saved_quizzes /existing/private/directory/quizzes-2026-09-26.json
```

This command creates a new mode-600 JSON file and refuses overwrites. It contains
active/archived quizzes, their exact order, settings, and both reviewed and current
question evidence, with no student records. It is not an `import_content` input or
an automatic restore format. Keep these exports private and outside tracked data.

## Imported question and reading content

The approved typed/recall question bank is versioned in
`data/typed-questions.json` (15,947 questions). Original multiple-choice questions
remain unchanged in `data/practice/` (10,976 questions). The importer validates
both banks before writing, preserves stable IDs and pinned sessions, and rebuilds
category autocomplete banks from current typed answers. A complete typed bank
must cover every topic with 2–5 questions based on its source count. The raw
generation/correction history remains local under ignored `research/typed-questions/`;
the published site requires none of it. Runtime generation is not performed.

As of September 26, 2026, all 7,072 topics have expanded study content:
2,335 existing detailed pages and 4,737 new paragraph-only descriptions.
The latter were generated with GPT-6 Sol, low reasoning, and no tools through
the Batch API. Every request included one original tournament source and two
approved typed quiz questions, along with topic metadata and its descriptor.
Existing pages, topic descriptors, source questions, and both quiz banks were
preserved.

Paragraph-only entries have one overview block, an empty `key_facts` list, and
`source.kind = "model_generated"` with model/date provenance, no references,
and `web_search_used = false`. Do not attach invented citations or imply that
these entries received external research. All 4,737 outputs passed basic
structural checks; the full set has not received a factual or quiz-coverage audit.
The six-topic pilot received a separate source review. Full-batch generation
cost was estimated from usage at $5.755255, not reconciled to an invoice.
The frozen requests, original responses, and import ledger are retained locally
under `research/topic-enrichment/sol-no-tools-batch-2026-09-26/`.

## Local-only workspace

The complete enrichment workspace remains at `research/topic-enrichment/` on
the maintainer's machine, but is ignored by Git and excluded from releases.
It includes the durable queue, assignments, response traces, evidence notes,
normalization snapshots, exact corrections, cost summaries, and security cleanup
ledger. This workspace is approximately 83 MB and is not a runtime dependency.

Keep a separate private backup if these records need to survive loss of the
maintainer's machine. A new clone does not include them. Existing older Git
commits still contain earlier copies; untracking files does not purge history.
The production package deliberately contains neither research files nor Git
history. Do not use `git add -f` to reintroduce local research artifacts.

The original 2026-09-24 queue and Luna run manifests must be restored together
with their response/result files to resume that exact research history. Keep
their relative paths intact. The paused continuation schedule must not be
resumed on a machine that lacks its workspace.

```sh
python3 scripts/enrich_topics.py status
```

Without a local queue, `status` reports coverage from the authoritative data.
`init` explicitly starts a new queue from topics still missing content and
protects all currently detailed pages; it does not reconstruct previous research
or authorize API spending. Do not initialize over the existing research history.

## Research and acceptance

Research instructions for the existing queue are retained in the local
`research/topic-enrichment/README.md`. For future work using the externally researched workflow (the authorized no-tools batch above is a separate workflow):

- Give each researcher the exact topic ID, category, and original question context
  for disambiguation. Question text is context, not verified evidence.
- Search the internet and directly read credible sources. Write an original
  80–130 word paragraph and four to six facts suitable for ages 12–18.
- Support every block with listed reference URLs and evidence notes. Verify or
  remove uncertain claims; attribute traditions, interpretations, and disputes.
  Respect source-specific summary/quotation limits and do not invent licenses.
- The accepted review policy uses researcher self-checks and automatic validation,
  with targeted investigation of concerns and failures. Do not claim an independent
  factual audit unless one actually occurred.
- Accept through the queue/integration helpers, validate the complete dataset,
  and use `manage.py import_content` to preserve student history and pinned revisions.

The Luna run used one independently researched topic per request. The pilot had
a separate 12-topic audit; the full 939-topic set did not. Known factual and
citation corrections were applied before import. API usage for the pilot and
subsequent run was estimated at $20.64, not reconciled to an invoice. The subsequent one-source Batch run was separately authorized and is documented above.

## Credential hygiene

Web search can return signed third-party download URLs. The writer strips AWS
signing material before saving or returning responses. Normalization and
integration reject unsanitized records and flag changed research citations for
source repair. The earlier signed-URL cleanup changed search traces only;
generated topic text, accepted citations, and usage records were preserved.

Run `python3 scripts/scan_research_credentials.py` before committing, and add
`--staged` to scan the staged snapshot. The scanner checks repository files, not
the ignored local research archive or old Git history. Never commit `.env`, keys,
database dumps, or student records. Source attribution stays in the public data;
raw provider traces do not need to be public.
