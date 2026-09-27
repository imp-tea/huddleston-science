# Teacher Tools and live quizzes

Implementation plan · September 26, 2026.

Phase 1 is implemented locally; see [implementation and validation notes](TEACHER_TOOLS_PHASE1.md).
Phases 2–6 remain planned. The owner confirmed that one administrator is sufficient.

## 1. Product direction and agreed decisions

Add teacher question authoring, reusable quiz lists, current student progress views,
and teacher-paced classroom games to Scholars Bowl. Target one teacher and roughly
30 students on the current 1-vCPU, 1-GB droplet.

The owner confirmed:

- Use one shared question bank. Teacher-created and edited questions become
  available to future individual Study sessions as well as teacher quizzes.
- Original players can rejoin an ongoing game after a refresh or connection loss,
  keeping saved answers. Leaving removes their live presence, not their results.

Other proposed first-release defaults:

- Existing signed-in accounts; one site-wide lobby or running game at a time.
  Students join through the Scholars Bowl home card, without a code.
- Live games use typed questions with the existing autocomplete and grading.
  No timers, speed bonuses, or public individual leaderboard.
- Only the host advances questions. Even when everyone has answered, the game
  waits for the teacher.
- Live results appear in history but do not grant Study topic completions or
  count toward the five-session weekly Study goal.
- Start with short polling on the existing Django/PostgreSQL stack. Load-test
  this before classroom deployment; WebSockets remain a later transport option.

These defaults make the requested team activity a complete first release. They
are recommendations, not additional decisions already approved by the owner.

## 2. Navigation and teacher experience

### Teacher Tools

Add an admin-only **Teacher Tools** link to the Scholars Bowl navigation and a
matching card to its home page. Keep the current dark shell and paper-card design.
The new section contains:

| Option | Behavior |
| --- | --- |
| View Student Progress | Select/search a student; view current Progress and recent history. |
| Quiz Creator | Create, edit, generate, and organize saved quizzes. |
| Host a Quiz | Select a saved quiz and open its waiting room. |

While a lobby or game exists, **Host a Quiz** becomes **Hosting Live Quiz** and
links back to it. After completion/cancellation, restore **Host a Quiz** and retain
the report in quiz history.

The repository currently enforces exactly one administrator through a database
constraint and protection trigger. Use the existing `is_admin` permission model;
supporting multiple teacher accounts is a separate account-model change, not a
prerequisite for these tools.

### Topic tools

On each Explore topic page, admins get expandable **Quiz Questions** and
**Source Questions** panels. Students receive neither panel nor its hidden data.

Quiz Questions displays stems, canonical answers, format, and editing status.
Each question has an accessible three-dot menu with **Edit Question** and
**Add Question to Quiz**. The latter opens a named-quiz selector with a successful
addition/already-added message. Provide an **Add New Question** button on the
panel; the topic association is automatic.

New questions default to typed format, with a required prompt and canonical
answer. Validate lengths against the existing 240-character response limit and
reject blank fields. Existing multiple-choice questions remain viewable/editable,
including choices and the correct choice, but cannot enter a typed live quiz.
Do not silently convert question formats. Reuse the existing grader; adding a new
accepted-alias system is outside this release.

Source Questions shows original tournament question text, answer lines, multipart
structure, and available tournament/round/question metadata from `Source.payload`.
Treat originals as read-only provenance. Editing a practice question never rewrites
the source question. Preserve citations and attribution. Offer these same teacher
panels on any other topic-reading surface used by admins through a shared partial.

Forms return to the relevant topic/quiz after saving. Menus and expanders must work
with keyboard, touch, and visible focus; authored text is escaped, not executable
HTML.

### Student progress

Reuse `coverage_rows()` and `calendar_progress()` from `scholars/discovery.py` and
the current Progress template with an explicit target student. Show whose record
is being viewed and offer a student switcher/back link.

Include recent Study sessions, statuses, dates, and scores, plus live quiz reports
once available. Keep older practice history accessible and labeled separately.
Admin history/detail routes must be read-only: viewing another student's records
must never impersonate the student or submit/advance their work.

The existing `student_progress` route uses legacy practice calculations. Update
its destination or provide a clear link to the new view so Admin and Teacher Tools
do not present conflicting definitions of progress.

## 3. Shared question bank and import protection

