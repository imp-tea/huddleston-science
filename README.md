# Huddleston Science

A Django/PostgreSQL classroom site with private, pseudonymous accounts and persistent Scholars Bowl practice. Milestones 1–3 are implemented locally; live deployment and the student pilot remain pending. The complete journey remains: administrator creates a student → student replaces a temporary password → completes a quiz → returns to saved results on another device.

The original static site and educational content pipeline remain available. The Django application is now the classroom website; static `dist/` output does **not** include accounts or saved results. Nothing has been deployed.

## Local setup

Requires Python 3.10+ and PostgreSQL 14+ (PostgreSQL 17 is used by the supplied Compose service). Node.js 18+ is needed only for the original JavaScript tests. Runtime dependencies are pinned in `requirements.txt`: Django 5.2.17 LTS, psycopg 3.3.6, and python-dotenv 1.2.2. Django's [supported release table](https://www.djangoproject.com/download/#supported-versions) lists 5.2 LTS security support through April 2028.

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

1. Log in as the administrator and open **Admin**. Create a pseudonymous username and a unique temporary password; deliver both to the student outside the website.
2. Log out. Log in as the student. Every private route requires replacing the temporary password before continuing.
3. Open **Scholars Bowl**, then **Start practice**, or browse a category/subcategory/topic and practice that scope.
4. Choose an answer and select **Check answer**. The server saves and scores it immediately. Feedback keeps the question, correct answer, explanation, and source links visible until **Continue**.
5. Leave midway to resume later, or complete the session and view results. Log out and sign in from another browser; **History** retains completed and unfinished sessions.
6. In **Account**, students can change their username or password. Their immutable account code and results stay attached to the same account.

The administrator can view student results, reset passwords, disable/re-enable accounts, and delete a student with a separate confirmation page. Deletion permanently removes that student's answers and sessions; disabling preserves them. The sole administrator cannot be deleted, disabled, or demoted, including through ordinary database writes. A partial unique constraint prevents a second administrator. Before first bootstrap, there are zero administrators by design.

### Recovery and authentication

- Forgotten student credentials are recovered through the administrator; there is no email, public registration, social login, or security-question flow.
- `python manage.py recover_admin` resets the existing administrator password through trusted local/server access and clears login throttles. It does not create another administrator or change the account ID.
- Passwords use Django's password hashing and validators, with a 12-character minimum. Temporary passwords cannot be issued twice; only keyed one-way fingerprints are retained to enforce this. A first-login replacement must differ from the temporary password.
- Resetting a password invalidates existing sessions and requires another password change. Disabling/re-enabling rotates the session version so old sessions cannot revive. A student's password change keeps their current session and invalidates other devices.
- Login attempts are limited in PostgreSQL to 10 per normalized username and 160 per direct client network address per 15-minute window, including successful attempts. The network allowance accommodates 32 students sharing a school network. Counters are shared across workers and contain keyed hashes, not raw addresses. Run `python manage.py purge_login_buckets` and Django's `python manage.py clearsessions` periodically to remove expired counters/sessions. Reverse-proxy IP handling and production rate limits need configuring at deployment; untrusted forwarded headers are not used.
- All writes use CSRF-protected POSTs. Sessions use HttpOnly cookies; no credentials or session tokens go in localStorage. Private responses prohibit browser caching. Production defaults enable secure cookies and HTTPS redirects when `DJANGO_DEBUG=0`; this is not a completed deployment configuration.

## Educational content and repeatable imports

`data/` remains authoritative. Edit its JSON files, then run:

```sh
python manage.py import_content
```

The importer reuses `scripts/build.py` validation before writing, then imports in one PostgreSQL transaction with an advisory lock. It preserves all original payloads, stable `study_topic_id`, `subject_id`, globally unique `question_id`, subcategory IDs, source references, redirects, study prose, revision metadata, and attribution. Topic-local IDs such as `q1` are never persistence keys. Import counts are recorded in `ContentImport`.

Current inventory: 12 categories, 355 subcategories, 7,072 category-specific topics, 6,906 shared subjects, 1,006 detailed study pages, 10,976 questions, 4,383 tournament source units, and 13 redirects.

Repeated imports update current content without duplicating questions or deleting progress. Changes to a question, its topic/context, study notes, or source attribution create a new immutable-by-import question revision. Sessions pin the revision and shuffled choices at creation. Saved answers and even unfinished sessions keep the original text, correct answer, explanation, classifications, and attribution after an update. Historical **Sources for this question** displays that snapshot; **Study [topic]** opens the current study page.

