# Phase two: preferences and Study

The new Django landing page and Study flow implement the approved visual design:
charcoal background, light paper cards, muted gold, ten choices, and functional
copy. The first visit to the Scholars Bowl landing page prompts for interests.
Account contains the same selector. At least one active category is required.
Preferences apply to the next selection and preserve the current session.

## Learning rules

Study offers resume or start-over for an active session. The picker uses active,
uncompleted topics in the student's selected categories and avoids the previous
ten choices when the eligible pool permits. Completed topics are excluded; a
remaining pool below five produces a labeled shorter session.

Reading position is saved after each Back/Next action. Each topic contributes two
questions to the first quiz. Responses are saved individually; the score appears
after the attempt. The existing typed grader handles exact matches and spelling /
specificity prompts on the server. After the owner’s post-phase-four refinement, Study sends the pinned category
autocomplete candidates to the browser and restores fuzzy suggestion matching.
It does not label a candidate as correct. A saved response briefly shows Correct
or Incorrect, then advances after 1.2 seconds (Continue remains available without
JavaScript). Incorrect feedback never reveals the canonical answer or explanation. No browser JavaScript is required for the learning loop.

A failed quiz presents the deduplicated missed-topic list and requires rereading
those topics before retry. Retry priority is the preceding attempt's misses, then
unseen pinned questions, up to the original quiz size. Questions answered correctly
in any earlier attempt are excluded. Retries can be shorter; every attempt has
distinct questions and there is no retry limit. Passing requires 90% rounded up
using that attempt’s actual question count; 9/10 completes all five original topics, including the topic
behind a remaining miss. A passed short session counts once as well.

## Stored evidence and concurrency

- `StudyPreferences`: existing legacy goal plus category memberships/onboarding.
- `StudySession`: owned UUID, idempotency key, phase, reading position/version,
  original subject labels, review topic IDs, start/pass/abandon timestamps.
- `StudySessionTopic`: stable topic FK plus a reading-only content snapshot.
- `StudyQuestion`: complete original pool with protected question revisions and
  immutable grading banks. Imports cannot alter questions during a retry loop.
- `StudyAttempt` / `StudyAnswer`: ordered quiz composition, responses, timestamps,
  and server scores. Submitted answers are immutable through student endpoints.
- `TopicCompletion`: unique per student and stable topic ID, timestamped with the
  passing session. Current category/subcategory membership is used by the picker;
  separate records sharing a subject ID do not merge.
- `StudyActivity`: reading, quiz, and pass events ready for phase-three reporting.

All learning mutations lock the account before the session. A partial unique
constraint permits at most one active Study session per student. Start-over
abandons the referenced session, so an old tab cannot abandon a newer one.
Reading versions reject duplicate/stale navigation. Answers are sequential and
idempotent. Final grading, completion timestamps, and pass events commit together.
Creation holds the import read lock while capturing content and question banks.
Session rendering locks the session to avoid mixed-state pages during submission.

## Existing history and remaining work

Existing practice results, accounts, manual markers, rewards, and review evidence
are preserved. They do not grant new topic completion. History lists recent new
Study sessions above previous practice results. Canonical answer/explanation
output, source-question displays, and client autocomplete banks were removed from
legacy views as well. Legacy recognition/recall question displays and answer
reveals are retired; their stored results remain available. Existing typed
practice sessions can still be resumed separately.

Progress and Explore were subsequently connected to these records in phase three.
See [phase-three notes](SCHOLARS_BOWL_PHASE3.md) and the final
[validation record](SCHOLARS_BOWL_PHASE4.md).

## Rollout

Back up the target database using the existing deployment workflow, then run:

```sh
python manage.py migrate
python manage.py import_content
python manage.py collectstatic --noinput
```

Restart the Django application as described in `UPDATE_DEPLOYMENT.md`. Migration
`0007_studypreferences_categories_and_more` is additive; it creates no synthetic
completions. Current data import supplies the typed question format introduced in
migration `0006`. A subject with fewer than two available typed questions per
selected topic is rejected before any session is created. Short descriptions are
valid and are never excluded or rewritten.

Validation uses PostgreSQL (including real transaction races), importer round
trips, the existing Django suite, content tests, and JavaScript tests. Covered
boundaries include cross-device resume, interest changes, first-attempt balance,
retry priority/backfill, rounded short-session thresholds, shared-topic credit,
retirement/reimport snapshots, owner/CSRF checks, stale tabs, concurrent starts and
final answers, rollback, and new/legacy answer-key secrecy. Browser review covered
onboarding, reading → quiz → review → retry, and 320/390px layouts.

The working local review server runs on port 8878 using the disposable
`huddleston_study_preview` database and `.local/study_preview_settings.py`; it is
separate from the existing database and the static design preview on port 8877.
This local run is not a deployment. No production database was modified.
