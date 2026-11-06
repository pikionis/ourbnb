# 0022 — Deploy on the shared VPS: nginx in front, staging beside production, shipped from a laptop

- Status: accepted (Petros asked for the deploy and a staging stage, 2026-11-06). Amends 0010 and 0021.
- Date: 2026-11-06

## Context
ADR 0010 left one check for the first deploy: who holds ports 80/443 on the VPS. FeedGenix's
operations notes (`feedgenix/ops/README.md`) answer it. The VPS (Ubuntu 24.04, 8 vCPU, 31 GB) is a
CloudPanel host, and its nginx holds both ports. It serves FeedGenix and a frozen legacy app. On that
host:
- every change needs the owner's go-ahead at that moment;
- nginx is reloaded only after `nginx -t` passes, and the other sites must still answer afterwards;
- the `cloudpanel` package has been half-configured since July 2026, so every `apt install` re-runs its
  maintainer script. Today that script fails harmlessly at its first command. If `/tmp/cloudpanel`
  ever exists, it would stop and restart CloudPanel's services.

Petros also asked for a staging stage, to check the site and the back-office live and to pass real
iCal feeds through them before anything public changes. Git is decided too: KosPM lives on the
branch `kospm` of `pikionis/ourbnb`, whose `main` is the public site that Hostinger deploys.

## Decision
**Caddy sits behind the host's nginx** (the second option in ADR 0010).
- One nginx vhost per environment terminates TLS with a certbot `--webroot` certificate, as FeedGenix
  does, and forwards to a localhost port. It is the only file KosPM puts in the shared nginx, and it
  stays the same when routes change.
- Caddy, in the KosPM stack, keeps every route of ADR 0021. Nothing outside the host can reach its
  port, so Caddy trusts nginx's `X-Real-IP` and passes it on as the one `X-Forwarded-For` value. A
  process already on the host could forge it, which would only affect throttling.
- A move to a server of its own means removing the vhost and letting Caddy terminate TLS.

**Two environments, the same files.**

| | Address | Port | Folder | Email |
|---|---|---|---|---|
| staging | `staging.ourbnb.gr` | 8211 | `/srv/kospm/staging` | to the scheduler's log |
| production | `ourbnb.gr` | 8210 | `/srv/kospm/production` | SMTP |

Each has its own containers, database, volumes and generated secrets. Staging differs only by its
`.env` and by asking search engines to stay out. It sends no email and no WhatsApp to anyone.

**Docker comes from Ubuntu's packages** (`docker.io`, `docker-compose-v2`, `docker-buildx`), so the
host gets no new apt source. `deploy/setup_host.sh` installs them with the guards of FeedGenix's
provisioning: apt may start no service, the run stops if apt would upgrade or remove a package, it
stops if `/tmp/cloudpanel` exists, and an unfinished package must be named by hand. Docker, once
started, adds its iptables chains, normally sets the FORWARD policy to DROP and turns on `ip_forward`.
The survey is read for anything on the host that forwards. Containers publish nothing except Caddy's
localhost port, so Docker's rules open nothing to the outside.

**Code reaches the server from the laptop.** `deploy/ship.sh` sends a commit with `git archive` over
SSH, and the public site from `origin/main`, without the files only Apache hid. The server builds the
image and migrates before it replaces the running containers. It holds no GitHub key and never pulls.
To roll back, ship an older commit.

**CI runs the stack.** On every push of `kospm`, `deploy/tests/smoke.sh` runs the real image behind a
real nginx, with the site's real files: routes, headers, a login through both proxies, the form, and
the scheduler delivering its email.

**The form keeps its address.** The site posts to `/api/lead.php`, so the Django view answers there.
The site needs no edit at the switch, and its form works on both hosts during the DNS change.

## Consequences
- The site stays on Hostinger, untouched, until production is switched. Staging proves everything
  first and needs only one new DNS record.
- Git's main risk stays open: a force-push or merge of `kospm` into `main` would wipe the live site.
  This clone has no local branch named `main`, so a plain `git push` cannot reach it, and the two
  branches share no history, so a normal push or pull request between them fails. Nothing stops an
  explicit `git push --force origin kospm:main`. Site edits are made in a separate clone.
- Any local account on this host can administer CloudPanel (FeedGenix's notes), and root reads every
  container's data. Staging carries little, but production will hold owners' IBANs and later guests'
  ID numbers. Sensitive fields are encrypted, yet the key is on the same host. Moving to a server of
  its own, as FeedGenix plans for its launch, should be decided before guest data arrives (Phase 8).
- Real iCal feeds on staging mean the feed URLs and their tokens are stored there. Staging's data
  gets the same care as production's, and its `.env` the same mode.
- Certificates for `ourbnb.gr` can only be issued once DNS points to the VPS, so HTTPS has a short gap
  at the switch. It is planned for a quiet hour, with the TTL lowered first.
- The privacy page says a form's data stays in the mailbox and is deleted after a set time. On the
  VPS the name and phone also stay in the outbox table once sent. Before production, those rows are
  purged and the page is checked with Petros.
- Before production: off-site backups, the staff view of uploads, the SMTP settings and the
  `no-reply@ourbnb.gr` mailbox (BUILD_PLAN Phase 7).

## Alternatives considered
- **Caddy on 80/443, in front of everything.** It would take over the routing of FeedGenix and the
  legacy app, which must not be disturbed.
- **Routes in the nginx vhost, without Caddy.** One proxy fewer, but every route change would touch
  the shared nginx.
- **KosPM natively with systemd, as FeedGenix runs.** No Docker on the host, but it reverses ADR 0010
  and needs far more host scripting.
- **A separate repository.** Safer against the risk above. Petros chose the branch.
