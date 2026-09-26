# Final redesign validation

Completed locally September 25, 2026. All four redesign phases are implemented.
This records repository and isolated-preview validation; it is not a production
deployment or a student pilot.

## Fixes from this pass

- Study offers resume before checking whether the student's current interests
  are still active. Retiring selected categories cannot hide an existing pinned
  session. A subsequent new session still requires valid interests.
- Empty categories show “No study topics available”; “All selected topics
  complete” is reserved for scopes containing active study topics.
- Quiz inputs now associate their help and spelling/specificity prompt with the
  input through `aria-describedby`. Removed obsolete suggestion copy from legacy
  validation errors. Search/Account focus rings use dark gold on paper surfaces.
- Replaced obsolete README and deployment smoke-test instructions covering
  autocomplete, multiple-choice, and answer reveals. Current rollout guidance
  covers migration 0007, study/review/pass, topic completion, history, and rollback.

## Automated verification

| Check | Result |
| --- | --- |
| Django/PostgreSQL suite | 147 tests passed |
| Content/build/release/research tooling | 69 tests passed |
| JavaScript regressions | 9 tests passed |
| Django system check | No issues |
| Migration drift | No changes detected |
| Diff whitespace | Clean |

Coverage includes first-visit interests; selected-category filtering and
reshuffles; five-topic and shorter sessions; back navigation; cross-device resume
at reading, quiz, review, and completion; restart invalidation; grading prompts;
sequential answers; duplicate final posts; concurrent starts and final answers;
atomic rollback; deduplicated review and retry priorities; unlimited backfill;
90% thresholds; completion identity across memberships; retirement/import
snapshots; answer secrecy on new and legacy endpoints; ownership and CSRF;
account changes/deletion; empty coverage; Chicago week/DST boundaries; weekly goal
overflow; scoped search/pagination; breadcrumbs; and read-only Explore.

The final cross-page plain-form test resumes on a new authenticated client at
every question, fails a short quiz, rereads, retries, passes, repeats the final
submission, and checks exactly one pass in Progress and one topic completion.
The flow works through server forms without requiring browser JavaScript.

## Browser and full-library checks

The isolated Django preview uses the complete 7,072-topic library. Prior phase
checks covered 320px, 390px, and 1440px layouts, search, hierarchy, breadcrumbs,
onboarding, reading, failed quizzes, and retry. Final checks verified the 320px
passed-session screen and subsequent ten-card picker with no horizontal overflow,
keyboard activation of the history link and next action, and the live increase to
one weekly pass / five completed topics after finishing the disposable demo quiz.

The loaded stylesheet includes the reduced-motion override disabling all
animations and transitions with `!important`; this pass inspected that rule rather
than changing the user's OS preference. Core paper/dark text and category accents
were reviewed, and paper input focus contrast was improved. The completion
celebration is brief and its meaning is also stated as text.

Full-library measurements in phase three used five aggregation queries for
Progress and two for Explore's category cards, without per-row queries. They
rendered locally in roughly 200ms and 140ms respectively after query cleanup.
These are local observations, not classroom load guarantees.

## Backup and restore drill

Completed the existing `backup_database` / `verify_database_backup` workflow
against **only** `huddleston_study_preview`, using PostgreSQL 17. The backup
included interests, pinned Study records, failed/passed attempts, activity, topic
completions, full content, and existing schema. Verification restored into a new
temporary database, compared every public table's row count and checksum, checked
the administrator protection trigger, and removed only that temporary restore.
**All 33 tables matched.** The private dump/manifest remain under ignored
`.local/phase4-backups/`.

The main local database and production data were not migrated or modified.
The demo preview is at port 8878; the port-8877 static prototype is separate.

## Operator follow-through

Use UPDATE_DEPLOYMENT.md for the existing server, with a verified backup,
migrations, current content import, collected static assets, and service restart.
Run its updated browser smoke checks after rollout. Do not reverse migration 0007
or run older application code once new Study records exist.

Confirm actual-server HTTPS/service behavior, off-server backups/alerts, and a
small classroom pilot on real devices. Existing administrator student-statistics
pages intentionally retain legacy practice metrics; students' new Progress pages
show Study completions. That administrator reporting expansion is outside this
redesign. Short descriptions remain valid; no content enrichment is required.

## Subsequent owner-requested quiz refinement

Restored Study autocomplete after the final pass: the original fuzzy candidate
search, arrow-key navigation, and Tab/Enter completion use the session’s pinned
category bank. Scoring remains server-side. Finalized responses show a brief
Correct/Incorrect page with a 1.2-second automatic continuation and a plain-link
fallback. That page never contains the question’s canonical answer, an answer
bank, or an explanation; close-answer prompts do not save or advance.
This intentionally supersedes the earlier ban on all candidate-bank payloads.
33 targeted Django tests and five matching/widget/feedback JavaScript tests passed.
A browser check verified fuzzy matches for misspelled input, arrow-key and Tab
selection, and the 390px suggestion layout without horizontal overflow.

## Reroll and shorter retries refinement

The owner subsequently requested Reroll above the subcategory grid and retries
containing only misses and unseen questions. Previously correct questions are
excluded across the session's entire answer history; retries no longer backfill.
The display and passing threshold use each attempt's actual size (90%, rounded
up), while a successful retry still completes the original topic set once.
32 targeted Study/journey/Progress tests passed, including shrinking retries,
exclusion across several attempts, one-question retries, 9/10 initial passing,
and picker control order. Browser verification confirmed Reroll supplied ten new
choices without immediate repeats in the available pool.

## Unique quizzes and optional review after passing

The reported Tokenization repetition came from two differently worded questions
attached to separate topics. Initial selection now groups matching normalized
prompts or answers before random selection, aiming for two per topic and filling
overlaps from other unique pinned questions. Ten questions are retained whenever
the pool supports them; smaller pools produce shorter quizzes. Retries apply the
same grouping, so an already-correct variant cannot return as unseen. Saved
pre-fix attempts keep their scores; duplicate-only remaining misses can finish
after review without creating an empty retry.

Passing results now list topics behind remaining missed answers, linking to
optional pinned reading cards. These reads do not reopen quizzes or change
completion records. 38 targeted Django tests passed, including the two actual
Tokenization prompts, small pools, retry exclusion, and review authorization.
The local browser check confirmed that the saved 9/10 AI session shows Decision
Tree for optional review and returns to the same passed result.
