# Huddleston Science

The approved Scholars Bowl redesign is tracked in
[the redesign plan](docs/SCHOLARS_BOWL_REDESIGN.md). **The redesign is implemented in Django:** saved category interests, a ten-subject picker, reading sessions, typed
quizzes, targeted review/retries, and timestamped topic completions. Home, Account,
Study, Progress, and Explore use the approved dark shell and light paper cards.
Progress includes a five-session weekly goal, activity calendar, and topic
coverage; Explore provides category/subcategory browsing and topic search.
See [phase-two rollout notes](docs/SCHOLARS_BOWL_PHASE2.md) and
[phase-three implementation notes](docs/SCHOLARS_BOWL_PHASE3.md).

Run migrations and import the current typed-question data before using Study:
`python manage.py migrate` then `python manage.py import_content`. Existing
accounts and practice results are retained; old results and manual study markers
are not converted into new topic completions. Final validation and polish are recorded in the phase-four notes below.

The separate phase-one design preview remains available with
`python3 prototypes/scholars-bowl/serve.py` at
[port 8877](http://127.0.0.1:8877); it uses sample progress and resets on refresh.

A Django/PostgreSQL classroom site with private, pseudonymous accounts and persistent Scholars Bowl practice. The complete journey is: administrator creates a student → student replaces a temporary password → completes a quiz → returns to saved results on another device.

The original static site and educational content pipeline remain available. The Django application is now the classroom website; static `dist/` output does **not** include accounts or saved results. For the existing server, use the [Git checkout update guide](UPDATE_DEPLOYMENT.md).

## Local setup

Requires Python 3.10+ and PostgreSQL 14+ (PostgreSQL 17 is used by the supplied Compose service). Node.js 18+ is needed for the JavaScript tests. Runtime dependencies are pinned in `requirements.txt`: Django 5.2.17 LTS, psycopg 3.3.6, and python-dotenv 1.2.2. Django's [supported release table](https://www.djangoproject.com/download/#supported-versions) lists 5.2 LTS security support through April 2028.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp -n .env.example .env
python - <<'PY'
from pathlib import Path
import secrets
p = Path('.env')
p.write_text(p.read_text()
    .replace('replace-with-a-random-secret', secrets.token_urlsafe(64))
    .replace('replace-with-a-local-database-password', secrets.token_urlsafe(32)))
p.chmod(0o600)
PY
docker compose up -d --wait db
python manage.py migrate
python manage.py import_content
python manage.py bootstrap_admin classroom-admin
python manage.py runserver 127.0.0.1:8000
```

Open [localhost:8000](http://127.0.0.1:8000). `bootstrap_admin` prompts twice for a password without echoing it. There are no default credentials. Keep `.env`, database files, and passwords out of Git. `DJANGO_DEBUG=1` is for local development only. Environment variables override `.env` values.

If PostgreSQL is already installed, skip Compose and set the `POSTGRES_*` values in `.env` for a dedicated database and role. The test runner needs permission to create a test database (`CREATEDB`); the Compose development role has it. PostgreSQL is required for row locks, import locks, and the administrator protection trigger; SQLite is intentionally unsupported.

The Compose database binds only to localhost and persists in a named volume. `docker compose stop` stops it without deleting records. Do not use `docker compose down -v` unless you intend to erase that local database.

### This workspace's validation environment

This machine had neither Docker nor PostgreSQL installed. Validation used the official Postgres.app 2.9.6 PostgreSQL 17 binaries copied into ignored `.local/Postgres.app`, a cluster in `.local/pgdata`, and generated secrets in ignored `.env`. It listens on `127.0.0.1:55432`. The full dataset is imported; no administrator or student credentials are seeded in the main database. Run `bootstrap_admin` above to choose your own credentials.

To restart that existing local cluster after a reboot:

```sh
.local/Postgres.app/Contents/Versions/17/bin/pg_ctl \
  -D .local/pgdata -l .local/postgres.log \
  -o '-p 55432 -h 127.0.0.1 -k /tmp' start
```

To stop it, use the same `pg_ctl` executable with `-D .local/pgdata stop`. New checkouts should use Compose or their own PostgreSQL installation.

## First classroom journey

1. The administrator creates a pseudonymous student account in **Admin** and delivers its temporary password outside the site.
2. The student signs in and replaces the temporary password, then opens **Scholars Bowl** and chooses at least one category of interest.
3. **Study** offers ten random subcategories, with **Reroll** above the cards to choose another set. Choose one, read up to five unfinished topics, and answer two typed questions per topic.
4. Responses save individually. A spelling/specificity prompt lets the student try again; **Skip** records an incorrect response. Fuzzy autocomplete offers category-wide candidates as you type; arrow keys and Tab/Enter select a suggestion. Each finalized response briefly shows Correct or Incorrect without revealing the correct answer after a miss. A failed quiz requires rereading missed topics before another shuffled attempt.
5. A score of at least 90% (rounded up for shorter sessions) completes every topic in that session. **Progress** shows topic coverage, a fixed five-session weekly goal, and five calendar weeks of activity. Dates use America/Chicago.
6. Leave and return to **Study** to resume the saved reading or quiz position on any device. **Start New Session** abandons only the unfinished session; earned completions remain.
7. **Explore** browses all active categories, subcategories, and topics, independent of interests. Search and reading never grant completion. **Account** changes interests, username, or password without losing progress.
8. The footer's **Study history & previous results** retains Study sessions and older practice results.

The administrator can reset credentials, disable/re-enable accounts, and delete a student with confirmation. Deletion removes that student's sessions, answers, preferences, and completions; disabling preserves them. Administrator progress links open current Study progress and read-only history; older practice statistics remain separately labeled and accessible. The sole administrator is protected against deletion, disabling, and demotion, including ordinary database writes.

### Recovery and authentication

- Forgotten student credentials are recovered through the administrator; there is no email, public registration, social login, or security-question flow.
- `python manage.py recover_admin` resets the existing administrator password through trusted local/server access and clears login throttles. It does not create another administrator or change the account ID.
- Passwords use Django's password hashing and validators, with an 8-character minimum. Temporary passwords cannot be issued twice; only keyed one-way fingerprints are retained to enforce this. A first-login replacement must differ from the temporary password.
- Resetting a password invalidates existing sessions and requires another password change. Disabling/re-enabling rotates the session version so old sessions cannot revive. A student's password change keeps their current session and invalidates other devices.
- Login attempts are limited in PostgreSQL to 10 per normalized username and 160 per direct client network address per 15-minute window, including successful attempts. The network allowance accommodates 32 students sharing a school network. Counters are shared across workers and contain keyed hashes, not raw addresses. Run `python manage.py purge_login_buckets` and Django's `python manage.py clearsessions` periodically to remove expired counters/sessions. Reverse-proxy IP handling and production rate limits need configuring at deployment; untrusted forwarded headers are not used.
- All writes use CSRF-protected POSTs. Sessions use HttpOnly cookies; no credentials or session tokens go in localStorage. Private responses prohibit browser caching. Production defaults enable secure cookies and HTTPS redirects when `DJANGO_DEBUG=0`; this is not a completed deployment configuration.

## Educational content and repeatable imports

`data/` remains authoritative for imported content. Administrator question edits
and new questions are stored in PostgreSQL and survive imports. On an Explore
topic page, expand **Quiz Questions** to create a typed question or use its **⋯**
menu to edit a question. **Source Questions** shows the original read-only
tournament material. These panels are available only to the administrator,
including on topic-reading pages.

Teacher edits apply to future sessions; existing sessions keep their pinned
questions and autocomplete banks. Imported questions retain a separate baseline:
an import never overwrites the teacher version, and a changed baseline is flagged
for comparison. **Restore Imported Version** switches future sessions back to it.
Teacher-created questions can be archived/restored without deleting history.
The administrator's Scholars Bowl home now includes **Teacher Tools**, also in
the Scholars Bowl navigation. **View Student Progress** searches all student
accounts (including disabled accounts) and shows the selected student's current
weekly goal, activity calendar, topic completion, and recent/full history. Study
attempts and older practice records open in read-only report pages. The existing
Admin progress link now opens this same current view; older practice statistics
are labeled separately. Teachers can reach the hub without choosing personal
Study interests. **Quiz Creator** supports named lists, adding typed questions from
topic menus, renaming, duplication, archiving/restoring, removal, and move-up/down
ordering. Edited bank questions are flagged for explicit review; unavailable items
remain visible until removed or restored. Random generation supports categories,
optional subcategories, 1–100 questions, a per-topic limit, balanced or whole-pool
sampling, and duplicate exclusion. Preview first, then explicitly save the exact
selection. **Host a Quiz** remains upcoming in
[the implementation plan](docs/TEACHER_TOOLS_AND_LIVE_QUIZZES.md).

Migration `0009` adds saved quizzes and ordered items. Apply it before restarting
the updated application. Lists live in PostgreSQL, alongside authoring and student
records. `python manage.py export_saved_quizzes /path/to/new-quizzes.json` exports
lists plus reviewed/current question evidence without student data; full database
backups remain the recovery mechanism. See [Phase 3 notes](docs/TEACHER_TOOLS_PHASE3.md).

Migration `0008` adds authoring provenance and seeds the imported baseline from
each existing question's current revision. Apply it before running the updated
application or importer. Full database backups now protect teacher-authored
content as well as student records. A portable export is available with
`python manage.py export_teacher_questions /path/to/new-export.json`; it contains
question revisions/provenance and no student records. It is supplementary to the
database backup, not an input to `import_content`.

For imported content, edit its JSON files, then run:

```sh
python manage.py import_content
```

The importer reuses `scripts/build.py` validation before writing, then imports in one PostgreSQL transaction with an advisory lock. It preserves all original payloads, stable `study_topic_id`, `subject_id`, globally unique `question_id`, subcategory IDs, source references, redirects, study prose, revision metadata, and attribution. Topic-local IDs such as `q1` are never persistence keys. Import counts are recorded in `ContentImport`.

Original import inventory: 12 categories, 355 subcategories, 7,072 category-specific topics, 6,906 shared subjects, 1,006 detailed study pages, 10,976 questions, 4,383 tournament source units, and 13 redirects.

The current question inventory is **26,923**: the original **10,976 multiple-choice** questions in `data/practice/` plus **15,947 typed/recall** questions in `data/typed-questions.json`. The latter is the approved GPT-6 Luna/xhigh run with giveaway follow-up corrections. It contains only stable IDs, question stems, and answers; runtime imports do not require research files or API access.

All 7,072 topics now have expanded study content: 2,335 existing detailed pages and 4,737 paragraph-only descriptions generated by GPT-6 Sol with low reasoning and no internet tools. The new paragraphs retain generation provenance rather than invented citations; the full set has passed structural validation but has not received a factual audit. Accepted content lives in `data/content.json`. [Content maintenance](docs/CONTENT_WORKFLOW.md) documents both workflows. Raw responses and import records remain local under ignored `research/`.

Repeated imports update current content without duplicating questions or deleting progress. Study sessions pin reading content, question revisions, and grading banks at creation. Imports and retirements do not change an unfinished session's reading or retry pool. Historical session evidence stays intact; Progress and Explore use current active topic membership. Topic completion is unique per student and stable topic ID, including topics in multiple subcategories. Separate records with the same subject ID are not merged.

Imports refuse missing existing IDs unless explicitly reviewed and approved through:

```sh
python manage.py import_content --allow-retire
```

This retires removed content from new practice; it does not delete it or student history. Reintroducing the same identity reactivates it. Reassigning a topic ID to a different subject or a question ID to a different topic is rejected. For an alternate complete dataset, use `--data-dir /path/to/data`. Never point this at generated `dist/`.

## Study rules and retained history

Each initial quiz aims for two typed questions per selected topic, ten for a five-topic session. Matching normalized prompts or answers are treated as duplicates across topics. Overlaps are replaced with other unique pinned questions; if the entire pool is too small, the quiz is shorter. Passing is 9/10 for ten questions, with 90% rounded up for shorter quizzes. When fewer than five unfinished topics remain, Study labels the shorter session and counts a pass as one session toward the weekly goal. Short topic descriptions are valid; enrichment does not gate participation. A topic needs at least two active typed questions to start a session.

Failed attempts deduplicate missed topics for rereading. Retries include the preceding attempt's misses, then unseen pinned questions, up to the original quiz size. Questions answered correctly earlier in the session, including duplicate variants, never return. Quizzes can shrink below ten; the 90% threshold rounds up against the actual question count. No attempt contains duplicate questions; attempts are unlimited. A passing result still lists topics behind any missed answers, with optional rereading that preserves the pass and requires no further quiz. The server owns grading, order, authorization, and completion. Duplicate submissions preserve the first saved answer; stale reading pages cannot advance the session twice. Restart and concurrent submissions are serialized with account/session locks.

Interests affect future choices. A current session keeps its original content and remains resumable even if its selected categories are retired. Empty categories are distinguished from completed content. Fully completed interests offer editing interests or Explore; there is no automatic spaced repetition.

The weekly goal counts passed Study sessions from Monday midnight through the next Monday in America/Chicago. Extra passes remain visible; the progress bar caps at 100%. Reading/quiz events shade the 35-day activity calendar but do not advance the goal. Current completion percentages exclude retired topics while historical evidence is retained.

Older practice sessions, manual studied markers, XP, optional question goals, personal bests, and review evidence are preserved under previous results/statistics. They are not converted into Study completions and do not affect the new weekly goal. Legacy typed sessions remain resumable. Multiple-choice/recall displays and answer reveals are retired. Study restores the original fuzzy autocomplete using its pinned category bank. Candidate data does not mark the correct answer. Incorrect feedback contains only the result and never the canonical answer or explanation. Legacy quiz pages still omit autocomplete banks. The original static explorer is separate and is not the classroom application.

## Updating an existing installation

Use [UPDATE_DEPLOYMENT.md](UPDATE_DEPLOYMENT.md) for the existing server or
[DEPLOYMENT.md](DEPLOYMENT.md) for production configuration and recovery.
Back up and verify a restore before updating. With the application paused, run:

```sh
python -m pip install -r requirements-prod.txt
python manage.py migrate
python manage.py import_content
python manage.py check
python manage.py collectstatic --noinput
```

Restart the service and verify interests → reading → quiz → review/retry → pass,
Progress, Explore, and previous results. Migration `0006` adds the typed format;
`0007` adds Study persistence and topic completions without rewriting old results.
Do not reverse these migrations or run older code against new Study records.
Prefer a forward fix; database restore must use the matching application release
and an explicit decision about any progress recorded since the backup.
No generation API key or research workspace is needed in production.

## Repository layout

- `classroom/`: shared Django settings, routing, and WSGI entry point.
- `accounts/`: custom account model, administration, login limits, lifecycle, and setup/recovery commands.
- `scholars/`: imported content, revisions, scoped quizzes, persistent results, and tests.
- `templates/`, `static/`: shared navigation and responsive, server-rendered UI. Core flows work without JavaScript.
- `data/`: authoritative taxonomy, topics, detailed notes, source units, practice questions, redirects, and original import manifest.
- `src/`: preserved original JavaScript/HTML/CSS static interface.
- `scripts/`: content validation, release packaging, research tooling, static export, and static preview.
- `tests/`: dataset/build, research-tooling, release-boundary, and JavaScript regression tests; they do not require the local research archive.
- `docs/`: concise maintenance and repository/release guidance.

The preferred server workflow uses a permanent Git checkout and `git pull`. The existing packaged deployment can be converted once using [UPDATE_DEPLOYMENT.md](UPDATE_DEPLOYMENT.md). Release packaging remains available as an alternative; see [repository boundaries](docs/REPOSITORY_LAYOUT.md).

## Validation

Run the backend tests against PostgreSQL, then the content and JavaScript checks:

```sh
source .venv/bin/activate
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test accounts scholars classroom --settings=classroom.test_settings --noinput
python -m unittest discover -s tests
node --test tests/*.test.js
```

`classroom.test_settings` creates an isolated test database and uses fast password
hashing only for tests. Never run the website with test settings. **147 Django, 69 content, and 9 JavaScript tests passed** on September 25,
2026. An isolated PostgreSQL restore matched all 33 tables. The final
redesign validation record is in [phase-four notes](docs/SCHOLARS_BOWL_PHASE4.md).

The original static preview remains available with `python scripts/serve.py` on
port 8766. The redesign prototype uses port 8877; both are separate from the
functional Django preview on port 8878 in this workspace. Static `dist/` contains
neither authenticated Study nor saved results and must not replace Django.

## Attribution and operations

See [ATTRIBUTION.md](ATTRIBUTION.md), **Content attribution** in the footer, and
reading-card citations. Original source attribution is retained; no blanket
third-party license is asserted. The redesign plan supersedes older student-flow
instructions in [WEBSITE_PLAN.md](WEBSITE_PLAN.md).

Production deployment of this redesign, off-server backup/alert checks, and a
student pilot remain operator tasks. No external analytics, AI runtime service,
or identity provider is required. See [DEPLOYMENT.md](DEPLOYMENT.md).
