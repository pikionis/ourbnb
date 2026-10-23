# DOMAIN.md — Kos Property Management Platform

This file is the single source of truth for the business rules. Code must match it.
If a rule here is unclear or contradicts code, stop and ask the product owner (Petros) — do not guess.

---

## 1. The business in one paragraph

An IKE (Greek private company) manages short-term rental properties on the island of Kos on behalf of
their owners. The IKE is the legal **Manager (Διαχειριστής)** of every property (sublease model):
listings run on the IKE's own Airbnb / Booking.com accounts, the platforms pay the IKE, and the IKE pays
each owner monthly after deducting fees. The platform automates operations: reservation import, guest
communication on WhatsApp, cleaning schedules, linen stock, maintenance issues, owner statements,
tax declarations and the owner portal.

## 2. Hard principles (never violate)

1. **No automated access to Airbnb / Booking.com.** No scraping, no browser automation, no logging in
   with credentials. Allowed inputs: iCal feeds, CSV files the admin downloads and uploads, inbound
   WhatsApp messages, manual admin entry.
2. **No third-party credentials are stored.** Never store owners' TAXISnet / gov.gr passwords or any
   platform password.
3. **Sensitive data is encrypted at rest and deleted on schedule:** guest ID/passport numbers, lockbox
   codes. Collect only what the tax declaration requires.
4. **The AI assistant never decides business rules.** Rules live in the domain. The AI only interprets
   free text into commands and answers from stored data. When unsure → escalate to admin.
5. **Money is `Decimal`, never `float`.** All amounts in EUR, rounded half-up to 2 decimals at the end
   of each calculation.
6. **Time:** store UTC, display and reason in `Europe/Athens`.

---

## 3. Ubiquitous language (glossary)

| Greek (business) | Code name | Meaning |
|---|---|---|
| Ιδιοκτήτης | `Owner` | Person who owns one or more properties and signs a contract with the IKE |
| Τραπεζικός λογαριασμός | `BankAccount` | The owner's IBAN for payouts, verified with a test transfer |
| Ακίνητο / διαμέρισμα | `Property` | A rentable unit managed by the IKE |
| ΑΜΑ | `ama_number` | Short-term rental registry number issued by AADE, in the IKE's name |
| Δήλωση υπεκμίσθωσης | `sublease_declaration_number` | AADE declaration by the owner granting sublease rights to the IKE |
| Συμβόλαιο | `Contract` | Agreement IKE–owner: commission rate, cleaning charge, terms |
| Κράτηση | `Reservation` | A stay booked on a channel (Airbnb, Booking, direct) |
| Κανάλι | `Channel` | AIRBNB, BOOKING, DIRECT |
| Επισκέπτης | `Guest` | Person staying in a property |
| Οδηγίες check-in | `CheckInGuide` | Location, directions, exterior photo, lockbox photo, lockbox code |
| Κουτί κλειδιών | `Lockbox` | Key box at the property; one code for guests, one for cleaners (may be the same) |
| Καθαρισμός | `CleaningTask` | Cleaning needed between a check-out and the next check-in |
| Καθαρίστρια | `Cleaner` | Team member who performs cleanings (paid per cleaning) |
| Stand-by | `StandbyMember` | Non-cleaner team member who cleans only when cleaners are full |
| Πρόγραμμα ημέρας | `DailySchedule` | All cleaning assignments for one date |
| Σετ λινών | `LinenSet` | One full set of sheets + towels for one changeover |
| Απόθεμα λινών | `LinenStock` | Sets currently stored on the rack at a property |
| Εφοδιασμός | `Restock` | Driver delivers clean linen sets to a property |
| Καθαριστήριο | `Laundry` | External laundry; charges per set |
| Βλάβη / πρόβλημα | `Issue` | Damage or missing item reported by a cleaner |
| Εκκαθάριση κράτησης | `BookingStatement` | Money breakdown of one reservation |
| Πληρωμή ιδιοκτήτη | `OwnerPayout` | Monthly transfer to an owner |
| Δήλωση βραχυχρόνιας διαμονής | `StayDeclaration` | AADE declaration per stay |
| Τέλος κλιματικής ανθεκτικότητας | `ClimateResilienceFee` | Per-night tax charged to guest, passed through to the state |
| Τοπικός οδηγός | `LocalGuideEntry` | A recommendation (beach, restaurant, transfer…) |

---

## 4. Bounded contexts