Imports refuse missing existing IDs unless explicitly reviewed and approved through:

```sh
python manage.py import_content --allow-retire
```

This retires removed content from new practice; it does not delete it or student history. Reintroducing the same identity reactivates it. Reassigning a topic ID to a different subject or a question ID to a different topic is rejected. For an alternate complete dataset, use `--data-dir /path/to/data`. Never point this at generated `dist/`.

Quizzes select up to ten distinct questions, including smaller pools, using server-side randomness. Category/subcategory joins are deduplicated. Scores are calculated exclusively from saved server revisions. A unique start token makes repeated start submissions idempotent; session row locks and unique question positions make duplicate/concurrent answers idempotent. The first recorded choice wins. Retrying after losing a response is safe. Every unfinished session remains resumable unless the student explicitly ends it; completed sessions have a completion timestamp. Each new session is retained separately, so repeat practice is distinguishable without treating it as mastery.

## Study and progress (Milestone 2)

The site is designed for ages 12–18 and classes of up to 32. Pages use compact headings, ordinary controls, and short functional text. There are no hero sections, slogans, decorative category icons, or automatic celebrations. Class size is a planning assumption, not a 32-account cap; one administrator may manage more than one class.

- **Library** searches topic titles and aliases, with category, subcategory, and studied/practiced filters. **Practice these topics** uses all matching topics, not just the current page. The search and status filters also apply to the quiz.
- Opening a topic records its first/last visit. **Mark studied** is an explicit, reversible marker; opening or answering a question never marks it studied. Shared subjects retain separate category-specific topic records.
- **Progress** shows studied/practiced topic coverage and correct answers with their sample size over the last 30 days. Coverage denominators use current active topics. Accuracy retains the classification recorded with each answer. An answer contributes once to its category and overall accuracy even if it belongs to several subcategories. These are coverage/accuracy counts, not mastery claims.
- **Topics to revisit** lists topics whose latest answer to a current question revision was incorrect. Answer feedback stays visible until Continue. A later correct answer to the same revision can be identified as previously missed; this is not evidence of spaced recall.
- **Personal bests** compare only completed sessions with matching scope/filter values, mode, number of questions, and question-bank revisions. A 3/3 result never competes with a 9/10 result. Changed eligible content or a changed study-filter pool starts a separate comparison group. The first completed session establishes a record; a strictly higher score gets a small personal-best label. Ties do not trigger it. Questions within a scope are still sampled randomly; records are not standardized difficulty ratings.
- Existing Milestone 1 sessions keep their answers/results. Their original full question pool was not recorded, so they remain outside the new personal-best comparisons. No speculative content versions are backfilled.

### Participation XP and optional goals

XP is awarded by the server in the same transaction as an answer, regardless of correctness:

| Attempt on a stable question ID | XP |
| --- | --- |
| First recorded attempt ever | 2 |
| First attempt on a later local calendar day | 1 |
| Further attempts that day | 0 |

Dates use `America/Chicago`. Revisions of the same question do not reset the reward rule. A unique reward ledger and account/session locks prevent retries or simultaneous tabs from duplicating points. Opening topics and toggling study markers award no XP. XP begins with Milestone 2; earlier answers are not retroactively rewarded, but are considered when determining first/repeat attempts.

Weekly goals are off by default. A student can choose 10, 20, 30, 50, or 100 different questions per week under **Progress → Weekly goal**. Counts use Monday–Sunday in the site timezone and count distinct question IDs, including answers from unfinished sessions. Repeating the same question does not advance the weekly count. There is no penalty for missing a goal.

Study state, accuracy, XP, goals, and records are private to the student and administrator, survive username changes, and persist across devices. The administrator's student page links to read-only progress. All content remains available without earning points.

### Updating an existing Milestone 1 checkout

