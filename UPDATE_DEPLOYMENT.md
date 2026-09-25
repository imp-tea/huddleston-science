# Deploy this update, then use Git pull for future updates

Your server currently runs an extracted package at
`/srv/huddleston/releases/dd545cec8c9e`, through the
`/srv/huddleston/current` symlink. It is not a Git checkout.

We will create **one permanent checkout at `/srv/huddleston/app`** and point
`current` there. After that, update this same checkout with `git pull`; do not
clone into a new directory or make a release archive for each update.

The `huddleston` service, database, `/etc/huddleston/site.env`, static directory,
and Caddy configuration stay in place. This update adds migration
`scholars.0006`, 15,947 typed/recall questions, and keeps all 10,976 multiple-choice
questions. Existing accounts, sessions, answers, XP, and history are preserved.

Run the numbered steps separately. **If a command fails, stop at that step.**
The parenthesized blocks stop on errors without closing your SSH connection.
No API key or question generation is needed on the server.

## 1. Commit and push on your Mac

In GitHub Desktop, review and commit the changes, then **Push origin**.
Suggested commit message: `Use dedicated typed-question bank with giveaway corrections`.
Make sure the commit includes `data/typed-questions.json`, migration `0006`,
the application changes, tests, scripts, and documentation.

Alternatively, in your Mac's Terminal:

```sh
cd ~/Desktop/huddleston-science
git status --short
git add README.md DEPLOYMENT.md FIRST_DEPLOYMENT.md UPDATE_DEPLOYMENT.md ATTRIBUTION.md docs data/typed-questions.json scholars scripts tests
git diff --cached --stat
git commit -m "Use dedicated typed-question bank with giveaway corrections"
git push origin main
git rev-parse --short=12 HEAD
```

Keep that last commit ID to compare with the server. `.env`, raw research
responses, local databases, and virtual environments remain ignored.

## 2. Connect to the server

On your **Mac**:

```sh
ssh -i ~/.ssh/id_ed25519 adam@206.189.230.160
```

All remaining commands run **inside SSH, on the server**, as `adam`.

## 3. Create the permanent checkout — once

The old site keeps running while you prepare this checkout.

```sh
(
  set -eu
  umask 022
  test ! -e /srv/huddleston/app
  sudo install -d -o adam -g adam -m 755 /srv/huddleston/app
  git clone --branch main https://github.com/imp-tea/huddleston-science.git /srv/huddleston/app
  cd /srv/huddleston/app
  git rev-parse --short=12 HEAD
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements-production.txt
  sudo -u huddleston ./deploy/manage check --deploy
  sudo -u huddleston ./deploy/manage migrate --plan
)
```

The commit ID must match your Mac. The two documented warnings `security.W005`
and `security.W021` are expected. Investigate other errors. If the previous
application is current, the only new migration should be `0006_question_format`.

If `/srv/huddleston/app` already exists, stop and inspect it rather than deleting
it or cloning again. If Git is missing, install it with
`sudo apt update && sudo apt install -y git`. If GitHub requires authentication,
use your authorized GitHub access, such as a read-only deploy key; an account
password is not accepted for Git over HTTPS. Do not put a token in the clone URL.

Do not copy `.env` from your Mac. `deploy/manage` loads the existing production
settings from `/etc/huddleston/site.env`.

## 4. Pause the site and make a backup

This begins the maintenance window. Students may briefly see `502 Bad Gateway`
until step 6 restarts the app.

```sh
(
  set -eu
  sudo systemctl stop huddleston
  cd /srv/huddleston/current
  sudo -u huddleston ./deploy/manage backup_database /var/backups/huddleston
  sudo ls -lt /var/backups/huddleston | head
)
```

The backup command must succeed and produce a `.dump` plus its `.json` manifest.
For this schema update, verify that the newest backup restores before proceeding:

```sh
(
  set -eu
  cd /srv/huddleston/current
  backup_file=$(sudo find /var/backups/huddleston -maxdepth 1 -type f -name '*.dump' | sort | tail -n 1)
  test -n "$backup_file"
  trap "sudo -u postgres psql -v ON_ERROR_STOP=1 -c 'ALTER ROLE huddleston NOCREATEDB;'" EXIT
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c 'ALTER ROLE huddleston CREATEDB;'
  sudo -u huddleston ./deploy/manage verify_database_backup "$backup_file"
)
```

Expect `Restore verified`. This restores into a temporary database, not over
live data, and revokes the temporary CREATEDB permission when the block exits.
Keep the backup and its manifest. If preparation or backup fails before the
migration/import, `sudo systemctl start huddleston` brings the unchanged old
site back while you investigate.