| Context | Type | Responsibility |
|---|---|---|
| `properties` | Core | Owners, properties, contracts, onboarding, check-in guide, amenities, preferred cleaner |
| `reservations` | Core | Import from iCal, manual entry, changes/cancellations, check-in/out times |
| `housekeeping` | Core | Cleaning tasks, team, daily planning, linen stock, restock route, issues |
| `guests` | Supporting | Guest identification, conversation state, check-in info release, AI assistant |
| `local_guide` | Supporting | Categorised recommendations sent to guests |
| `finance` | Core | Booking statements, owner charges, monthly payouts, accounting export |
| `compliance` | Supporting | AADE stay declarations, deadlines, amendments, data retention |
| `owner_portal` | Supporting | Read models for owners (CQRS read side) |
| `identity` | Generic | Users, roles (Admin, Owner), signed links for cleaners — use Django auth |
| `messaging` | Generic (adapter) | WhatsApp Cloud API: templates, outbound, inbound webhook |

### 4.1 Context map (events between contexts)

```
reservations ──ReservationImported/Rescheduled/Cancelled──▶ housekeeping (create/move/remove CleaningTask)
reservations ──ReservationImported────────────────────────▶ guests (create GuestStay in AwaitingContact)
reservations ──ReservationCancelled───────────────────────▶ finance, compliance
housekeeping ──CleaningCompleted──────────────────────────▶ guests (notify "home ready"), finance (owner cleaning charge)
housekeeping ──IssueApproved──────────────────────────────▶ finance (OwnerCharge)
guests       ──GuestLinkedToReservation / IdVerified──────▶ compliance (guest data for declaration)
guests       ──EarlyCheckInAgreed / LateCheckOutAgreed────▶ reservations (update times) ──▶ housekeeping (replan)
reservations ──StayEnded──────────────────────────────────▶ compliance (DeclarationDue), finance (statement ready)
properties   ──PropertyActivated──────────────────────────▶ reservations (start iCal sync), owner_portal (ask website consent)
properties   ──PropertyDeactivated/Reactivated/Offboarded─▶ reservations (stop/resume iCal sync), housekeeping (no new cleanings)
```

Contexts never import each other's domain models. They communicate through events on the message bus
and through IDs (`property_id`, `reservation_id`). A context may keep its own small copy of data it needs
(e.g. housekeeping keeps `PropertyOpsInfo` with address, coordinates, preferred cleaner).

---

## 5. Properties context

Owners register themselves (owner portal, BUILD_PLAN Phase 2b) or the admin registers them, and
complete a checklist; a property starts working only when its checklist is complete. Only owners
register: the IKE is the only manager on the platform. One owner can have many properties.
Co-ownership is out of scope.

### Aggregate: `Owner`
Fields: `id`, `name`, `email` (unique), `phone`, `afm` (ΑΦΜ, unique, 9 digits with a valid check
digit), `bank_account`, `show_on_website` (default `False`), `website_consent_requested`.

### Bank account (on the `Owner`)
`BankAccount(iban, status)`, where the IBAN must pass the ISO 13616 check (mod 97). States:
`UNVERIFIED` → `PENDING` → `VERIFIED`.
- Verification proves the account exists, accepts transfers and belongs to the owner: a test
  transfer of €0.01 is sent with a 6-digit code in its reference (`PENDING`); the owner enters the
  code and the account becomes `VERIFIED` (`BankAccountVerified`).
- Wrong codes are limited (configuration, default 3); after the last one the account returns to
  `UNVERIFIED` and a new transfer is needed.
- Changing the IBAN returns the account to `UNVERIFIED`.
- Who sends the test transfer is an adapter (`BankAccountVerifier` port): at first the admin, from
  the IKE's e-banking, with the code the platform shows; later automatically through a bank or
  payment provider (provider and ADR chosen in Phase 2b).

### Aggregate: `Property`
Fields: `id`, `owner_id`, `code` (short, e.g. `KOS-A1`, unique), `name`, `address`, `lat`, `lng`,
`default_check_in_time` (15:00), `default_check_out_time` (11:00), `status`, `ama_number`,
`sublease_declaration_number`, `contract`, `check_in_guide`, `amenities`, `preferred_cleaner_id`,
`ical_feeds` (one `url` per `channel`), `linen_par_level` (default 3).

**States:** `ONBOARDING` → `ACTIVE` ⇄ `INACTIVE`; any state → `OFFBOARDED` (final).
Admin labels: Σε εξέλιξη · Ενεργό · Ανενεργό · Αποχώρησε. The admin list of properties filters by
state and shows, for every property in `ONBOARDING`, what is still missing, so the admin knows whom
to follow up.