```sh
source .venv/bin/activate
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

The additive migration preserves existing accounts, sessions, answers, and imported content. No re-import or new administrator is required. The migration has already been applied to this workspace's local database.

## Personalization and recall (Milestone 3)

**Start practice** now defaults to a personalized mix. Students can select multiple choice or **Recall · self-assessed** and choose personalized, random, or due-only questions on the dashboard, in the library, or on a topic. All existing scope/search/status filters still apply. Personalized sets aim for 4 due questions (oldest first), 3 weak questions, and 3 new questions, filling missing groups from due → weak → new → remaining questions, without duplicates, up to 10. Weak means the current revision's review state has no successful steps. “New to reviews” means no scheduling evidence for that revision and mode, even if older study/history exists. Due-only practice never fills with non-due questions; an empty scope offers a clear message.

Recall hides choices and the answer until **Reveal answer**. Revealing persists across devices but awards nothing and does not count as an answer. After revealing, choose **I remembered** or **I need more practice**, then **Save assessment**. Recall stores a separate boolean assessment; its objective correctness/selected-choice fields stay empty. Explanations and source links stay visible until Continue. Recall does not enter multiple-choice accuracy or personal bests. XP and weekly goals count participation across both modes, with the same stable-question/day limit, so changing modes earns no extra same-day XP.

### Exact review rules

Schedules belong to the student, exact question revision, and mode. Dates use `America/Chicago` calendar days, including daylight-saving transitions. No worker or scheduled job is needed to make reviews due.

| Evidence | Effect |
| --- | --- |
| First answer to a revision in a mode | Success sets step 1; a miss sets step 0; next review tomorrow |
| Success when due, on a later day | Advance one step; intervals are **1, 3, 7, 14, 30 days**, capped at 30 |
| Any mistake / self-assessed miss | Reset to step 0; review tomorrow |
| Same-day successful retry, including after a miss | No new successful step or changed due date |
| Early success before the due date | No new successful step or changed due date |

A first success plus two successful due reviews on separate days qualifies that **question association** as **remembered across reviews**. This is not broad topic/category mastery. Due status is independent of readiness. A later miss removes remembered status. Every subsequent successful due review at the cap schedules another 30 days. Account locks and unique review-state records serialize concurrent devices; an immediate retry cannot count as lasting recall.

Readiness is computed only from active questions and their current revisions. Recognition never establishes self-assessed recall readiness, or vice versa. Changed content/context gets a fresh revision and fresh schedule. Old sessions retain original question/attribution snapshots; answering an outdated or retired revision preserves the answer and participation reward but does not change current review readiness. Reintroducing the exact same revision may expose its previously saved evidence. Nothing propagates through shared subject IDs.

Saved answers include first/same-day/early/due/historical attempt classifications and the next-review/step snapshot at answer time. Older Milestone 1/2 answers are retained without inventing scheduling evidence; review tracking starts with new answers. Category and subcategory summaries count each current question once within each scope, even when subcategories overlap. The progress page shows separate 30-day objective and self-assessed results with denominators, due reviews, remembered/practicing/new counts, scheduled versus same-day attempts, and the next five reviews for each mode. Study markers, coverage, and XP remain separate.

Only **completed random multiple-choice** sessions enter comparable personal bests. Adaptive and due-only question sets are history/progress records without scored bests because their selection changes with the learner. Existing random-session records keep their comparison keys.

**Save and leave** retains a resumable session. **End this session → End session** explicitly marks it ended early, keeps saved answers/XP/review evidence, and excludes it from bests and resume prompts. There is no automatic expiry. A completed session cannot become abandoned.

### Upgrade and launch preparation

```sh
source .venv/bin/activate
python manage.py migrate
python manage.py check
python manage.py runserver 127.0.0.1:8000
```

Migration `0003` is additive and already applied to this workspace's local database. No re-import, replacement administrator, or historical-score rewrite is needed. Do not roll back to Milestone 2 after recall records exist; it cannot interpret them. Read [DEPLOYMENT.md](DEPLOYMENT.md) for production setup, HTTPS/proxy trust, systemd services/timers, backup/restore commands, code versus data rollback, and the owner-led student pilot.

The production dependency file adds Gunicorn 26.2.0. Production requires a strong secret, explicit hosts, debug off, and a database password. A loopback-only Gunicorn listener accepts Caddy's overwritten scheme/client headers; the application rejects other proxy peers and invalid addresses. Daily backup and housekeeping timers are supplied, but are not installed on a server. Local backup/restore commands also work with the normal `.env`; point `PG_BIN_DIR` at the workspace's Postgres.app `bin` directory when using that installation.

## Repository layout

- `classroom/`: shared Django settings, routing, and WSGI entry point.
- `accounts/`: custom account model, administration, login limits, lifecycle, and setup/recovery commands.
- `scholars/`: imported content, revisions, scoped quizzes, persistent results, and tests.
- `templates/`, `static/`: shared navigation and responsive, server-rendered UI. Core flows work without JavaScript.
- `data/`: authoritative taxonomy, topics, detailed notes, source units, practice questions, redirects, and original import manifest.
- `src/`: preserved original JavaScript/HTML/CSS static interface.
- `scripts/`: preserved content validation, static export, and static preview.
- `tests/`: original dataset/build and JavaScript regression tests.

## Validation

Run the backend tests against PostgreSQL, then the existing checks:

```sh
source .venv/bin/activate
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test accounts scholars classroom --settings=classroom.test_settings --noinput
python -m unittest discover -s tests
node --test tests/quiz.test.js
```

`classroom.test_settings` uses an isolated `test_<POSTGRES_DB>` database and fast password hashing only for tests. Never run the website with test settings. Tests cover authorization, no identity fields, one-administrator database protections, account lifecycle, CSRF, login throttling, the complete student journey, cross-device persistence, smaller question pools, scoring, interrupted sessions, sequential/concurrent retries, repeat imports, rollback, retirement, versioning, and full-dataset preservation.

Milestone 1 validation on September 22, 2026: **45 backend tests + 5 original Python tests + 3 JavaScript tests passed**, with clean system/migration checks. A separate Chrome browser check completed the administrator-to-student journey and reopened the same results after a username change on a new mobile session. Keyboard login/answer submission also passed with JavaScript disabled, reduced motion enabled, and a 320px viewport. Screenshots were inspected; temporary browser-test accounts/database were removed.

Milestone 2 validation on September 22, 2026: **70 backend tests + 5 original Python tests + 3 JavaScript tests passed**. New checks cover study/goal privacy and persistence, no automatic study credit, scope/alias filtering, category overlap, historical classification, comparable bests, content-version changes, day/week boundaries, atomic rollback, concurrent rewards, repeat-import preservation, and a class of 32 logging in behind one network. A Chrome check with JavaScript disabled verified study marking → filtered practice → 0/3 then 3/3 → a personal best without repeat XP → optional weekly goal → the same records on a separate 320px browser session. Keyboard answers, reduced motion, and all table columns at 320px were checked; screenshots were visually reviewed. System/migration checks and `git diff --check` passed.

Milestone 3 validation on September 22, 2026: **101 backend/operations tests + 5 original Python tests + 3 JavaScript tests passed**, with clean system/migration/diff checks. New coverage includes calendar/DST boundaries, exact intervals, early and same-day retries, separate recall evidence/scoring, reveal persistence, concurrent device answers, rollback, abandoned sessions, active revisions, overlaps, proxy boundaries, and backup guards. Chrome completed recall → reveal → resume on another device → keyboard self-assessment → saved results without a scored best, plus due-only selection and explicit session ending; JavaScript was disabled, reduced motion enabled, and 320px pages/screenshots checked. Gunicorn 26.2.0 + Caddy 2.11.4 served the production profile over local TLS with redirects, secure/HttpOnly cookies, HSTS, static assets, private caching, overwritten forwarding headers, direct-request rejection, and CSRF rejection. `check --deploy` reports only the documented intentional HSTS subdomain/preload warnings. Real PostgreSQL 17 restore drills passed for both the full corpus and an isolated database with recognition/recall/review/abandoned records: all 24 public tables matched snapshot counts and checksums, and the administrator trigger was present. Linux systemd execution, public certificates, off-server copies/alerts, and a student pilot remain unverified until deployment.

The original static preview remains available with `python scripts/serve.py` at localhost:8766; `python scripts/build.py` rebuilds ignored `dist/`. This is useful for content comparison and offline browsing; its original quizzes are transient and separate from Django history. Do not publish `dist/` as the authenticated classroom application.

## Attribution and next milestones

See [ATTRIBUTION.md](ATTRIBUTION.md), **Content attribution** in the application footer, and the citations on topic and saved-question pages. Tournament texts retain original source attribution; no blanket third-party license is asserted.

[WEBSITE_PLAN.md](WEBSITE_PLAN.md) records implementation status and deferred work. Live DigitalOcean deployment, off-server backups/alerts, the student pilot, review-based badges, and standardized challenge mode remain later work. Production configuration and local HTTPS/restore drills are now included; see [DEPLOYMENT.md](DEPLOYMENT.md). No external analytics, AI generation service, or identity provider was added.
