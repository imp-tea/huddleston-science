# First deployment: from your Mac to huddleston.science

This guide is for a **fresh Ubuntu 24.04 droplet** at **206.189.230.160**. First check the operating system in step 1. If it is different, or the machine already hosts something, get the commands adapted before continuing. Nothing in this guide has been run on your droplet yet.

Run one block at a time. If a command fails, stop at that command and keep its error message; later steps often depend on it succeeding. Commands labeled **Mac** run in your Mac's Terminal. Commands labeled **droplet** run inside your SSH connection. Do not paste the headings or the triple-backtick markers.

The pieces you are setting up:

| Piece | What it does |
| --- | --- |
| Your server account, `adam` | Lets you SSH in and administer Linux using `sudo` |
| Background account, `huddleston` | Runs the website with limited permissions; you do not log in as it |
| Website administrator, `classroom-admin` | Logs into the website and creates student accounts |
| PostgreSQL | Stores accounts, saved answers, review schedules, and other progress |
| Gunicorn | Keeps the Django application running |
| Caddy | Receives web traffic, handles HTTPS certificates, and forwards requests to Gunicorn |
| systemd | Starts the services at boot and runs the daily backup jobs |

Those three accounts have different jobs. The server administrator and website administrator are separate accounts.

## 1. Connect and identify the server

**Mac — open Terminal:**

```sh
ssh -i ~/.ssh/id_ed25519 root@206.189.230.160
```

Your public key file exists at `~/.ssh/id_ed25519.pub`. SSH uses the matching private file without `.pub`. Keep that private file on your Mac.

On a first connection, SSH asks whether to trust the server's fingerprint. You can compare it with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` in the droplet's DigitalOcean console when the SSH prompt identifies an ED25519 host key, then accept the matching fingerprint. A prompt for your key's passphrase refers to the passphrase you chose when creating the key. Password/passphrase entry shows no characters while you type.

Once connected, the prompt should resemble `root@your-droplet:~#`. Run these **on the droplet**:

```sh
cat /etc/os-release
free -h
df -h /
ss -lntp
```

Continue with the installation below if this is Ubuntu 24.04 and a fresh server. The other commands show memory, free disk space, and existing listening services. If something already uses port 80 or 443, investigate before installing Caddy. You can paste these outputs into our conversation; they do not contain your private SSH key or passwords.

