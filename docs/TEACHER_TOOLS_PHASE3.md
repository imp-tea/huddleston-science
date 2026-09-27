# Quiz Creator — Phase 3

Implemented locally September 26, 2026. Not deployed to the production droplet.

## Teacher workflow

Open **Teacher Tools → Quiz Creator** to create an empty named quiz or generate a
random preview. Saved quizzes support rename, duplicate, archive/restore, question
removal, and keyboard/touch-accessible move-up/down ordering. Lists are capped at
100 questions. Removing an item does not delete its question from the shared bank.

In **Explore**, expand a topic's **Quiz Questions** and choose **Add Question to
Quiz** from a typed question's three-dot menu. Choose an active quiz to add it;
the same question identity cannot appear twice. Multiple-choice questions remain
editable in the bank, but are excluded from these typed classroom quizzes.

The quiz page shows current prompts and answers. **Edit Question** saves to the
shared bank and returns to the quiz. Changes are flagged until **Mark Reviewed**
is pressed for that exact revision. Previous wording remains available for
comparison. Unavailable questions stay visible until removed or restored; they
are never silently dropped. Copying a quiz preserves its outstanding review flags.
Matching normalized prompts or answers are flagged, but teachers may deliberately
keep variants in manually assembled lists.

## Random generation

Choose a name, categories, optional subcategories, 1–100 questions, an optional
per-topic maximum, and balanced-category or whole-pool sampling. If subcategories
are selected, the pool is restricted to those subcategories, and each must belong
to a selected category. Duplicate exclusion defaults on and uses the same connected
prompt/answer grouping as Study, now extracted into `question_selection.py`.

An augmenting-path selector respects duplicate groups and per-topic limits even
when a group spans multiple topics/categories. Balanced generation starts with
nearly equal category quotas and redistributes unfillable shares incrementally.
The preview discloses requested and actual category counts before saving. If the
request is impossible, it reports the available count without creating a quiz or
padding with duplicates. No AI service or API key is used.

A preview is read-only until **Save This Quiz**. Its signed, account-bound payload
pins the exact ordered identities/revisions for one hour. Saving validates current
availability and revision equality; changed or retired items require a fresh
preview. Repeated successful saves create one quiz. Once saved, it behaves like
any other editable list. Generation settings remain stored with the quiz.

## Data and concurrency

Migration `0009_saved_quizzes` adds `SavedQuiz` and `SavedQuizItem`. Database
constraints enforce unique question identities and positions per quiz. Position
uniqueness is deferred to transaction completion to permit atomic reorderings.

Writes lock the active administrator account, then the shared content advisory
lock, then the quiz. Expected edit versions reject stale tabs; review/add actions
also verify the exact question revision displayed. GET requests do not mutate
lists. Student access and cross-owner list access are denied. Every mutation uses
POST and CSRF protection. Future hosting can use `ready_items()` under its content
lock to reject empty, archived, unreviewed, or unavailable lists before snapshotting.

## Deployment and recovery

Back up PostgreSQL, apply migrations, collect static files, and restart the updated
application. No new dependencies or services are needed. Migration `0009` has been
applied only to the isolated local preview and automated test databases. Keep its
tables if rolling back application code; reversing this migration drops saved lists.

Full database backups protect lists, teacher authoring, and student data together.
`python manage.py export_saved_quizzes /path/to/new-quizzes.json` creates a private,
non-overwriting supplementary JSON export with active/archived lists, order,
settings, and reviewed/current question evidence. It contains no student records.
It is not an input for `import_content` or an automatic restore mechanism.

## Validation

- Full Django suite (`accounts scholars classroom`): all 206 tests passed, including
  20 new quiz-list/generation/concurrency tests.
- Focused quiz-list, Study uniqueness, and teacher-progress suite: 37 tests passed.
- Django system checks, migration drift check, and `git diff --check` pass.
- Tests cover permissions/CSRF, cross-list IDs, stale versions, concurrent tabs,
  duplicate adds, ordering, archive/restore, revision review, duplicate warnings,
  generation quotas and topic limits, constrained matching, exact shortages,
  preview tampering/expiry/staleness/replay, export, and read-only GET behavior.
- Browser verification used the separate `huddleston_authoring_preview` database:
  manual creation and topic-menu addition, generation with disclosed redistribution,
  explicit save, question reordering, shared-bank editing and review, and a 390px
  mobile layout. No production records were changed.

Host a Quiz remains marked as upcoming. Phase 4 adds live lobby/game orchestration;
this phase does not start games or display student join cards.
