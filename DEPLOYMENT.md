# Launch preparation and operations

Milestone 3 supplies a production profile, Caddy configuration, Gunicorn configuration, systemd units, daily backups/housekeeping, and a tested PostgreSQL restore drill. **No deployment has occurred.** The supplied server layout targets a Linux machine with systemd, local PostgreSQL, and Caddy. It is an example to adapt after inspecting the actual droplet; its OS, memory, installed software, SSH access, and firewall have not been assumed.

Before rollout, confirm those details, DNS A/AAAA records, existing services using ports 80/443, and the owner’s readiness for a student pilot. Choose an encrypted off-server backup destination and an operator who will check failures. Keep the student site closed until HTTPS and a server-side restore drill pass.

## Server layout and prerequisites

Use a dedicated unprivileged `huddleston` service account, with no interactive login. Only trusted operators can log into this server or change application code/configuration. Install supported Python 3.10+, PostgreSQL 14+ (17 is locally validated), matching PostgreSQL client tools, and Caddy through the OS's supported installation process. Two Gunicorn workers are an initial setting to measure against the droplet’s actual resources.

| Location | Purpose / permissions |
| --- | --- |
| `/srv/huddleston/releases/<release-id>/` | Versioned application checkout and its own `.venv`; operator-owned, service-readable |
| `/srv/huddleston/current` | Symlink to the active release |
| `/srv/huddleston/static` | Collected assets, writable by `huddleston`, readable by Caddy; directory mode 755 |
| `/etc/huddleston/site.env` | Secrets/configuration copied from `deploy/production.env.example`; root-owned, group `huddleston`, mode 640; parent 750 |
| `/var/backups/huddleston` | Backup archives/manifests; `huddleston` owner, mode 700 |
| PostgreSQL data directory | Persistent OS-managed database storage, separate from code/releases |
| Caddy data directory | Persistent TLS certificate storage managed by Caddy's service |

Create a PostgreSQL login role `huddleston` with a unique password, no superuser/CREATEROLE/CREATEDB privileges, and ownership of a dedicated `huddleston` database. Enter the password interactively (`\password huddleston` in a trusted `psql` session), not as a shell argument. Listen on loopback only; require password authentication (`scram-sha-256`) for TCP. The runtime role owns the app schema so migrations and the administrator protection trigger can be installed. Routine app writes cannot disable the administrator; privileged server operators remain trusted.

Only SSH for the operator and ports 80/443 for web traffic should be reachable externally. Do not expose PostgreSQL or Gunicorn. Port 80 is needed for HTTP redirects and may be used by certificate validation. Do not add a CDN, second proxy, or load balancer without reviewing the forwarding trust configuration.

Generate independent application/database secrets with a trusted local password tool or `secrets.token_urlsafe(64)` and place them directly in the protected environment file. Do not paste them into tickets, Git, command arguments, or logs. Keep the same Django secret across ordinary releases: it also keys temporary-password fingerprints and throttling. Preserve an encrypted copy outside the droplet.

## First installation

