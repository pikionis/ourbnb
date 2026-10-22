# 0012 — Data sources: iCal, manual entry, CSV uploads and inbound WhatsApp only

- Status: accepted
- Date: 2026-10-22

## Context
Reservations, payouts and guest contacts start on Airbnb and Booking.com. Automated access
(scraping, browser automation, scripted logins) breaks the platforms' terms and would put at risk
the accounts the business depends on. Owners' TAXISnet / gov.gr credentials and platform
passwords must never be held by the platform (DOMAIN.md §2.1–2.2).

## Decision
The only data inputs are:
1. **iCal feeds**, one per property and channel, polled every 30 minutes (configurable).
2. **Manual entry** by the admin in the Django admin (e.g. DIRECT reservations, AADE numbers).
3. **CSV files** that the admin downloads from the platforms and uploads (e.g. payout reports, v3).
4. **Inbound WhatsApp** messages through the official Cloud API webhook (ADR 0011).

There is no scraping, no browser automation, no automated login and **no stored third-party
password**. The system prepares AADE declarations, and they are submitted manually. Automated
submission would only use an official interface, if one becomes available.

## Consequences
- iCal carries little data. It has no prices and often no guest name, and Booking.com feeds may
  not tell reservations apart from blocks. Events that cannot be classified go to an admin review
  queue.
- Changes appear up to about 30 minutes late, and the sync must be idempotent.
- The money for a reservation is exact only once the payout CSV is uploaded. Mismatches go to a
  review queue.
- Any request that needs scraping or a stored password is refused and taken to Petros
  (CLAUDE.md, "When to stop and ask").
- A channel manager with an official API stays in the backlog, in case volume grows.