**Activation checklist (invariant).** A property becomes `ACTIVE` — first activation, or return
from `INACTIVE` — only when all of these hold; items can be completed in any order:
1. the contract is signed (the signed PDF is uploaded);
2. `sublease_declaration_number` is set;
3. `ama_number` is set;
4. the profile is complete: address and coordinates, check-in guide in Greek and English with the
   exterior and lockbox photos, the guests' lockbox code, at least one included amenity;
5. the owner's bank account is `VERIFIED` (once per owner, valid for all their properties).

Otherwise activation raises `PropertyNotReadyForActivation` listing every missing item. iCal feeds
are not on the checklist: under the sublease model the listings run on the IKE's accounts, so the
admin adds the feeds when the IKE's listing exists.

**Onboarding steps and events**

| # | Who | Action | Event |
|---|---|---|---|
| 1 | Owner (or admin) | Registers: name, email, phone, ΑΦΜ, IBAN | `OwnerRegistered` |
| 2 | Owner (or admin) | Adds a property and completes its profile (guide, amenities, photos). Listing text may be pasted and parsed by AI into fields; the platform never fetches a listing from a platform URL (§2.1) | `PropertyProfileCompleted` |
| 3 | Owner | Signs the contract (e.g. digitally on gov.gr, by the owner themself; provider to be confirmed with the lawyer) and uploads the signed PDF | `ContractSigned` |
| 4 | Owner or owner's accountant | Files the sublease declaration at AADE; the number is recorded. Reminders while missing | `SubleaseDeclared` |
| 5 | Admin | Registers the property in the AADE registry with the IKE's credentials; records the ΑΜΑ | `AmaAssigned` |
| 6 | Owner + admin | Verifies the bank account (test transfer + code) | `BankAccountVerified` |
| 7 | Admin | Checks the checklist, activates | `PropertyActivated` |

After the property's first `PropertyActivated`, the owner is asked (in their profile) whether
their name/logo may appear on the public website. `Owner.show_on_website` defaults to `False`.

Later states: `ACTIVE` → `INACTIVE` (`PropertyDeactivated`, e.g. paused by the admin),
`INACTIVE` → `ACTIVE` (`PropertyReactivated`, the checklist is checked again), any state →
`OFFBOARDED` (`PropertyOffboarded`, final). While a property is not `ACTIVE` it gets no iCal sync
and no new cleanings.

### Value objects
- `CheckInGuide(directions_el, directions_en, map_url, exterior_photo, lockbox_photo,
  guest_lockbox_code, cleaner_lockbox_code)`. Lockbox codes are encrypted at rest (§2.3); the
  cleaners' code defaults to the guests' code when empty.
- `Contract(commission_rate=Decimal("0.15"), owner_cleaning_charge=Money("40.00"), signed_at,
  document)` — defaults are configuration. One contract per property until the lawyer says
  otherwise (§14).
- `Amenities` — structured list of included / not included items, used by the AI to answer guests.
- `IcalFeed(channel, url)` — one per channel (Airbnb, Booking.com), https only.
- Concurrent changes to one aggregate are detected with a version number (ADR 0016).

---

## 6. Reservations context

### Aggregate: `Reservation`
Fields: `id`, `property_id`, `channel`, `external_uid` (iCal UID), `confirmation_code` (optional),
`check_in_date`, `check_out_date`, `check_in_time`, `check_out_time`, `status`
(`CONFIRMED`, `CANCELLED`), `guest_name` (optional), `nights` (derived).

**Rules**
- Two confirmed reservations of the same property must not overlap (check-out day may equal the next
  check-in day). An overlap from import raises an admin alert, it is never silently merged.
- Times default to the property defaults; can be changed by admin or by agreed early check-in /
  late check-out.
- Minimum stay is configured on the platforms, not enforced here. Off-season: 4 nights. High season:
  minimum stay at first, later 2-night stays at higher price. Code must not assume a minimum stay.
- Advance notice (how late before check-in a booking may be made) is configured on the platforms,
  not enforced here: normally 48 h, at least 24 h. Late bookings are therefore rare, but code must
  not assume it: a later booking is still imported, planned and announced as a schedule change.

### iCal sync
- Each property has one iCal URL per channel. Poll every 30 minutes (configurable).
- Parse events into `ImportedCalendarEvent(uid, start, end, summary, description)`.
- Classify: reservation vs owner/manual block. Airbnb typically marks reservations as "Reserved"
  and blocks as "Not available"; Booking.com feeds may not distinguish. Unclassifiable events become
  `PendingReview` items for admin confirmation. Classification rules live in the channel adapter.
