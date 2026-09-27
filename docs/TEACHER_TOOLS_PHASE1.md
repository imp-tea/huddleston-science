# Teacher question authoring — Phase 1

Implemented locally September 26, 2026. Production has not been changed. The
Teacher Tools landing page, student-progress expansion, quiz lists, and live games
remain later phases of [the plan](TEACHER_TOOLS_AND_LIVE_QUIZZES.md).

## Available behavior

- Administrator-only expandable Quiz Questions and Source Questions panels on
  Explore topic pages and current Study reading/optional-review pages.
- Typed question creation; typed and multiple-choice editing; accessible native
  disclosure menus; source questions and their attribution remain read-only.
- Shared question bank: newly created/edited questions and updated candidate banks
  apply to future Study sessions. Existing sessions and results keep pinned data.
- Imported baselines are separate from teacher overrides. Imports preserve edits
  and new questions, flag changed baselines, and retain content history.
- Restore Imported Version for edited imported questions; archive/restore for
  teacher-created questions. Retired topics exclude their questions from new pools.
- Optimistic edit versions plus database/content locks prevent stale writes.
  Duplicate creation submissions reuse the original request identity.
- Supplementary `export_teacher_questions OUTPUT` command writes a new private
  JSON file containing authoring evidence without student records.

The three-dot menu gains Add Question to Quiz in Phase 3; Phase 1 does not present
a nonfunctional quiz-list action.

## Migration and operations

Migration `0008_question_authoring` seeds each existing question's imported
baseline from its current revision, adds origin and override pointers, edit
versions, and optional revision authors. No content IDs or saved session references
are rewritten. Apply migrations before the updated application/importer.

Teacher work lives in PostgreSQL; full database backups are the recovery mechanism.
The JSON export is supplementary and is not accepted by `import_content`. Do not
run an older importer after this upgrade. Maintenance, README, and both deployment
guides describe this boundary. No new runtime dependencies or services are needed.

## Verification

- Full Django/PostgreSQL suite: **173 tests passed**, including the original 14
  authoring tests, in 188 seconds.
- Final focused authoring suite: **16 tests passed**, including two additional
  checks for migration backfill and admin/student Study-reading panel visibility.
- JavaScript suite: **11 tests passed** using the bundled Node runtime.
- Django system checks, migration drift check, and Git whitespace check passed.
- Browser preview verified sign-in, expandable questions, keyboard actions,
  question creation/editing, and return to an expanded panel. At 390 pixels the
  editor and expanded topic page have no horizontal overflow.

Authoring tests cover import preservation and baseline changes, archive/restore,
old versus new Study snapshots and banks, protected source data/escaped content,
authorization and CSRF, field validation, duplicate creation, stale/concurrent edits,
atomic rollback, export contents/file protection, and migration compatibility.

The broader standalone content/research suite ran 70 tests: **66 passed; four
failed in unchanged tests/scripts against the current dataset**. These are outside
Phase 1 and were not modified:

- `test_enrichment.EnrichmentTests.test_external_import_is_idempotent_and_recovers_prepared_state`:
  assumes an outstanding multi-topic enrichment batch; none exists after the prior
  full-content enrichment.
- `test_typed_question_pilot.TypedQuestionPilotTests.test_manifest_covers_population_and_preserves_all_data`:
  expects 69 sample topics; the current selection contains 57.
- `test_typed_question_pilot.TypedQuestionPilotTests.test_v4_same_sample_full_context_and_new_quota`
  and `test_v5_readable_context_preserves_sources_and_same_sample`: expect 201
  requested questions; the current selection requests 177.

`data/`, `scripts/`, and `tests/` have no changes from this task. Production and the
main local application database were not migrated. Browser verification uses the
separate `huddleston_authoring_preview` database on port 8881 with a small imported
content subset and disposable teacher examples.
