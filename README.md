# Huddleston Science

A Django/PostgreSQL classroom site with private, pseudonymous accounts and persistent Scholars Bowl practice. Milestone 1 implements the complete journey: administrator creates a student → student replaces a temporary password → completes a quiz → returns to saved results on another device.

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
3. Open **Scholars Bowl**, then **Start mixed practice**, or browse a category/subcategory/topic and practice that scope.
4. Choose an answer and select **Check answer**. The server saves and scores it immediately. Feedback keeps the question, correct answer, explanation, and source links visible until **Continue**.
5. Leave midway to resume later, or complete the session and view results. Log out and sign in from another browser; **All results** retains completed and unfinished sessions.
6. In **Account**, students can change their username or password. Their immutable account code and results stay attached to the same account.

The administrator can view student results, reset passwords, disable/re-enable accounts, and delete a student with a separate confirmation page. Deletion permanently removes that student's answers and sessions; disabling preserves them. The sole administrator cannot be deleted, disabled, or demoted, including through ordinary database writes. A partial unique constraint prevents a second administrator. Before first bootstrap, there are zero administrators by design.

### Recovery and authentication

- Forgotten student credentials are recovered through the administrator; there is no email, public registration, social login, or security-question flow.
- `python manage.py recover_admin` resets the existing administrator password through trusted local/server access and clears login throttles. It does not create another administrator or change the account ID.
- Passwords use Django's password hashing and validators, with a 12-character minimum. Temporary passwords cannot be issued twice; only keyed one-way fingerprints are retained to enforce this. A first-login replacement must differ from the temporary password.
- Resetting a password invalidates existing sessions and requires another password change. Disabling/re-enabling rotates the session version so old sessions cannot revive. A student's password change keeps their current session and invalidates other devices.
- Login attempts are limited in PostgreSQL to 10 per normalized username and 50 per direct client network address per 15-minute window, including successful attempts. Counters are shared across workers and contain keyed hashes, not raw addresses. Run `python manage.py purge_login_buckets` and Django's `python manage.py clearsessions` periodically to remove expired counters/sessions. Reverse-proxy IP handling and production rate limits need configuring at deployment; untrusted forwarded headers are not used.
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

Quizzes select up to ten distinct questions, including smaller pools, using server-side randomness. Category/subcategory joins are deduplicated. Scores are calculated exclusively from saved server revisions. A unique start token makes repeated start submissions idempotent; session row locks and unique question positions make duplicate/concurrent answers idempotent. The first recorded choice wins. Retrying after losing a response is safe. Every unfinished session remains resumable; completed sessions have a completion timestamp. Each new session is retained separately, so repeat practice is distinguishable without treating it as mastery.

No XP, rewards, review scheduler, personal-best comparisons, or mastery claims are implemented in this milestone.

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
python manage.py test accounts scholars --settings=classroom.test_settings --noinput
python -m unittest discover -s tests
node --test tests/quiz.test.js
```

`classroom.test_settings` uses an isolated `test_<POSTGRES_DB>` database and fast password hashing only for tests. Never run the website with test settings. Tests cover authorization, no identity fields, one-administrator database protections, account lifecycle, CSRF, login throttling, the complete student journey, cross-device persistence, smaller question pools, scoring, interrupted sessions, sequential/concurrent retries, repeat imports, rollback, retirement, versioning, and full-dataset preservation.

Milestone 1 validation on September 22, 2026: **45 backend tests + 5 original Python tests + 3 JavaScript tests passed**, with clean system/migration checks. A separate Chrome browser check completed the administrator-to-student journey and reopened the same results after a username change on a new mobile session. Keyboard login/answer submission also passed with JavaScript disabled, reduced motion enabled, and a 320px viewport. Screenshots were inspected; temporary browser-test accounts/database were removed.

The original static preview remains available with `python scripts/serve.py` at localhost:8766; `python scripts/build.py` rebuilds ignored `dist/`. This is useful for content comparison and offline browsing; its original quizzes are transient and separate from Django history. Do not publish `dist/` as the authenticated classroom application.

## Attribution and next milestones

See [ATTRIBUTION.md](ATTRIBUTION.md), **Content attribution** in the application footer, and the citations on topic and saved-question pages. Tournament texts retain original source attribution; no blanket third-party license is asserted.

[WEBSITE_PLAN.md](WEBSITE_PLAN.md) records implementation status and deferred work. DigitalOcean deployment, proxy/HTTPS configuration, backups and restore drills, study markers, category progress aggregates, review scheduling, self-assessed recall, and game rewards remain later work. No external analytics, AI generation service, or identity provider was added.