This is a prerequisite, not a later polish task. `scholars/importer.py` currently
sets every imported question's current revision and retires records missing from
JSON. Unmodified, it would overwrite teacher edits or reject/retire new questions.

Retain the existing stable `Question` identity and immutable `QuestionRevision`:

- Track whether a question is imported or teacher-authored. Generate namespaced
  IDs for authored questions; never use topic-local counters as global IDs.
- Track the latest imported revision separately from an optional teacher override.
  Keep `current_revision` as the effective revision consumed by existing Study.
- Editing creates a new immutable revision with author/time metadata. Use an
  expected-revision check so two open editing tabs cannot silently overwrite edits.
- Imports update the imported baseline, but preserve a teacher override. Flag
  baseline changes under an override for teacher review. Teacher-created questions
  are excluded from imported-question missing/retirement checks.
- Retiring an imported question removes it from new selection while preserving its
  revisions, override, and historical use. Retiring a topic also removes its
  authored questions from new selection; neither action deletes history.
- Serialize authoring and imports using the existing content advisory lock; update
  revisions, effective pointers, and affected autocomplete banks atomically.
  Existing sessions retain their pinned revision and bank.
- Make **Restore Imported Version** available for overridden imported questions.
  Use reversible archival for authored questions rather than deleting evidence.

JSON remains authoritative for the imported baseline. Production PostgreSQL
becomes authoritative for teacher authoring and saved quizzes. Update maintenance
and backup documentation accordingly; a fresh JSON import alone cannot reproduce
teacher work. Include an export command for authored questions/overrides as a
portable recovery artifact, alongside the existing full database backup.

Audit every selector that currently reads `Question.current_revision`, including
Study creation, typed banks, legacy practice, and random selection. An authored
question should enter future Study pools without changes to topic-completion rules.

## 4. Quiz Creator

A saved quiz behaves like a named list, separate from any particular live run.
Support create, rename, duplicate, archive, add/remove questions, and reorder.
Provide move-up/down controls so ordering does not depend on drag-and-drop.
Removing a question from a quiz does not delete it from the shared bank.

Each quiz displays its question count and an editable preview. Prevent the same
question ID from appearing twice. Flag different questions with duplicate wording
or answers for review; a teacher may deliberately keep such variants.

Saved items reference question identities and track the last reviewed revision.
They follow the effective bank revision for future runs. Before hosting, clearly
show changed or retired items: require review of changed content, and removal or
replacement of unavailable items. Never quietly shorten a quiz at launch.

### Random generation

Provide quiz name, one or more categories, optional subcategories, question count,
and optional maximum questions per topic. Offer **Balanced across categories**
(default) or **Sample across the whole selected pool**. First-release bounds:
1–100 questions, adjustable after testing.

Generate from active typed questions and effective revisions. Default to excluding
duplicate normalized prompts/answers using the existing Study grouping rules,
extracted into a reusable selector where appropriate. For balanced selection,
distribute counts as evenly as possible; disclose any shortage and proposed
redistribution. If constraints cannot supply the requested count, show the available
count and let the teacher reduce the request or relax filters. Never pad with
duplicates or silently return fewer questions.

Generation produces a preview that is saved explicitly as a normal editable quiz.
It samples existing questions; it does not require AI generation or an API key.

## 5. Live lobby, membership, and reconnection

Hosting creates a durable game and snapshots the quiz title, ordered question
revisions, topic/category context, autocomplete banks, and grading version. The
lobby's question count is therefore stable. Later quiz/bank edits affect future
runs, not this game. Enforce one open game with a database constraint and handle
duplicate Host submissions idempotently.

While the game is waiting:

- Students see **Join the Live Quiz!** as a fourth card at the top of Scholars Bowl
  home. Existing open home pages discover/remove the card through a lightweight
  status check, not only on refresh.
- Clicking it opens the live page and registers presence through a CSRF-protected
  POST. Merely fetching a link must not create membership.
- Everyone sees quiz title, question count, and currently present students using
  existing pseudonymous usernames.
- Only the host sees **Start the Quiz!** and **Cancel Quiz**. Starting with no
  students is disabled.
- Start atomically captures the currently present roster, opens question one, and
  closes admission. New joins racing Start either enter the roster before it locks
  or receive a clear "This quiz has already started" response.

