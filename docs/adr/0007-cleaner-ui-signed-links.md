# 0007 — Cleaner UI: server-rendered pages behind signed links

- Status: accepted
- Date: 2026-10-22

## Context
Cleaners and standby members work from their phones and receive their daily plan on WhatsApp at
18:00. For each task they need:
- the property and a map link;
- the time slot and its reason;
- the lockbox code, shown only on the planned date;
- a checklist;
- two big buttons, **Done** and **Report problem** (photo + text).

They should not have to install an app or remember a password (DOMAIN.md §9).

## Decision
Server-rendered Django pages at `/c/<signed-token>/`: mobile-first, with a Greek/English toggle, no
login and no app. React is not used here.
- The token is made with Django's `TimestampSigner`, using a purpose-specific salt. It identifies
  one cleaning task and is valid until the end of the planned day + 1.
- The views are entrypoints that dispatch the `complete_cleaning` and `report_issue` commands.
  Requests are rate-limited.

## Consequences
- The link is a **bearer credential**: whoever holds it can act on that one task. The page shows
  the minimum data, never other tasks, and the lockbox code only on the planned date. It is served
  only over HTTPS.
- Tokens are signed with `SECRET_KEY`. Rotating the key invalidates all open links, unless the old
  key stays in `SECRET_KEY_FALLBACKS` until those links expire.
- Full tokens must not appear in proxy or application logs.
- A re-plan can reassign a task. Phase 5 decides how a stale link for the old assignee stops working.
- There is no offline mode, so pages must stay light for weak mobile connections.