## 5. Apply the update

```sh
(
  set -eu
  cd /srv/huddleston/app
  sudo -u huddleston ./deploy/manage migrate --noinput
  sudo -u huddleston ./deploy/manage import_content
  sudo -u huddleston ./deploy/manage collectstatic --noinput
)
```

Expected import counts include:

- `topics`: **7072**
- `typed_questions`: **15947**
- `multiple_choice_questions`: **10976**
- `practice_questions`: **26923**

The import may take a few minutes. It is atomic and repeatable. Do not add
`--allow-retire` to this update: no existing question IDs should be removed.
Do not recreate the database, administrator, or environment file.

## 6. Point the service at the permanent checkout and start it

```sh
(
  set -eu
  test -L /srv/huddleston/current
  test "$(readlink -f /srv/huddleston/current)" = /srv/huddleston/releases/dd545cec8c9e
  sudo ln -s /srv/huddleston/app /srv/huddleston/current.git-next
  sudo mv -Tf /srv/huddleston/current.git-next /srv/huddleston/current
  sudo systemctl restart huddleston
  sudo systemctl is-active huddleston
)
```

Expect `active`. The one-time switch is complete. Keep the old release directory
for reference; future updates use `/srv/huddleston/app` directly.
The service and scheduled jobs already use `current`, so their configuration
and Caddy do not need changing.

## 7. Check the live site

```sh
readlink -f /srv/huddleston/current
sudo systemctl status huddleston --no-pager
sudo systemctl list-timers 'huddleston-*' --no-pager
curl --fail --silent --show-error -o /dev/null -w 'Login HTTP status: %{http_code}\n' https://huddleston.science/login/
```

Expect `/srv/huddleston/app`, `active (running)`, and HTTP `200`.
In your browser, sign in and:

1. Start a **new typed-answer** session and answer using autocomplete.
2. Start **multiple choice** and confirm it still offers four choices.
3. Try **Recall · self-assessed**, reveal an answer, and save an assessment.
4. Check History and resume an existing unfinished session.
5. Check Progress's separate mode totals.

Resumed sessions intentionally keep their old questions and autocomplete banks.
New typed/recall questions start with new review schedules. Old scores and review
records are retained; they are not treated as attempts on the new questions.

Closing SSH does not stop the site. After the checks, make another backup and
copy backups to your usual protected off-server destination.

## Future updates — use this same checkout

First commit and push on your Mac. Then SSH in and run the following block.
It checks for a clean checkout, records the previous commit, backs up, pulls,
installs pinned dependencies, migrates, imports content, collects assets, and
restarts. Schedule a maintenance window, and inspect/restore-test backups before
future risky migrations as described in DEPLOYMENT.md.

```sh
(
  set -eu
  cd /srv/huddleston/app
  test "$(git branch --show-current)" = main
  test -z "$(git status --porcelain)"
  git fetch origin
  git merge-base --is-ancestor HEAD origin/main
  git log --oneline HEAD..origin/main
  git rev-parse HEAD > "$HOME/huddleston-previous-commit.txt"
  sudo systemctl stop huddleston
  sudo -u huddleston ./deploy/manage backup_database /var/backups/huddleston
  git pull --ff-only origin main
  .venv/bin/python -m pip install -r requirements-production.txt
  sudo -u huddleston ./deploy/manage check --deploy
  sudo -u huddleston ./deploy/manage migrate --noinput
  sudo -u huddleston ./deploy/manage import_content
  sudo -u huddleston ./deploy/manage collectstatic --noinput
  sudo systemctl restart huddleston
  sudo systemctl is-active huddleston
)
```

If the clean-checkout or ancestry check fails, inspect `git status` and stop;
do not discard changes with `reset --hard`. If a later command fails, the site
may remain stopped. Fix the specific failure before restarting, and repeat
step 7's checks after a successful update. No new checkout, archive, or symlink
switch is needed for ordinary updates.

## If something goes wrong

```sh
sudo systemctl status huddleston --no-pager
sudo journalctl -u huddleston -n 50 --no-pager
```

Share the failed command and error, without credentials or environment-file
contents. A database import error rolls that import back, but migrations are a
separate step. Do not restore an old database as a routine code rollback: that
would lose student work recorded since the backup.

**After the new bank is imported, do not simply restart the old package or
point `current` back.** Older code assumes every question has multiple-choice
options and cannot handle the new payloads. Prefer fixing forward. The additive
format column can remain; reversing migrations or deleting new rows is not a
safe rollback for existing sessions. DEPLOYMENT.md explains code/content/data
rollback considerations; ask for a targeted recovery plan if needed.