After Start, remove the join card and deny new participants server-side. Original
roster members may return through a separate **Return to your live quiz** link or
the existing game URL. This recovery link is not an open invitation to late joiners.

Leaving the page removes live presence. Keep a clear **Leave Quiz** control and
notify the server on in-site navigation; use best-effort browser exit notification
and expiring presence leases for tab closure/network loss. Proposed tuning:
heartbeat every 5 seconds, inactive after 20 seconds without renewal. The roster
must distinguish active, reconnecting/away, and departed students; it must not claim
perfect instantaneous knowledge of browser closure. Browser exit events are not
reliable enough to be the sole mechanism ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/sendBeacon)).

Deduplicate students across tabs with per-page connection tokens and one participant
record per user/game. Closing one page must not remove another active page. A tab
visibility change alone is not a deliberate leave. Returning players keep their
answers and resume the current question; closed questions cannot be answered later.

If the host leaves, the game stays on its current question and accepts eligible
answers until the host returns. Show host-away status. Never automatically advance
or end because a browser disappeared. The host can resume or explicitly cancel/end
a stale game from Teacher Tools. Page refresh and service restart must recover from
database state.

## 6. Question and scoring rules

The game progresses through `waiting → running → finished`; a cancelled lobby has
no scored report. A running game can also be explicitly ended early, producing a
clearly labeled partial report.

Students see the current question, question number, autocomplete input, Submit,
and Skip. Reuse the Study suggestion widget, keyboard behavior, normalization, and
spelling/specificity prompt. A prompt is not a finalized answer: the student can
retry while the question remains open. Correct, incorrect, or skipped finalizes
their response and shows feedback plus **Waiting for the next question**.

The host sees the question and a tally such as **18 of 30 answered or skipped;
27 currently connected**, with per-student response status if expanded. Do not
put the canonical answer on the default host screen, since it may be projected.
Students receive only their own response/feedback and permitted aggregate status.

**Next Question** is always available to the host while a question is open; it
does not wait for all students. Display the number still unanswered beside it.
Advancing closes the old question, marks outstanding roster responses **No answer
before advance**, and opens the next. On the last question the control becomes
**Finish Quiz**. **End Quiz Early** is a separate confirmed action.

Important invariants:

- One finalized response per participant/question. First accepted response wins;
  duplicate POSTs, retries, and multiple tabs do not alter scores.
- Submit and Advance serialize on the same game row. A response saved before
  advance counts; one arriving after closure is rejected clearly. Client clocks
  do not determine acceptance.
- Host transitions include the expected question and game version plus a request
  ID. Double clicks or stale host tabs cannot skip two questions.
- A delayed response from an old question must not overwrite the browser's new
  question screen. Clients discard stale versions and resynchronize on conflict.
- Skipped and unanswered are separate report statuses, both worth zero. Score is
  one point per correct answer, with no speed component.
- Before finish, no student HTML, JSON, report endpoint, or preload contains a
  marked correct answer, future question, answer explanation, or another student's
  response. Autocomplete still includes unmarked candidate answers, as Study does.

## 7. Reports and history

Finishing closes the last question and makes reports available immediately and on
later visits. With roughly 30 × 100 responses at the upper proposed bound, ordinary
indexed database queries should suffice; no report job queue is planned initially.

Each student sees their private score and question-by-question response, status,
correct answer, and topic link for review. Canonical answers become visible only
after the live game ends. This is a new live-report behavior: current Study does
not actually reveal canonical answers after an incorrect response, so leave its
existing behavior intact.

The shared report leads with **Team coverage**:

`questions answered correctly by at least one roster member / questions presented`

For example: if somebody answered 18 of 20 questions correctly, team coverage is
**90%**, regardless of the average individual score. Also show questions nobody
answered, per-question correct counts, and optional category coverage. Label any
average student accuracy separately so it cannot be confused with team coverage.

Personal accuracy uses the same presented-question denominator, including skipped
and unanswered items. For a normal completed game this is the full quiz. For an
early finish, exclude questions never opened, include the current closed question,
and label **Partial quiz: 7 of 20 questions presented**. Never show unpresented
question answers in a partial report.

Keep the start roster as the reporting cohort even when players leave or reconnect.
Their accepted answers still contribute to team coverage. The teacher can inspect
all individual reports; students see only their own details and class aggregates.
No public individual ranking in this release.