- Diff against stored reservations by `external_uid`:
  - new → `ReservationImported`
  - dates changed → `ReservationRescheduled(old_dates, new_dates)`
  - disappeared from feed (and start date in the future) → `ReservationCancelled`
- The sync is idempotent: running it twice with the same feed produces no events.
- **Feed health.** A sync of one feed fails when the fetch errors (network, HTTP status, unparseable
  content) or when it returns no events while that feed still has future confirmed reservations.
  A failed sync changes nothing: no reservation is cancelled, rescheduled or added from that feed.
- When a feed has kept failing for longer than the alert threshold (configuration, default 2 h =
  4 consecutive syncs), `CalendarFeedFailing(property_id, channel, since)` is raised and the admin
  receives one WhatsApp alert for that incident. The next successful sync ends the incident; a new
  incident alerts again.
- An empty feed is accepted only when the admin confirms it (e.g. listing closed, all bookings
  cancelled); its future reservations are then cancelled as usual.

`StayEnded` is raised by a scheduled job on the check-out date.

---

## 7. Guests context (phase 2)

### Identification flow
1. After a booking is confirmed, the platform's automated message (configured manually by admin on
   Airbnb/Booking) contains a `wa.me` link with prefilled text including the property code and check-in
   date, e.g. `Hi! Booking KOS-A1 check-in 2026-07-12`.
2. Guest sends the message → inbound webhook → `GuestMessageReceived(phone, text)`.
3. `GuestMatcher` (domain service) finds the reservation by **property code + check-in date**
   (unique per property).
4. Bot confirms full name and dates with the guest → `GuestLinkedToReservation`.
5. If the message has no code: bot asks for property name and arrival date.
6. If zero or several matches → **never guess**, escalate to admin.

### `GuestStay` states
`AWAITING_CONTACT` → `IDENTIFIED` → `ID_VERIFIED` → `CHECK_IN_INFO_SENT` → `IN_STAY` → `CHECKED_OUT`

- `ID_VERIFIED`: bot asks for ID or passport number (only fields required by the AADE declaration).
  Stored encrypted.
- `CHECK_IN_INFO_SENT`: second message with location, directions, exterior photo, lockbox photo and
  lockbox code.
- **Invariant:** the lockbox code is released only when state ≥ `ID_VERIFIED` **and** date ≥ check-in
  date (configurable: day of arrival, from 09:00). Enforced by the aggregate, not by the AI.
- After check-in info: offer local recommendations (transfer, restaurants, beaches, …).
- Later: check-out reminder (evening before), review request (after check-out).
- Guest requests for early check-in / late check-out → admin approval → event to reservations.
- Problems during stay reported by the guest → `Issue` in housekeeping (maintenance).

### AI assistant (adapter)
- Answers only from: property amenities + check-in guide (non-secret parts) + local guide entries +
  reservation facts. Otherwise escalates.
- Replies with human-like delay (adapter setting, e.g. 20–90 s).
- Can propose commands (e.g. `RequestEarlyCheckIn`) but cannot execute irreversible actions.
- Languages: reply in the guest's language when possible; Greek and English at minimum.

### WhatsApp rules
- Business-initiated messages must use approved templates. Templates live in code
  (`messaging/templates.py`) with Greek and English variants.
- Free-form replies are allowed within 24 h of the guest's last message.

---

## 8. Local guide context (phase 2)

`LocalGuideEntry(id, category, name, description_el, description_en, map_url, phone, tags, active)`.
Categories: `TRANSFER`, `RESTAURANT`, `BEACH`, `BAR`, `ACTIVITY`, `CAR_RENTAL`, `SUPERMARKET`,
`PHARMACY`, `OTHER`. Managed in Django admin. Later: partner commissions.

---

## 9. Housekeeping context

### Team
| Order | Member | Kind | Normal limit / day |
|---|---|---|---|
| 1 | Cleaner A | CLEANER | 2 |
| 1 | Cleaner B | CLEANER | 2 |
| 2 | Mother | STANDBY | 2 |
| 3 | Third person | STANDBY | 1 |
| 4 | Petros | STANDBY | 2 |

Team, kinds, limits and order are **configuration** (`EscalationPolicy`), not code.

