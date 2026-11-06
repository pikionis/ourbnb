# KosPM runbook

How KosPM runs on the VPS (ADR 0010, 0021, 0022). `VPS` below is `root@69.62.116.163`, the shared
Hostinger VPS. Commands marked **laptop** run in Git Bash at the repo's root. **On this host, every
step that changes something needs the owner's go-ahead at that moment.** The survey and `--dry-run`
change nothing.

## Layout on the server
```
/srv/kospm/staging/         .env (mode 600)  app/  site/  deploys.log
/srv/kospm/production/      the same
/etc/nginx/sites-available/kospm-<environment>.conf
/var/lib/kospm-acme/        Let's Encrypt challenges
```

## First setup of an environment
1. **DNS** (hPanel → Domains → ourbnb.gr → DNS): for staging, an `A` record `staging` → `69.62.116.163`.
2. **Survey, laptop** (read-only):
   ```bash
   ssh root@69.62.116.163 'bash -s' < deploy/survey.sh > survey.txt
   ```
   Read it for: nginx on 80/443, ports 8210 and 8211 free, `/tmp/cloudpanel` absent, `x86_64`, enough
   disk, the DNS record pointing here, and the apt simulation with no `[old]` and no `Remv` lines.
3. **Dry run, laptop:**
   ```bash
   ssh root@69.62.116.163 'bash -s -- staging --allow-unfinished=cloudpanel --dry-run' < deploy/setup_host.sh
   ```
4. **Setup, laptop** (go-ahead): the same command without `--dry-run`. It installs Docker if needed,
   creates the folders and a `.env` with fresh secrets, and sets up the vhost and its certificate.
   Expected in its output: `cloudpanel`'s postinst failing on a missing `/tmp/cloudpanel` file.
   It ends with FeedGenix's own check, whose baseline also flags system package upgrades. Before
   blaming a setup for a `FAIL`, compare the file's `stat -c %z` and its md5 with `dpkg-query -W
   -f='${Conffiles}\n' <package>`. Rebaselining that check is the owner's call, never this script's.
5. **First deploy, laptop:** `deploy/ship.sh staging`
6. **Your admin user** (you type the password; it is stored only as a hash):
   ```bash
   ssh -t root@69.62.116.163 'bash /srv/kospm/staging/app/deploy/dc.sh staging run --rm backend python manage.py createsuperuser'
   ```

## Deploy, and roll back
```bash
deploy/ship.sh staging            # HEAD, committed code only
deploy/ship.sh production         # only a commit already on origin/kospm
deploy/ship.sh staging abc1234    # any older commit: this is the rollback
```
The image is built and migrations run before the site folder and the containers are replaced. A
failure before that step leaves what visitors see as it was, though an applied migration stays.
Migrations are additive, so an older commit runs on a newer schema. `deploys.log` lists what was
shipped.

## Looking at it
```bash
ssh root@69.62.116.163
cd /srv/kospm/staging/app/deploy
bash dc.sh staging ps
bash dc.sh staging logs --tail 50 backend      # also: scheduler, caddy, postgres
bash dc.sh staging run --rm backend python manage.py sync_calendars
```
- Staging's emails and WhatsApp messages are in the scheduler's log.
- nginx errors: `/var/log/nginx/kospm-<environment>.error.log`. There are no access logs, on purpose:
  the paths of signed links carry their tokens.

## Secrets
- Each environment's `.env` is written once, on the server, and stays there. It is never copied off.
- After editing it: `bash dc.sh <environment> up --detach --force-recreate backend scheduler`.
- `FERNET_KEYS`: put a new key first and keep the old ones after it. Losing every key loses the
  encrypted fields, so keep an offline copy of production's.
- `DJANGO_SECRET_KEY`: changing it logs everyone out and invalidates links already sent.

## Before production (open items of BUILD_PLAN Phase 7)
- [ ] Off-site backups (`deploy/backup.sh`) and one tested restore.
- [ ] The staff view of owners' uploads.
- [ ] The mailbox `no-reply@ourbnb.gr` (hPanel → Emails), then `EMAIL_URL` and `LEAD_NOTIFY_EMAIL`
      in production's `.env`, by hand. `remote_up.sh` refuses to start while they say `CHANGE_ME`.
- [ ] A decision on two-factor login for the admin.
- [ ] Sent `properties.owner_lead` rows purged from the outbox (they hold a name and a phone), and the
      site's privacy page checked with Petros (it says where a form's data stays).
- [ ] A decision on a cap for the whole form: its limit is per visitor, so many addresses together
      could still flood the outbox and the mailbox's send quota.

## Switching ourbnb.gr to the VPS (ADR 0021, 0022)
At a quiet hour, with staging checked and the items above done. Everything runs on the VPS before
DNS changes, so the gap in step 6 is short. Hostinger keeps serving the site until step 5, and its
copy stays until step 8.
1. Lower the TTL of the apex and `www` records (hPanel), a day ahead.
2. **Folders and secrets, laptop:**
   ```bash
   ssh root@69.62.116.163 'bash -s -- production --skip-vhost --allow-unfinished=cloudpanel' < deploy/setup_host.sh
   ```
3. **On the server,** fill in `EMAIL_URL` and `LEAD_NOTIFY_EMAIL` in `/srv/kospm/production/.env`.
4. **Deploy, laptop:** `deploy/ship.sh production`, then the admin user as above. It checks itself
   through Caddy. Nobody can see it yet: nginx does not forward to it.
5. **DNS:** the apex `A` record → `69.62.116.163`. Delete the apex `AAAA` record unless it is the VPS's
   own IPv6 address: a record left behind sends IPv6 visitors to the old host and can fail the
   certificate check. `www` → `CNAME` to `ourbnb.gr`. **Do not touch MX, SPF, DKIM or DMARC.**
6. **Certificate:** once `nslookup ourbnb.gr` and `nslookup www.ourbnb.gr` answer `69.62.116.163`, run
   the command of step 2 without `--skip-vhost`. HTTPS is unavailable until this finishes.
7. **Check:** the home page, a test of the form that reaches your inbox, `/admin/`, and that the other
   sites still answer.
8. Disconnect "Deploy from GitHub" in hPanel.

**Rollback:** restore the DNS records. The copy on the web hosting is still there until step 8.

After the switch, site changes reach the visitors with `deploy/ship.sh production`.

## Removing an environment
This deletes that environment's database and uploads. The other applications are not touched.
```bash
cd /srv/kospm/staging/app/deploy && bash dc.sh staging down --volumes
rm /etc/nginx/sites-enabled/kospm-staging.conf /etc/nginx/sites-available/kospm-staging.conf
nginx -t && systemctl reload nginx
certbot delete --cert-name staging.ourbnb.gr
cd / && rm -r /srv/kospm/staging
```

## Never
- Push or merge `kospm` into `main`: that is the live site until the switch.
- Run `apt` on this host without reading FeedGenix's notes (`feedgenix/ops/README.md`).
- Publish a container port on anything but `127.0.0.1`.