Add live reports to student history and teacher quiz/run history. Retain frozen
content evidence when a quiz is renamed/archived or questions are edited. Existing
account deletion must still remove the student's personal responses and membership;
define aggregate reports as calculated from retained records and indicate when
account deletion has changed the available cohort, rather than retaining identifying
snapshots to bypass deletion.

## 8. Architecture and data model

Use existing Django templates, JavaScript, PostgreSQL, Caddy, and Gunicorn initially.
Untimed teacher-controlled questions tolerate a small synchronization delay, so
polling is a simpler fit than the earlier speed-oriented Kahoot recommendation.

Proposed implementation:

- Authenticated state GET every approximately 2 seconds on live pages, with jitter,
  one request in flight, timeout, and bounded retry backoff. Poll home-page lobby
  discovery less frequently (approximately 5 seconds) and immediately on focus.
- Compact state/version responses; send question/suggestion data only on question
  changes, not every poll. Fetch permitted candidate data separately and keep it
  in page memory; do not store session credentials in localStorage.
- Separate CSRF-protected POSTs for join, presence renewal, leave, answers, Start,
  Advance, Finish, and authoring. A GET must not renew presence or mutate gameplay.
- Server checks current account state, ownership, roster membership, phase, and
  expected version on every relevant request. Restrict private response caching.
- Database transactions/constraints are authoritative. No process-local game state,
  cross-request database locks, or sleeping/long-polling requests in sync workers.
- Keep game services independent of HTTP. If measured latency/load requires
  WebSockets, add Channels, ASGI, and Redis around these same services; send updates
  after commit and retain state resynchronization on reconnect.

Thirty live students polling every two seconds create approximately 15 state
requests per second, plus host, heartbeat, and answer traffic. This is a measurement
target, not a claim that polling is inherently cheaper than WebSockets. Keep reads
indexed and avoid loading all participants/answers for every student poll. Avoid
locking the game row for routine polling/presence renewals. Start resolves presence
and roster membership consistently with joins/leaves under the game transaction.

| Record/change | Responsibility |
| --- | --- |
| Question provenance/revision fields | Imported baseline, teacher override, origin, author, effective revision. |
| SavedQuiz | Owner, name, timestamps, archive flag, edit version, generation settings if applicable. |
| SavedQuizItem | Quiz, question identity, order, last reviewed revision; unique quiz/question and position. |
| LiveQuiz | Host, originating quiz, frozen title, phase, position, version, request IDs, start/end times and finish reason. |
| LiveQuizQuestion | Frozen revision, context, bank, grading version, position, opened/closed times. |
| LiveParticipant | Unique game/user, lobby membership, start-roster status and participation timestamps. |
| LiveConnection | Per-page lease and connection token tied to a participant; expiring presence, not scoring evidence. |
| LiveResponse | Unique participant/game-question, answer, final status, grading result and submission timestamp. |

Use database-enforced uniqueness for one open site-wide game, response identity,
and quiz order. Define consistent lock ordering, including the existing active
account lock, and test it against account disable/reset/delete operations. Validate
cross-record membership in the service layer; a posted response ID must never
grant access to another game or user.

Likely code areas: new `scholars/teacher_views.py`, `teacher_forms.py`,
`question_authoring.py`, `quiz_lists.py`, `live.py`, `live_views.py`, and
`live_reports.py`; model migrations; teacher/live template directories; a dedicated
live client script. Refactor small shared grading/suggestion/progress helpers rather
than copying Study orchestration wholesale.

Remove the Scholars Bowl home page's unconditional interest-setup redirect so
Teacher Tools and a live invitation can be reached before Study interests are set.
Keep onboarding at the Study entry point, with an appropriate home-page prompt.

## 9. Implementation phases and completion checks

