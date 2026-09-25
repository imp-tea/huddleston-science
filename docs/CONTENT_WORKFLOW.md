# Study content and local research

`data/` is the versioned source of truth for the classroom application. Study
paragraphs, facts, supporting URLs, reference titles, publishers, and available
license/retrieval metadata are retained in `data/content.json`. Tournament
questions and their attribution remain in `data/sources.json` and `data/topics.json`.
The application and its importer do not read `research/`.

The approved typed/recall question bank is versioned in
`data/typed-questions.json` (15,947 questions). Original multiple-choice questions
remain unchanged in `data/practice/` (10,976 questions). The importer validates
both banks before writing, preserves stable IDs and pinned sessions, and rebuilds
category autocomplete banks from current typed answers. A complete typed bank
must cover every topic with 2–5 questions based on its source count. The raw
generation/correction history remains local under ignored `research/typed-questions/`;
the published site requires none of it. Runtime generation is not performed.

As of September 24, 2026, there are 7,072 topics and 2,335 detailed study pages:
1,006 original pages, 390 GPT-6 Sol additions, and 939 GPT-6 Luna additions.
The remaining 4,737 topics each have one original tournament source ID. All
previously unenriched topics with at least two source IDs have been enriched.
Original topic IDs, questions, and existing study pages were preserved.

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
`research/topic-enrichment/README.md`. For future work:

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
subsequent run was estimated at $20.64, not reconciled to an invoice. No further
API generation is currently authorized for the one-source backlog.

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
