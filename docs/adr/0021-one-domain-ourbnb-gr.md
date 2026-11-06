# 0021 — One domain: the site and KosPM under ourbnb.gr (amends 0009 and 0010)

- Status: accepted (Petros, 2026-11-05); amended by 0022 (the host's nginx terminates TLS in front
  of Caddy, and does the HTTPS and `www` redirects)
- Date: 2026-11-05

## Context
Petros wants the back-office at an address like `ourbnb.gr/admin`, and everything on the official
domain, with no second domain for KosPM.

Today:
- `ourbnb.gr` is the public site: static pages and one PHP form on Hostinger web hosting, deployed
  from GitHub into `public_html`. The apex has A and AAAA records, and `www` is a CNAME to
  Hostinger's CDN.
- KosPM is not deployed yet. ADR 0010 puts it on the Hostinger VPS, which is another machine.
- KosPM's pages are already paths: `/admin/`, `/owner/`, `/c/`, `/s/`, `/webhooks/whatsapp/`.

A domain leads to one entry point, so the site and KosPM must stand behind the same one.

## Decision
**One address.** `https://ourbnb.gr` is the only public address of the site and of KosPM. `www`
redirects to it.

**Caddy on the VPS is the entry point.** At the first deploy the public site moves from the web
hosting to the VPS, and the domain's web records point there. The site keeps its own source and its
own releases, separate from KosPM's.

**Routes.**

| Path | What answers |
|---|---|
| `/admin`, `/admin/*` | The back-office |
| `/owner/*` | The owner portal (ADR 0017) |
| `/c/*`, `/s/*` | The team's signed-link pages (ADR 0007) |
| `/webhooks/*` | Inbound WhatsApp (ADR 0011) |
| `/api/*` | The JSON API (ADR 0002) |
| `/i18n/*` | The language toggle |
| `/static/*` | Django's static files, served by Caddy |
| `/healthz` | The health check of the deploy and the containers |
| anything else | The public site's files, served by Caddy |

Matches are exact, so `/administrator` belongs to the site and answers 404.

**The back-office at `/admin/`.** Today that is the Django admin, and it stays there until a new
screen ships. If ADR 0020 is accepted, the new screens take `/admin/` and the Django admin moves to
`/admin/system/`.

**The public site on the VPS.**
- Caddy serves an exported copy without `.git`, `.htaccess`, `README.md` and PHP files. It would
  otherwise hand them out as plain files.
- Caddy takes over what `.htaccess` does today: the HTTPS and `www` redirects, the security headers,
  the cache rules and the 404 page.
- The form (`api/lead.php`, PHP `mail()`) has no PHP to run on. It becomes a small Django endpoint
  with the same checks and a rate limit. The Phase 7 plan proposes its place in the code.

**The switch.**
1. Everything runs on the VPS first and is tested with `curl --resolve`, while visitors still reach
   the old host.
2. The DNS TTL is lowered in advance.
3. The apex A and AAAA records and `www` change together. An AAAA record left behind would send IPv6
   visitors to the old host and can fail the certificate check.
4. Mail records (MX, SPF, DKIM, DMARC) are not touched.
5. The copy on the web hosting stays until the new one is verified. Restoring the records is the
   rollback.

## Consequences
- Nothing changes on the live site until the first deploy. `ourbnb.gr/admin` answers 404 until then.
- **Same origin.** API calls need no CORS, and the session and CSRF setup stays simple (ADR 0020).
  But a script on a public page runs on the same origin as the back-office, so it could act for a
  logged-in staff member. The public pages load no third-party script today, and adding one needs a
  review. Caddy sends a Content-Security-Policy on the whole domain.
- **`/admin/` is the first address bots try.** Only the portal's logins are throttled today; Django's
  admin login is not. It gets throttling before go-live, and Phase 7 decides on two-factor login.
- Private paths send `X-Robots-Tag: noindex`, and access logs do not record signed-link tokens.
- The VPS becomes a single point of failure for the public site too. Caddy keeps serving the site
  when Django is down, but not when the VPS is down.
- Hostinger's "Deploy from GitHub" is disconnected after the switch. Phase 7 chooses how site
  releases reach the VPS.
- The paths in the table are reserved: a new page of the site cannot use them.
- ADR 0010's check on ports 80/443 now decides the setup, because this domain needs them and the
  existing app on the VPS must not be disturbed.
- Links in emails and WhatsApp messages start with `https://ourbnb.gr`. `PORTAL_NAME` sets the name
  owners see, so production can say OurBnb while the code stays KosPM.
- ADR 0009 predates the static site that now runs. Whatever Phase 13 builds must fit these routes.

## Alternatives considered
- **A subdomain, `admin.ourbnb.gr`.** The site stays on the web hosting, the switch is one new DNS
  record, and the separate origin is safer. Petros wants one address with a path.
- **A proxy from the web hosting to the VPS (`.htaccess`).** The site would not move, but this depends
  on what shared hosting permits, and the back-office and its live streams would pass through a
  server we do not control.
- **An edge proxy that splits paths between two servers.** It adds a service and one more place that
  holds TLS.
- **KosPM on the web hosting.** Shared hosting does not run the containers, Postgres and scheduler of
  ADR 0010.