| Phase | Deliverable | Complete when |
| --- | --- | --- |
| 1. Safe authoring | Provenance migrations, import changes, question/source panels, edit/create/archive/restore, bank refresh, export. | Teacher edits survive reimport; future Study uses them; existing sessions remain unchanged. |
| 2. Teacher Tools and progress | Navigation/home card, student selector, current progress and read-only history/details. | Teacher sees the same Study totals as the selected student; student access is denied. |
| 3. Quiz Creator | Named lists, add from topics, rename/remove/reorder/duplicate/archive, random generation and preview. | A teacher builds a quiz both manually and randomly, reviews changes, and sees its final order. |
| 4. Live game | Host selection, snapshots, lobby/card discovery, presence, roster lock, typed responses and manual advancement. | Multiple browsers join, play, leave, reconnect, and finish without losing accepted responses or revealing answers. |
| 5. Reports | Personal review, team coverage, teacher detail and history, partial-finish behavior. | Known sample answers produce exact personal/team results and survive later question edits. |
| 6. Classroom readiness | Regression/concurrency/browser/load tests, verified backup, deployment guide, small real-device pilot. | Target load passes on the actual deployment class and the teacher/student journey is verified. |

Each phase should leave an independently reviewable change. Authoring and list work
can ship before live hosting; expose Host only when the complete play/report flow
is ready. No production migration or server reconfiguration is part of this plan
writing task.

## 10. Validation and rollout

Test the failure cases that matter for shared state:

- Reimport after teacher edits/new questions; concurrent import/edit; changed bank
  suggestions; retired content and old session/report snapshots.
- Authorization on teacher forms, source panels, state APIs, reports, and direct
  URLs; account disable/password reset during a game; CSRF and answer secrecy.
- Duplicate/random pool selection, balanced-category shortages, stale quiz edits,
  changed question review, ordering and duplicate Host requests.
- Join racing Start; answer racing Advance; repeated Skip/Submit/Finish; two host
  tabs; old page leave events arriving after a new connection opens.
- Disconnect/reconnect, deliberate leave, multiple tabs, sleeping devices, host
  departure, restart, late join denial, and empty lobbies.
- Exact team-coverage math where different students answer different questions;
  missed/skipped/unanswered distinctions; partial finish; report privacy/deletion.
- Current Study grading/autocomplete/completion and Progress remain correct.

Use PostgreSQL transaction tests for concurrency, JavaScript tests for stale
responses/client state, and browser checks for the full teacher/student journey.
Check narrow screens, keyboard-only operation, focus preservation during updates,
and restrained accessible announcements. Teacher editing/progress forms can retain
normal HTML fallbacks; live participation requires JavaScript and should say so
clearly if it is disabled.

Load-test 40–50 simulated players with realistic question changes, category-sized
autocomplete payloads, simultaneous answers and reconnects, plus ordinary Study
traffic. Test the initial login burst separately because password hashing can be
more CPU-heavy than gameplay. Record actual memory, CPU, query counts, database
connections, errors, and end-to-end latency. Initial acceptance targets: no lost
accepted responses, no duplicate scoring, no out-of-memory restarts or sustained
swap pressure; p95 answer acknowledgement under 1 second and question propagation
under 3 seconds on a healthy test network. These are targets to verify, not measured
performance claims.

Retain the existing droplet for implementation/testing. If application/query tuning
cannot meet those targets, use the measurements to choose WebSockets and/or more
RAM. A 2-GB droplet is the first memory-headroom option; do not require it solely
because the class has 30 players.

Before production rollout, take and verify a database backup including authored
content, quizzes, and game records; migrate, run the current import, collect static
assets, and perform a teacher-plus-student smoke test. Update README, content
maintenance, deployment and backup guidance for the new database-authoritative
content. Pilot on a few actual school devices before a full-class game.

## 11. Useful later additions

Consider printable/exportable reports, a projection-only screen, explicit teacher
grading adjustments with an audit trail, saved random-generation presets, and
targeted review quizzes built from questions the team missed. Keep multi-room
hosting, guest accounts, timed/buzzer modes, AI question generation, and multiple
administrator support outside the first release.

## References checked for the plan

- [Django transaction row locking](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update)
- [Browser exit notification limitations](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/sendBeacon)
- [Channels deployment options](https://channels.readthedocs.io/en/stable/deploying.html)
- [Channels Redis channel layer](https://channels.readthedocs.io/en/stable/topics/channel_layers.html)

Repository grounding: `scholars/models.py`, `importer.py`, `study.py`,
`study_views.py`, `typed_answers.py`, `question_pools.py`, `discovery.py`,
`discovery_views.py`, `views.py`, `backups.py`, `accounts/models.py`, current Study
templates, and deployment configuration. These observations concern the checkout;
the production server was not inspected or changed.