### `CleaningTask`
Fields: `id`, `property_id`, `reservation_out_id`, `reservation_in_id` (nullable),
`available_from` (check-out datetime), `deadline` (next check-in datetime, nullable = no next booking
known), `status` (`PENDING`, `ASSIGNED`, `DONE`, `CANCELLED`), `assigned_to`, `planned_date`, `sequence`.

Created on `ReservationImported` for its check-out; deadline = check-in of the next reservation of the
same property. Recomputed on any reschedule/cancel/import affecting that property.

### Cleaning window
Normal window: 11:00–15:00 (≈ 2 cleanings per person). A cleaning may be done **after** 15:00 only
when the next check-in is late. A cleaning may move to a later day when no check-in happens on the
check-out day.

### Priority classes (Earliest Deadline First)
| P | Case | When |
|---|---|---|
| 1 | Early check-in today | First cleaning of the day |
| 2 | Normal check-in today | Within 11:00–15:00 |
| 3 | Late check-in today | May be after 15:00 |
| 4 | Check-in tomorrow | Today only if a cleaner is below 2, else tomorrow morning |
| 5 | Property empty ≥ 1 day after check-out | Last; today or a later day depending on load |

### Planning algorithm (`plan_day(day, tasks, team, policy, property_prefs) -> DailySchedule`)
1. Mandatory tasks = tasks whose deadline falls on `day` (P1–P3). Sort by deadline.
2. Assign mandatory tasks:
   a. Cleaners up to **2 each**, balanced (2+2, not 3+1). Prefer the property's preferred cleaner when
      it does not break balance.
   b. Then standby members in escalation order (Mother → Third → Petros), each up to their limit.
   c. Then cleaners' **3rd** cleaning.
   d. A **4th** for a cleaner only with explicit admin approval (`allow_emergency=True`); otherwise the
      task is reported as `UNASSIGNED` and an alert is raised.
3. Flexible tasks (P4–P5) fill remaining capacity **only up to 2 per cleaner**; never use standby or 3rd
   slots for flexible tasks. Unassigned flexible tasks roll to the next day.
4. Within a person's day, order by priority then deadline. P1 first.
5. Output: assignments with sequence, expected time slot, reason (e.g. "check-in 15:00").

**Invariants of `DailySchedule`:** no person above their limit except approved emergency; no task
assigned twice; a P1–P3 task is never left unassigned without an alert.

### Overload forecast
Daily job computes, for the next 30 days, mandatory cleanings per day vs total capacity (cleaners × 2 +
standby). If mandatory ≥ capacity − 1 → alert admin with date and properties, suggesting which
properties could be set to "closed to arrival" on the platforms (manual action by admin).

### Publishing
- A **provisional plan** covers the next 14 days (horizon: configuration). Days are planned in order,
  so flexible tasks (P4–P5) left unassigned on one day roll to the next. It is recomputed whenever
  tasks change (import, reschedule, cancellation, admin edit) and keeps every existing assignment
  that is still valid, so one new booking does not reshuffle the whole fortnight.
- The provisional plan is shown in the admin and on each person's schedule page; it is **not** sent
  on WhatsApp.
- The **final plan** for day D is the provisional plan for D as it stands at 18:00 on D−1. It is fixed
  then and sent to each person via WhatsApp template, with one signed link per task.
- Any later change affecting D re-plans and sends a "schedule changed" message only to affected people.

### Person schedule page (signed link, no login)
Each team member has one signed link showing their provisional days for the next 14 days (property,
time slot, priority). It never shows lockbox codes; those appear only on the task page on the
planned date.

### Cleaner task page (signed link, no login)
Shows: property name, Google Maps link, time slot and reason, lockbox code (visible only on the
planned date), checklist for the property, button **Done**, button **Report problem** (photo + text).
Language: Greek / English toggle. Very large buttons, minimal text.

`CleaningCompleted` → linen stock −1, finance records owner cleaning charge, guests notified "home
ready" (phase 2), schedule updated.

### Linen
- `LinenStock(property_id, sets_on_site)`; par level default 3 sets per property.
- `CleaningCompleted` → −1. `RestockDelivered(n)` → +n.
- Restock list (daily, for the driver, 11:00–15:00): urgency score = `sets_on_site − checkouts in the
  next N days` (N = 3, configurable). `≤ 0` or `sets_on_site ≤ 1` → **urgent**; `sets_on_site == 2` with
  upcoming check-outs → **normal**.
- The list comes with an optimised driving route (routing adapter). Driver in year 1: Petros.
- Laundry cost ≈ 12 € per set (configuration).

