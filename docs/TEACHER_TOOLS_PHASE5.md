# Live quiz reports — Phase 5

Implemented locally September 26, 2026. Not deployed to the production droplet.

## Reports and history

Finished games now link to a persistent report. Revisiting a finished live page
opens that report directly. Students see their own score, each response and outcome
(correct, incorrect, skipped, or unanswered), the saved correct answer, and a topic
review link. Correct answers are available only after finish. Existing individual
Study feedback and completion rules are unchanged.

The shared summary leads with **Team coverage**: questions answered correctly by
at least one start-roster member divided by questions presented. Each question
counts once. Question review shows the number of correct players, including questions
with no correct answers; the summary also counts questions with no submitted or
skipped responses. Multi-category games include expandable category coverage.

The teacher's class report lists students alphabetically and links to their private,
read-only reports. Students cannot inspect another student's responses or see the
teacher's student list. Reports reject non-roster students, unfinished games, and
cancelled lobbies. All report/history pages are read-only GETs and inherit the
application's private, non-cacheable response policy.

Live results appear in student history, selected-student progress/recent history,
and selected-student full history. Teacher Tools and Host a Quiz link to paginated
live run history. Each saved quiz links to its own run history, including archived
quizzes. Waiting, running, cancelled, partial, and completed runs have distinct labels.

## Counting and retained evidence

- Personal accuracy includes skipped and unanswered questions in its denominator.
- Early endings include the current closed question and exclude every unopened
  question. Partial reports disclose the presented/full count; unopened prompts
  and answers are never included.
- Original roster members remain in results after leaving or disconnecting.
  Disabled accounts remain in the retained roster, but cannot sign in.
- Account deletion still cascades personal responses, presence, and membership.
  Team coverage recalculates from retained records. No identifying snapshots are
  added to bypass deletion.
- Migration `0011_live_roster_count` adds an anonymous original roster count,
  recorded atomically at Start. Reports disclose when fewer records remain.
  Older games deliberately retain a null baseline: their historical original
  roster cannot be reconstructed reliably after earlier account deletion, so
  reports explicitly state that limitation rather than inventing a count.
- Title, prompt, answer, topic label, and category come from the game's frozen
  evidence. Bank edits, quiz renames/archive, and topic retirement do not rewrite
  reports. Topic links open the current library; unavailable topics retain their
  saved question and answer with an explanatory label.
- Reporting uses bounded aggregate queries over persisted game records. No new
  service, dependency, worker, or background report job was added.

## Deployment

Back up PostgreSQL, apply migration `0011_live_roster_count` (and any earlier pending
migrations), collect static files, and restart using the existing deployment process.
Only the isolated `huddleston_authoring_preview` database was migrated during local
verification. Production data and server configuration were not changed.

Smoke-test separate teacher/student sessions through finish, open detailed reports,
and revisit them from history. Check an early finish excludes unopened questions,
and that a student cannot open another student's report. Keep the original roster
column during a code rollback so deletion disclosures remain accurate.

Phase 6 remains: load testing for approximately 30 players on the current droplet,
deployment preparation, and a small classroom pilot.

## Verification

- Full Django suite: all 240 tests passed.
- System checks, migration drift check, and `git diff --check` passed.
- 45 focused live-game, report, and teacher-progress tests passed.
- 15 new report tests cover exact scores/coverage, all four outcomes, category
  totals, partial endings, account deletion, unknown historical cohort sizes,
  disabled players, frozen content, private access, pagination, read-only requests,
  bounded query counts, and finish/history navigation.
- All 14 JavaScript tests passed.
- Browser verification used separate teacher/student sessions on the isolated
  preview database. A two-player sample showed 67% team coverage with 33% personal
  accuracy for each player; student history, teacher history, and selected-student
  report navigation were checked. Screenshot: `.local/phase5-live-report.png`.
