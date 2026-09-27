# Teacher Tools — Phase 2

Implemented locally September 26, 2026. Not deployed to the production droplet.

## Available features

- Admin-only Teacher Tools navigation and Scholars Bowl landing card. Administrators
  can reach the landing page without first setting personal Study interests.
- Teacher Tools hub with View Student Progress. Quiz Creator and Host a Quiz are
  clearly marked as upcoming; they become functional in later phases.
- Searchable, paginated student roster, including disabled accounts and accounts
  that have not finished setup.
- Current student Progress using the same weekly goal, activity calendar, and topic
  completion calculations as the student's own page, plus recent saved history.
- Full paginated Study history and previous practice results. Study details show
  saved question revisions, every quiz attempt, student responses, correct answers,
  and correct/incorrect/skipped/unanswered outcomes. Previous typed, recognition,
  and self-assessed recall results remain readable.
- The existing Admin student page's progress link opens this current report. Older
  practice statistics remain available through a separately labeled link.

## Permissions and data behavior

Report routes require the existing administrator permission and accept GET only.
Each detail lookup is scoped to the selected student. Pages identify whose records
are being viewed and contain no student learning controls. Viewing unfinished
sessions never impersonates students, advances reading, grades answers, records
activity, or grants completions. Students cannot access these teacher reports.

History queries annotate scores in the database, and attempt details fetch only
the selected page's answers. Large tournament-source contexts are excluded from
answer-detail queries. No new models, migrations, packages, background workers,
or infrastructure are required. Phase 1 migration `0008` is still required if it
has not already been applied.

## Validation

- All 186 Django tests passed (`accounts scholars classroom` with
  `classroom.test_settings`), including 11 new teacher-report tests.
- Focused reporting/progress/review run: 58 tests passed.
- Coverage includes permission failures, student/session scoping, GET data
  immutability, POST rejection, parity with student progress, zero scores,
  unfinished and abandoned sessions, pagination/search, disabled accounts,
  empty states, and bounded history query counts.
- Browser checks on an isolated local preview database verified the hub, student
  search, progress, full history, and saved attempts, including a failed first
  attempt followed by a passed retry. Desktop and 390px mobile layouts checked.
- System checks and migration drift checks pass. No schema changes.

Production data was not used for browser fixtures or modified. The preview uses
the separate `huddleston_authoring_preview` database with sample accounts.

## Next phase

Phase 3 adds reusable quiz lists and random quiz generation, plus Add Question to
Quiz from topic pages. Live hosting and student participation follow in later
phases; this change does not start live games.