### Issues (maintenance)
`Issue(id, property_id, reported_by, photo, description, status, cost, owner_visible)`
States: `REPORTED` → `APPROVED` (admin sets cost, decides owner visibility) | `REJECTED` → `RESOLVED`.
`IssueApproved` with cost → finance `OwnerCharge`. Damages and extraordinary costs are always the owner's.

---

## 10. Finance context (phase 3)

### Inputs per reservation
- `accommodation_price` (A): the price set on the platform for the stay, before any platform fee.
  This is the commission base for all channels.
- `guest_cleaning_fee`: 30 € charged to the guest on the platform → IKE revenue.
- `climate_resilience_fee`: per night, charged to guest, **pass-through to the state**, never revenue,
  never in a commission base. Rate is configuration per season (verify rates with accountant).
- `platform_fee`: actual amount withheld by the platform (from the platform's payout CSV upload).
  Split into fee on accommodation and fee on cleaning fee.

### Owner side (per reservation)
```
owner_share = A
            − platform_fee_on_accommodation
            − ike_commission            (contract.commission_rate × A, default 15 %)
            − owner_cleaning_charge     (contract.owner_cleaning_charge × completed cleanings, default 40 €)
            − approved owner charges    (issues) in the period
```

### IKE side (per reservation)
```
ike_net = ike_commission + owner_cleaning_charge + guest_cleaning_fee
        − platform_fee_on_cleaning_fee − laundry_cost (≈12 €) − cleaner_pay (≈35 €)
```

### Worked example (acceptance test)
A = 1000.00 €, platform fee 15 % on everything, guest cleaning fee 30 €.
- Platform fee on accommodation = 150.00; on cleaning fee = 4.50
- IKE commission = 150.00
- Owner share = 1000 − 150 − 150 − 40 = **660.00 €**
- IKE net = 150 + 40 + 30 − 4.50 − 12 − 35 = **168.50 €**

In the IKE's books the platform fee is an IKE expense and the owner payment is a cost (rent/sublease
— exact classification to be confirmed by the accountant). This is the `accounting` view; the
`BookingStatement` is the owner view. Same events, two models.

### Cancellations
Cancelled without payment → no statement. Cancelled with a cancellation payment → statement with
`A = cancellation amount`, no cleaning charges; triggers amended declaration in compliance.

### `OwnerPayout`
- Monthly per owner, covering all reservations with **check-out in month M** (a stay spanning months
  belongs entirely to its check-out month). Paid during month M+1.
- One payout per owner across all their properties; statements per property.
- States: `CALCULATED` → `APPROVED` (admin) → `PAID` (admin records transfer).
- Accounting export (CSV) per month for the accountant, emailed automatically.

---

## 11. Compliance context (phase 3)

- IKE submits a `StayDeclaration` per stay at AADE **by the 20th of the month following check-out**,
  using the IKE's credentials (manual submission in v1–v3; the system prepares the list).
- `StayEnded` → `DeclarationDue(deadline)`. Cancellation after a declaration was submitted →
  `AmendmentRequired`.
- Monthly export: reservation, ΑΜΑ, dates, amount, guest fields required by AADE, deadline, status.
- Guest identity data: encrypted, deleted after the legal retention period (configuration; to be
  confirmed by accountant) by a scheduled purge job.

---

## 12. Owner portal (phase 3, read side)

Owners log in and see: their properties and onboarding status, reservations, money per reservation,
payouts, approved issues/charges, documents (contract, declarations), website-consent setting.
Built as read models (queries), never touching aggregates directly.

## 13. Public website (phase 3)

Next.js site for owners looking for management. Dynamic content via public API: number of managed
properties, owners with `show_on_website = True` (name/logo), testimonials, managed in Django admin.

---

## 14. Open questions (do not implement guesses)
- Accountant: tax treatment IKE ↔ owner (sublease vs management fee).
- Accountant: exact guest fields required in the AADE declaration; retention period.
- Accountant: climate resilience fee rates per season / property type.
- Consumables cost per cleaning (for margin reporting).
- E-signature provider (gov.gr digital signature by the owner?) — with the lawyer.
- ΑΜΑ under the sublease model: always a new ΑΜΑ in the IKE's name, or can an owner's existing ΑΜΑ
  be used? — accountant/lawyer.
- One contract per owner or one per property? — lawyer.
- Provider for automatic bank-account verification transfers (or open banking) — Phase 2b.
- Whether the WhatsApp `wa.me` link survives Airbnb's message filter (test on a real booking).