Prepare a reviewed release checkout at the paths above, install its virtual environment, and point `current` at it. The application code must not be writable by the running web process. From that checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-production.txt
sudo -u huddleston deploy/manage check --deploy
sudo -u huddleston deploy/manage migrate --noinput
sudo -u huddleston deploy/manage import_content
sudo -u huddleston deploy/manage collectstatic --noinput
sudo -u huddleston deploy/manage bootstrap_admin classroom-admin
```

`deploy/manage` loads the protected environment file without shell-sourcing it and always selects `classroom.production`. There is no seeded administrator password. Do not copy the development `.env` or use test settings. `DJANGO_ALLOWED_HOSTS` must name the actual domain. Debug is rejected in production, secure cookies and HTTPS redirects are on, and the proxy must supply a verified client address.

Review and install the files in `deploy/` into `/etc/systemd/system/`, and install the Caddyfile at `/etc/caddy/Caddyfile`. Adapt service dependencies if the distribution names PostgreSQL differently. Validate before starting:

```sh
sudo systemd-analyze verify /etc/systemd/system/huddleston*.service /etc/systemd/system/huddleston*.timer
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl daemon-reload
sudo systemctl enable --now huddleston.service
sudo systemctl reload caddy
sudo systemctl enable --now huddleston-backup.timer huddleston-housekeeping.timer
```

Start Caddy if it is not already running. Its service must have ports 80/443 and writable certificate storage. Caddy provisions certificates and redirects HTTP to HTTPS for the configured domain. Gunicorn 26.2.0 listens only on `127.0.0.1:8000`, with its control socket and access logging disabled. The Caddy proxy replaces `X-Real-IP` and `X-Forwarded-Proto` and removes `X-Forwarded-For`. Django rejects non-loopback proxy peers and malformed addresses. Login throttles hash the verified client address, so different networks do not all share a single proxy bucket. Existing 160-per-network/10-per-username limits remain; measure them during the pilot.

Django logs only severity, logger, and status code. Caddy access logs and request-bearing HTTP error logs are disabled. Gunicorn retains process/worker errors. Check service failures and availability; reproduce detailed application failures locally using non-student fixtures. Do not turn on body, cookie, credential, raw IP, or student URL logging to diagnose classroom issues.

HSTS starts at one hour. `check --deploy` intentionally reports `security.W005` and `security.W021`: subdomains and preload are off until all affected hosts are confirmed HTTPS-only. After successful operation, increase the ordinary HSTS duration if appropriate; a code rollback cannot revoke a browser’s already-cached HSTS policy.

## Backups and restore verification

The daily systemd timer creates a custom-format `pg_dump` and a companion JSON manifest in a private directory. Both files are mode 600. A read-only exported PostgreSQL snapshot ties the dump to row counts and checksums for **every** public table, including accounts, passwords, sessions, content, answer history, review schedules, goals, rewards, and migrations. A partial dump is never presented as complete. Keep each `.dump` and matching `.json` together. Only restore trusted archives: database dumps contain executable schema definitions.

Run a backup immediately and inspect timer status:

```sh
sudo systemctl start huddleston-backup.service
sudo systemctl status huddleston-backup.service
sudo systemctl list-timers 'huddleston-*'
sudo journalctl -u huddleston-backup.service --since today
```

For a manual backup from the active release:

```sh
sudo -u huddleston deploy/manage backup_database /var/backups/huddleston
```

`pg_dump` and `pg_restore` must be compatible with the server major version. Set `PG_BIN_DIR` in the environment file if clients are not on the service PATH. Commands never include passwords in arguments.

The restore drill needs CREATEDB solely to create a random `huddleston_restore_check_<uuid>` database. Either run against an isolated PostgreSQL instance with a dedicated drill role, or have the database operator temporarily grant CREATEDB to the application role for the attended drill and revoke it immediately afterward. The daily backup role does not need CREATEDB. While the temporary privilege is present, pause public application traffic.

```sh
sudo -u huddleston deploy/manage verify_database_backup /var/backups/huddleston/<backup>.dump
```

The command validates the archive hash **before connecting**, creates a fresh database, restores with `--exit-on-error`, compares every table's row count and checksum against the snapshot, verifies the administrator protection trigger, and drops only its own temporary database, including on failure. It never restores over the active database. If the process is forcibly killed or the server connection is lost, an operator should inspect any leftover `huddleston_restore_check_*` databases before removing them. Save the successful drill date and release identifier, without student data.

Copy archives, manifests, and a separately encrypted configuration/secret backup to an owner-chosen encrypted destination outside the droplet. This is **not yet configured**; local backups alone do not protect against droplet loss. Adopt an initial retention policy of 14 daily and 8 weekly verified copies, subject to the owner’s retention requirements. No script deletes backups automatically. Monitor disk space, check backup success daily, and test an off-server restore monthly and before major schema/database upgrades. Alert delivery depends on the owner’s monitoring destination and remains to configure at deployment.

For actual disaster recovery, provision a fresh PostgreSQL database/role, restore a chosen trusted dump with `pg_restore --exit-on-error --no-owner --no-privileges --dbname=<new-database> <backup>.dump` using a protected password file or environment (not a command argument), and point a private maintenance instance at it. Restore the saved application secret, matching release, and configuration. Verify row checksums, migrations, login/password reset, saved recognition and recall sessions, review dates, and administrator protection before changing the live database setting. Clear restored login sessions with `clearsessions` only for expired sessions; to invalidate **all** restored browser sessions, delete `django_session` rows through a trusted maintenance command. Keep the failed database and newest backups until recovery is confirmed.

## Updates and rollback

Application releases, educational content imports, schema migrations, and persistent student data are separate operations.

1. Run tests on the proposed release. Record old/new release IDs and inspect migrations. Create a fresh backup and verify a restore before a schema change. Briefly stop the app for the migration/switch window so old workers cannot write against a changed schema.
2. Build the new checkout/venv outside `current`. Run production checks using its `deploy/manage`. Apply reviewed migrations with that release, and import content only when the content changed. Omissions still require deliberate `--allow-retire` approval; history is retained.
3. Collect static assets, switch `current` to the new release, then restart `huddleston`. Check HTTPS, login, one recognition and one recall flow, history, and timers. Never run production database tests against the live database.
4. If application code fails, switch to a **schema-compatible** previous release, recollect its assets, and restart. Do not delete database volumes, drop tables, run `flush`, or restore an old dump as a routine code rollback.
5. Milestone 3 is additive, but Milestone 2 does not understand recall or abandoned sessions. Once such records exist, rolling back to Milestone 2 is unsafe. Prefer a forward fix. Do not reverse migration 0003: it removes recall/review fields and its old constraint rejects saved recall answers.
6. Restoring a pre-release backup loses all writes after its snapshot. This is a deliberate disaster-recovery decision requiring a maintenance window, a fresh backup of current state, and an explicit choice of acceptable data loss. Restore to a new database, validate, then switch configuration; retain the original for recovery.

Do not replace PostgreSQL data storage when updating code. Test major PostgreSQL upgrades independently. Re-importing an old content release may reactivate its exact prior question revisions; it never rewrites saved answer snapshots.

## Pilot when the owner is ready

Start with 4–6 students and pseudonymous accounts. Keep any real-name mapping outside the site. Use a 15–20 minute session to check temporary-password replacement, choosing a topic, multiple choice, reveal/self-assessment, readable explanations, saved history, and resuming on another device. Repeat on a later school day to exercise due reviews. Ask whether students can distinguish participation XP, objectively scored accuracy, and self-assessed recall; check keyboard use and small phones.

Record anonymous issues (screen/action/problem), failed requests, latency under a classroom of up to 32, review workload, and misleading labels. Do not collect student names or add external analytics. Resolve blockers, verify recovery/reset/disable behavior and backups, then decide whether to expand. No student pilot has occurred yet.

## Validation and references

Local validation results are recorded in `README.md` and `WEBSITE_PLAN.md`. Linux service installation, public DNS/ACME certificates, firewall behavior, off-server copy/alerts, and a live student pilot require the actual server and owner readiness.

Configuration follows the [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/), [Django proxy trust guidance](https://docs.djangoproject.com/en/5.2/ref/settings/#secure-proxy-ssl-header), [Gunicorn settings](https://gunicorn.org/reference/settings/), [Caddy reverse-proxy behavior](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https), and [PostgreSQL backup documentation](https://www.postgresql.org/docs/17/backup-dump.html).