**If SSH says `Permission denied (publickey)`:** creating a key on your Mac does not automatically install it on an existing droplet. Adding it to your DigitalOcean account later also does not retrofit that droplet. [DigitalOcean documents this distinction and its recovery options](https://docs.digitalocean.com/products/droplets/how-to/add-ssh-keys/to-existing-droplet/).

On your **Mac**, copy only the public key:

```sh
pbcopy < ~/.ssh/id_ed25519.pub
```

Open the droplet's console in DigitalOcean and get a root shell (use the Recovery Console/root-password recovery if normal access is unavailable). There, run:

```sh
mkdir -p /root/.ssh
chmod 700 /root/.ssh
nano /root/.ssh/authorized_keys
```

Paste the public key as its own line, preserving any existing lines. Save with **Control+O**, press **Enter**, and exit with **Control+X**. Then:

```sh
chmod 600 /root/.ssh/authorized_keys
```

Try the Mac SSH command again. This transfers the public key only; no private-key upload is needed.

## 2. Create your everyday server account

**Droplet — still logged in as root:**

```sh
adduser adam
usermod -aG sudo adam
install -d -o adam -g adam -m 700 /home/adam/.ssh
install -o adam -g adam -m 600 /root/.ssh/authorized_keys /home/adam/.ssh/authorized_keys
```

Choose a strong server-account password and save it in your password manager. It is used for `sudo`. Press Enter to leave the optional name/phone fields empty.

**Keep that root window open.** Open a second Terminal window on your **Mac**:

```sh
ssh -i ~/.ssh/id_ed25519 adam@206.189.230.160
```

In this new **droplet** session:

```sh
sudo whoami
```

Enter the password you just chose. It should print `root`. From here onward, use this `adam` session. The account separation follows [DigitalOcean's recommended droplet setup](https://docs.digitalocean.com/products/droplets/getting-started/recommended-droplet-setup/).

## 3. Install operating-system dependencies

**Droplet — as adam:**

```sh
sudo apt update
sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip postgresql postgresql-client curl gnupg ufw debian-keyring debian-archive-keyring apt-transport-https
sudo systemctl enable --now postgresql
```

If the upgrade reports that a reboot is required, run `sudo reboot`, wait for the server to restart, and reconnect as `adam` before continuing. An SSH disconnection during the reboot is expected.

Install Caddy from its official stable package repository:

```sh
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key -o /tmp/caddy-stable.key
sudo gpg --dearmor --output /usr/share/keyrings/caddy-stable-archive-keyring.gpg /tmp/caddy-stable.key
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt -o /tmp/caddy-stable.list
sudo install -m 644 /tmp/caddy-stable.list /etc/apt/sources.list.d/caddy-stable.list
sudo chmod 644 /usr/share/keyrings/caddy-stable-archive-keyring.gpg
sudo apt update
sudo apt install -y caddy
```

These steps use [Caddy's official Ubuntu installation instructions](https://caddyserver.com/docs/install#debian-ubuntu-raspbian). The package normally starts Caddy automatically with a default page. Your actual website is configured later. This application does not require Node.js, Docker, or a separate JavaScript build on the droplet.

## 4. Allow SSH and web traffic

**Droplet:**

```sh
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

Answer `y` to the enable prompt. The SSH allowance comes first so your standard port-22 SSH connection remains permitted.

If a DigitalOcean Cloud Firewall is attached, allow inbound TCP 22 from your current IP, and TCP 80/443 from the internet there too. Keep normal outbound traffic permitted. PostgreSQL port 5432 and Gunicorn port 8000 should not be publicly open.

Your domain's A record was checked on September 22, 2026 and already resolves to `206.189.230.160`; no AAAA answer was returned. You do not need a `www` record for the supplied configuration, which serves `huddleston.science`.

## 5. Create the application directories and download the code

**Droplet:**

```sh
sudo adduser --system --group --home /srv/huddleston --no-create-home huddleston
sudo install -d -o root -g root -m 755 /srv/huddleston
sudo install -d -o adam -g adam -m 755 /srv/huddleston/releases
sudo install -d -o huddleston -g huddleston -m 755 /srv/huddleston/static
sudo install -d -o root -g huddleston -m 750 /etc/huddleston
sudo install -d -o huddleston -g huddleston -m 700 /var/backups/huddleston
umask 022
git clone https://github.com/imp-tea/huddleston-science.git /srv/huddleston/releases/first-release
cd /srv/huddleston/releases/first-release
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-production.txt
sudo ln -s /srv/huddleston/releases/first-release /srv/huddleston/current
```

The repository is publicly reachable over HTTPS, so this clone does not need your Mac's SSH key or a GitHub token. The code belongs to your operator account; the background web account can read it but cannot edit it.

`current` is a shortcut to the active release. This lets later updates use a new release directory while keeping the database outside the code directory. If you reconnect later, return here with:

```sh
cd /srv/huddleston/current
```

## 6. Create the database

**Droplet:**

```sh
sudo -u postgres createuser --pwprompt huddleston
sudo -u postgres createdb --owner=huddleston huddleston
```

The first command asks for a **new database password** twice. Generate a unique password with your password manager and save it; 32 random letters and digits work well without configuration-escaping complications. This is separate from your `adam` Linux password.

Check that PostgreSQL listens locally:

```sh
sudo -u postgres psql -c 'SHOW listen_addresses;'
```

A fresh Ubuntu installation normally reports `localhost`. If it reports `*` or a public address, get that corrected before continuing. Do not enable passwordless `trust` authentication as a workaround for connection errors.

## 7. Save the production settings

**Droplet — from `/srv/huddleston/current`:**

```sh
sudo install -o root -g huddleston -m 640 deploy/production.env.example /etc/huddleston/site.env
sudo python3 - <<'PY'
from pathlib import Path
import secrets
path = Path('/etc/huddleston/site.env')
text = path.read_text()
text = text.replace('replace-with-a-unique-random-secret-at-least-50-characters', secrets.token_urlsafe(64))
path.write_text(text)
PY
sudo nano /etc/huddleston/site.env
```

The Python block creates and writes the application secret directly to the protected file. There is nothing to copy from its output.

In nano, find:

```text
POSTGRES_PASSWORD=replace-with-a-unique-database-password
```

Replace only the placeholder after `=` with the database password from step 6. Leave the generated `DJANGO_SECRET_KEY` and the other settings alone. Save with **Control+O**, **Enter**, then **Control+X**. Do not share this file's contents in chat or commit them to Git.

These commands are for first installation. On later updates, preserve this file and its existing secrets; do not copy the example over it again.

## 8. Initialize the website and your website administrator

**Droplet — from `/srv/huddleston/current`:**

```sh
sudo -u huddleston deploy/manage check --deploy
sudo -u huddleston deploy/manage migrate --noinput
sudo -u huddleston deploy/manage import_content
sudo -u huddleston deploy/manage collectstatic --noinput
sudo -u huddleston deploy/manage bootstrap_admin classroom-admin
```

The last command asks you to choose the **website administrator password** twice. Save it in your password manager. You will use username `classroom-admin` and this password in the browser. It is separate from the server and database passwords.

The content import loads 7,072 topics and 10,976 practice questions. `migrate` creates the database tables. `collectstatic` puts the stylesheet where Caddy can serve it.

The deployment check currently produces two expected warnings: `security.W005` and `security.W021`. They concern extending HTTPS policy to subdomains and browser preload lists; both are deliberately off. Other errors or warnings need investigation.

## 9. Install the background services

**Droplet:**

```sh
sudo install -m 644 deploy/huddleston.service /etc/systemd/system/
sudo install -m 644 deploy/huddleston-backup.service deploy/huddleston-backup.timer /etc/systemd/system/
sudo install -m 644 deploy/huddleston-housekeeping.service deploy/huddleston-housekeeping.timer /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/huddleston*.service /etc/systemd/system/huddleston*.timer
sudo systemctl daemon-reload
```

The app is not started yet. Verify a backup before making it available.

## 10. Make a backup and prove it restores

**Droplet:**

```sh
sudo systemctl start huddleston-backup.service
sudo systemctl status huddleston-backup.service --no-pager
sudo ls -lt /var/backups/huddleston
```

A successful backup job exits, so `inactive (dead)` is normal for this one-shot service; look for `status=0/SUCCESS`. There should be a `.dump` file and a matching `.json` file.

Run this block to find the newest archive, temporarily permit creation of a test database, run the restore check, and remove that permission afterward. The website is still stopped at this point.

```sh
sudo -u postgres psql -v ON_ERROR_STOP=1 -c 'ALTER ROLE huddleston CREATEDB;'
backup_file=$(sudo find /var/backups/huddleston -maxdepth 1 -type f -name '*.dump' | sort | tail -n 1)
sudo -u huddleston deploy/manage verify_database_backup "$backup_file"
sudo -u postgres psql -v ON_ERROR_STOP=1 -c 'ALTER ROLE huddleston NOCREATEDB;'
```

Run the final `NOCREATEDB` line even if the verification command fails. Expected success includes `Restore verified: 24 tables; every row count and checksum matches.` The drill restores into a temporary database and deletes that temporary database; it does not overwrite the live one.

Enable the daily jobs:

```sh
sudo systemctl enable --now huddleston-backup.timer huddleston-housekeeping.timer
sudo systemctl list-timers 'huddleston-*' --no-pager
```

## 11. Start the app and connect the domain

**Droplet:**

```sh
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.before-huddleston
sudo install -m 644 deploy/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl enable --now huddleston.service
sudo systemctl status huddleston.service --no-pager
sudo systemctl enable --now caddy
sudo systemctl reload caddy
sudo systemctl status caddy --no-pager
```

Both services should say `active (running)`. Caddy obtains the HTTPS certificate automatically when DNS and ports 80/443 are reachable. There is no separate Certbot installation for this setup.

**Mac — browser:** open **https://huddleston.science/login/**.

Log in as `classroom-admin`. Create one temporary test student, log out, sign in as that student, replace its temporary password, and try both multiple choice and recall. Check History, sign out/in, and confirm the answers remain. Use the Admin page to delete that test student when finished.

Closing your SSH window now will not stop the website. systemd runs the app independently and starts it again when the droplet reboots.

## 12. Keep a backup outside the droplet

Daily backups on the same machine are useful, but they disappear if that machine is lost. Before depending on the site for student records, choose an encrypted off-server destination and arrange a regular copy. A Mac copy is a useful first step; it is not an automated off-server backup system.

**Droplet:** prepare a private bundle containing your archives, manifests, and production settings:

```sh
sudo install -d -o adam -g adam -m 700 /home/adam/site-backup-transfer
sudo tar -czf /home/adam/site-backup-transfer/huddleston-backup.tar.gz -C / var/backups/huddleston etc/huddleston/site.env
sudo chown adam:adam /home/adam/site-backup-transfer/huddleston-backup.tar.gz
sudo chmod 600 /home/adam/site-backup-transfer/huddleston-backup.tar.gz
```

**Mac — in a local Terminal window, not inside SSH:**

```sh
mkdir -p ~/Documents/huddleston-backups
chmod 700 ~/Documents/huddleston-backups
scp -i ~/.ssh/id_ed25519 adam@206.189.230.160:site-backup-transfer/huddleston-backup.tar.gz ~/Documents/huddleston-backups/
chmod 600 ~/Documents/huddleston-backups/huddleston-backup.tar.gz
```

This bundle includes database contents and application/database secrets. Keep it in encrypted storage, such as a FileVault-protected Mac or an encrypted backup vault. After verifying the download, remove only the transfer bundle on the **droplet**:

```sh
rm /home/adam/site-backup-transfer/huddleston-backup.tar.gz
```

Keep the originals in `/var/backups/huddleston`. The daily job creates backups but does not automatically delete old ones, copy them elsewhere, or send alerts. Choose the destination, retention policy, and alert route before classroom use; [DEPLOYMENT.md](DEPLOYMENT.md) explains the ongoing procedures.

## If a step fails

Copy the failed command and its error message into our conversation. Do not include passwords, private-key contents, or the production environment file.

For an app that will not start, run on the **droplet**:

```sh
sudo systemctl status huddleston.service --no-pager
sudo journalctl -u huddleston.service -n 50 --no-pager
```

For HTTPS/domain trouble:

```sh
sudo systemctl status caddy --no-pager
sudo journalctl -u caddy -n 50 --no-pager
```

`502 Bad Gateway` usually means Caddy is reachable but cannot get a working response from Gunicorn. A connection timeout usually points to networking/firewall/DNS. A database password error means checking the password in step 7 against the one entered in step 6; reinstalling the application is not the fix.

After this first deployment, use the update/rollback procedure in [DEPLOYMENT.md](DEPLOYMENT.md). Pushing to GitHub alone does not change the running droplet. Later releases need to be fetched, their dependencies/migrations checked, and the service restarted. Preserve the production environment file and persistent database when updating code.
