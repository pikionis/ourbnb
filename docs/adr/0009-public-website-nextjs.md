# 0009 — Public website: Next.js reading a small public API (v3)

- Status: accepted; amended by 0021 (the site is served at ourbnb.gr by the same Caddy as KosPM)
- Date: 2026-10-22

## Context
The IKE needs a public site to attract property owners on Kos, in Greek and English (DOMAIN.md
§13, BUILD_PLAN Phase 13). It presents the services, how they work and the pricing model, and has a
contact form. It must rank in search, so it needs metadata, a sitemap, Open Graph tags and the
local-business schema. Some content is dynamic:
- the number of managed properties;
- owners who agreed to appear (`show_on_website=True`);
- testimonials.

## Decision
A Next.js site in `website/`, statically generated where possible for SEO and speed. It reads a
**small, read-only public API** (Django Ninja) that exposes only three things:
- the count of managed properties;
- the name and logo of each consenting owner;
- testimonials managed in the Django admin.

The site is built in Phase 13.

## Consequences
- The API is anonymous, so it must expose nothing beyond those three items and must respect
  `show_on_website`, which defaults to `False`.
- Pages are statically rebuilt or cached, so the site keeps working while the backend is briefly
  down.
- The contact form is not part of the read-only API. Where submissions go (a small write
  endpoint or an external form service) is an open question for Phase 13; either way it needs
  spam protection and rate limiting.
- The VPS runs one more container (Node) behind Caddy (ADR 0010), and the repo gets a second
  JavaScript project.
