# Deploy the Scholars Bowl redesign

## Choose the path that matches the server

The original deployment ran an extracted package at
`/srv/huddleston/releases/dd545cec8c9e`, through the
`/srv/huddleston/current` symlink. That package is not a Git checkout.

After committing and pushing in step 1, check the current server path over SSH:

```sh
readlink -f /srv/huddleston/current
```

- If it is `/srv/huddleston/app`, the one-time conversion is already done. Use
  **Existing checkout updates** below, then step 7 to check the site.
- If it is `/srv/huddleston/releases/dd545cec8c9e`, follow steps 2–7 for the
  one-time conversion.
- If it is another path, inspect the layout before using either procedure.

We will create **one permanent checkout at `/srv/huddleston/app`** and point
`current` there. After that, update this same checkout with `git pull`; do not
clone into a new directory or make a release archive for each update.

The `huddleston` service, database, `/etc/huddleston/site.env`, static directory,
and Caddy configuration stay in place. The redesign adds migration
`scholars.0007`; `scholars.0006` is also required if the typed-bank update has not
yet been deployed. Together these provide typed questions, saved interests, resumable
Study sessions, topic completions, and redesigned Progress/Explore. The 10,976
original multiple-choice questions remain stored. Existing accounts, sessions, answers, XP, and history are preserved.

The latest quiz uniqueness and optional-review fixes need no additional migration,
dependency, environment variable, or service configuration. Deploy their Python,
templates, and static files together. `collectstatic` is required for the redesign.

Run the numbered steps separately. **If a command fails, stop at that step.**
The parenthesized blocks stop on errors without closing your SSH connection.
No API key or question generation is needed on the server.

## 1. Commit and push on your Mac

In GitHub Desktop, review and commit the changes, then **Push origin**.
Suggested commit message: `Redesign Scholars Bowl study, progress, and exploration`.
Include migration `0007`, the new Study modules and templates, static assets,
account changes, tests, and documentation. The existing typed-bank data and
migration `0006` must remain in the repository.

Alternatively, in your Mac's Terminal:

```sh
cd ~/Desktop/huddleston-science
git status --short
git add -A
git diff --cached --stat
git diff --cached --check
git commit -m "Redesign Scholars Bowl study, progress, and exploration"
git push origin main
git rev-parse --short=12 HEAD
```

Review the staged files before committing, including new files; omit any unrelated
work. Keep that last commit ID to compare with the server. `.env`, raw research
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
and `security.W021` are expected. Investigate other errors. Expect
`0007_studypreferences_categories_and_more`, plus `0006_question_format` if the
typed-bank update has not been applied. Already-applied migrations are skipped.

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

1. Choose interests, start **Study**, and read the topic cards.
2. Confirm Reroll appears above the subcategory cards. Start a five-topic quiz and check that its ten questions have unique prompts and answers (a genuinely smaller unique pool produces a shorter quiz). Type a misspelled or partial answer and check fuzzy autocomplete plus keyboard completion. Submit responses and check brief Correct/Incorrect feedback without revealing the correct answer after a miss. Confirm a failed quiz offers targeted rereading and a retry containing only missed or unseen questions; previously correct questions and duplicate variants must not return.
3. Pass a quiz with 9/10; confirm the missed topic is listed for optional review, opens its reading card, and returns to the passed result without a retake. Confirm one completed session and its topic completions appear in **Progress**, with no extra credit from optional rereading.
4. Leave during reading or a quiz, then resume from another browser. Starting over must preserve earlier completions.
5. Browse **Explore**, follow a subcategory into a topic, and check its breadcrumb. Browsing must not change completion totals.
6. Check **Study history & previous results** and Account interests. Existing legacy typed sessions and results remain; recognition/recall displays and reveals are retired.

Migration 0007 does not convert old scores or manual markers into completions.
Current Study sessions pin their original reading, questions, and grading banks.
Keep migration 0007 and the new code together; do not roll back to older code or
reverse the schema after new Study records have been created.

Closing SSH does not stop the site. After the checks, make another backup and
copy backups to your usual protected off-server destination.

## Existing checkout updates — including this redesign

First commit and push on your Mac. Then SSH in and run the following block.
It checks for a clean checkout, records the previous commit, backs up, pulls,
restore-tests the backup, installs pinned dependencies, shows pending migrations,
migrates, imports content, collects assets, and restarts. Use a maintenance window.
The restore check creates a temporary database and never restores over live data.

```sh
(
  set -eu
  cd /srv/huddleston/app
  test "$(readlink -f /srv/huddleston/current)" = /srv/huddleston/app
  test "$(git branch --show-current)" = main
  test -z "$(git status --porcelain)"
  git fetch origin
  git merge-base --is-ancestor HEAD origin/main
  git log --oneline HEAD..origin/main
  git rev-parse HEAD > "$HOME/huddleston-previous-commit.txt"
  sudo systemctl stop huddleston
  sudo -u huddleston ./deploy/manage backup_database /var/backups/huddleston
  (
    set -eu
    backup_file=$(sudo find /var/backups/huddleston -maxdepth 1 -type f -name '*.dump' | sort | tail -n 1)
    test -n "$backup_file"
    trap "sudo -u postgres psql -v ON_ERROR_STOP=1 -c 'ALTER ROLE huddleston NOCREATEDB;'" EXIT
    sudo -u postgres psql -v ON_ERROR_STOP=1 -c 'ALTER ROLE huddleston CREATEDB;'
    sudo -u huddleston ./deploy/manage verify_database_backup "$backup_file"
  )
  git pull --ff-only origin main
  git rev-parse --short=12 HEAD
  .venv/bin/python -m pip install -r requirements-production.txt
  sudo -u huddleston ./deploy/manage check --deploy
  sudo -u huddleston ./deploy/manage migrate --plan
  sudo -u huddleston ./deploy/manage migrate --noinput
  sudo -u huddleston ./deploy/manage import_content
  sudo -u huddleston ./deploy/manage collectstatic --noinput
  sudo systemctl restart huddleston
  sudo systemctl is-active huddleston
)
```

Compare the deployed commit ID with your Mac's commit. Expect migration 0007
on the first redesign deployment; the later quiz fixes add no further schema
changes. If the clean-checkout or ancestry check fails, inspect `git status` and stop;
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
