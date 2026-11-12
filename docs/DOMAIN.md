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
| Λογαριασμός ιδιοκτήτη | `OwnerAccount` | An owner's login to the owner portal, linked to one `Owner` by `owner_id` |
| Τραπεζικός λογαριασμός | `BankAccount` | The owner's IBAN and account holder name for payouts, verified with a test transfer |
| Έλεγχος ονόματος δικαιούχου | `PayeeCheck` | The bank's name check (Verification of Payee) when the IKE sends the test transfer |
| Ακίνητο / διαμέρισμα | `Property` | A rentable unit managed by the IKE |
| ΑΜΑ | `ama_number` | Short-term rental registry number issued by AADE, in the IKE's name |
| Δήλωση υπεκμίσθωσης | `sublease_declaration_number` | AADE declaration by the owner granting sublease rights to the IKE |
| Συμβόλαιο | `Contract` | Agreement IKE–owner: commission rate, cleaning charge, terms |
| Συμβόλαιο προς υπογραφή | `ContractDraft` | The contract PDF and terms the IKE offers for a property; the owner signs it |
| Κράτηση | `Reservation` | A stay booked on a channel (Airbnb, Booking, direct) |
| Ημερολόγιο κρατήσεων | `ReservationCalendar` | All reservations of one property, with the state of its calendar feeds |
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
| Αίτημα εκτίμησης | `OwnerLead` | Someone with a home asks for an estimate on the public site's form |

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
| `identity` | Generic | Users, roles (Admin, Owner), owner accounts (sign-up, invitation, password reset), signed links for cleaners — use Django auth |
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
properties   ──PropertyCalendarSettingsChanged────────────▶ reservations (code, name, ACTIVE or not, default times, feed URLs)
properties   ──PropertyActivated──────────────────────────▶ owner_portal (ask website consent)
properties   ──PropertyDeactivated/Reactivated/Offboarded─▶ housekeeping (no new cleanings)
properties   ──OwnerRegistered────────────────────────────▶ identity (note it on the account that reserved the owner)
properties   ──OwnerEmailChanged──────────────────────────▶ identity (an invitation not used yet follows the new address)
```

The admin's "invite to the portal" is the one synchronous step between contexts: bootstrap sends
identity's `InviteOwner` command with the owner's id and email, so a refusal reaches the admin.

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
`BankAccount(iban, holder_name, status)`.
- The IBAN must pass the ISO 13616 check (mod 97).
- The holder name is the account holder's name exactly as the bank holds it, often in Latin
  capitals, because the bank compares it (see below).

States: `UNVERIFIED` → `PENDING` → `TRANSFER_SENT` → `VERIFIED` (ADR 0018).
- Verification proves the account exists, accepts transfers and belongs to the owner.
- Starting it (by the owner or the admin) creates a 6-digit code (`PENDING`). The IKE then sends a
  test transfer of €0.01 with the code in its reference.
- When the transfer is sent, the IKE's bank checks the holder name against the IBAN
  (Verification of Payee, mandatory in the euro area since October 2025). The admin records the
  result, a `PayeeCheck`:
  - `MATCH`: the transfer is sent (`TRANSFER_SENT`);
  - `CLOSE_MATCH`: the transfer is sent, and the name the bank returned becomes the holder name.
    It is the bank's own spelling, so the verification does not restart;
  - `NOT_POSSIBLE` (e.g. a bank outside the euro area): the admin may still send it, and the code
    alone is then the proof;
  - `NO_MATCH`: nothing is sent and the account returns to `UNVERIFIED`. The owner sees why and
    corrects the name or the IBAN.
- Once the transfer is sent, the owner enters the code from their statement and the account
  becomes `VERIFIED` (`BankAccountVerified`). A code cannot be entered before the transfer is
  recorded as sent.
- Wrong codes are limited (configuration, default 3). After the last one the account returns to
  `UNVERIFIED` and a new transfer is needed.
- Changing the IBAN or the holder name returns the account to `UNVERIFIED`.
  - In the owner portal the owner can change them only while the account is not `VERIFIED`.
  - A verified account is changed by the admin, so taking over an owner's login is not enough to
    redirect their payouts.
- Who sends the test transfer is an adapter (`BankAccountVerifier` port). Today it is the admin,
  from the IKE's e-banking, with the code the platform shows (ADR 0018). An automatic sender can
  replace the admin later without changing these rules.

### Aggregate: `Property`
Fields: `id`, `owner_id`, `code` (short, e.g. `KOS-A1`, unique), `name`, `address`, `lat`, `lng`,
`default_check_in_time` (15:00), `default_check_out_time` (11:00), `status`, `ama_number`,
`sublease_declaration_number`, `contract_draft`, `contract`, `check_in_guide`, `amenities`,
`preferred_cleaner_id`, `ical_feeds` (one `url` per `channel`), `linen_par_level` (default 3).

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
| 1 | Owner (or admin) | Registers: name, email, phone, ΑΦΜ, IBAN and account holder name | `OwnerRegistered` |
| 2 | Owner (or admin) | Adds a property and completes its profile (guide, amenities, photos). Listing text may be pasted and parsed by AI into fields; the platform never fetches a listing from a platform URL (§2.1) | `PropertyProfileCompleted` |
| 3 | Admin, then owner | The admin uploads the contract to sign; the owner signs it (e.g. digitally on gov.gr, by the owner themself; provider to be confirmed with the lawyer) and uploads the signed PDF | `ContractOffered`, `ContractSigned` |
| 4 | Owner or owner's accountant | Files the sublease declaration at AADE; the number is recorded. Reminders while missing | `SubleaseDeclared` |
| 5 | Admin | Registers the property in the AADE registry with the IKE's credentials; records the ΑΜΑ | `AmaAssigned` |
| 6 | Owner + admin | Verifies the bank account (test transfer with the bank's payee check + code) | `BankAccountVerified` |
| 7 | Admin | Checks the checklist, activates | `PropertyActivated` |

After the property's first `PropertyActivated`, the owner is asked (in their profile) whether
their name/logo may appear on the public website. `Owner.show_on_website` defaults to `False`.

Later states: `ACTIVE` → `INACTIVE` (`PropertyDeactivated`, e.g. paused by the admin),
`INACTIVE` → `ACTIVE` (`PropertyReactivated`, the checklist is checked again), any state →
`OFFBOARDED` (`PropertyOffboarded`, final). While a property is not `ACTIVE` it gets no iCal sync
and no new cleanings.

### Contract to sign (`ContractDraft`)
- The admin prepares a property's contract and uploads it as a PDF, with its terms: the commission
  rate and the owner cleaning charge, the configured defaults being proposed (`ContractOffered`).
- The owner downloads it, signs it themself, and uploads the signed PDF. The property's
  `Contract` then records the draft's terms, the signed PDF and the time of the upload
  (`ContractSigned`).
- In the portal, a signed contract can be uploaded only when a draft exists.
- A new draft replaces the previous one; it does not undo a signed contract.
- The admin can still record a contract signed another way (e.g. on paper) directly, with its
  terms.

### Owner portal (Phase 2b, ADR 0017)
Owners complete their checklist themselves on the owner portal.
- **Sign-up.** Email and password; the email is confirmed by a link before the account can log in.
  - The account reserves the id of the owner it will be linked to. The owner then registers
    (onboarding step 1) with that id and the account's email.
  - One account per owner, and one owner per account.
- **Invitation.** The admin can invite an owner they registered.
  - The emailed link lets the owner choose a password, which also confirms the email.
  - Inviting again while the invitation is open sends a new link.
  - An owner whose account is already active uses "forgot password" instead (see the details
    below).
- **No automatic linking.** Registering with a ΑΦΜ or email that another owner already has is
  refused with "contact us". An account never links itself to an existing owner: knowing someone's
  ΑΦΜ must not give access to their data.
- **Links.** Links sent by email (confirmation, invitation, password reset) work once and expire
  (configuration: by default 3 days, and 1 day for a password reset).
- **What the owner can change.**
  - An owner sees and changes only their own data.
  - Name and phone, at any time. The email is the login and is changed through the IKE. The ΑΦΜ is
    given at registration.
  - A property, only while it is `ONBOARDING`; after that, changes go through the IKE.
  - Never the ΑΜΑ, calendar feeds, preferred cleaner, linen par level or default check-in/out times,
    which the IKE sets.
- **Property code.** A property added by an owner gets its code automatically: the configured
  prefix and the next number (e.g. `KOS-014`).
- **Listing text.** Listing text pasted by the owner may be read by the AI into a draft of the
  profile (§2.4). The owner reviews it before anything is saved. The AI never fills in lockbox
  codes, and no URL is fetched (§2.1). The text goes to the Claude API (ADR 0019).
- **Files.** Uploaded files (photos, contracts) are visible only to their owner and the admin.

### Value objects
- `CheckInGuide(directions_el, directions_en, map_url, exterior_photo, lockbox_photo,
  guest_lockbox_code, cleaner_lockbox_code)`. Lockbox codes are encrypted at rest (§2.3); the
  cleaners' code defaults to the guests' code when empty.
- `Contract(commission_rate=Decimal("0.15"), owner_cleaning_charge=Money("40.00"), signed_at,
  document)` — defaults are configuration. One contract per property until the lawyer says
  otherwise (§14).
- `ContractDraft(document, commission_rate, owner_cleaning_charge)` — the PDF to sign and its
  terms, under the same rules as a contract's terms.
- `PayeeCheck(result, bank_name)` — `MATCH`, `CLOSE_MATCH` (with the name the bank returned),
  `NOT_POSSIBLE` or `NO_MATCH`.
- `Amenities` — structured list of included / not included items, used by the AI to answer guests.
- `IcalFeed(channel, url)` — one per channel (Airbnb, Booking.com), https only.
- Concurrent changes to one aggregate are detected with a version number (ADR 0016).

### Validation details (Phase 2 — to be confirmed by Petros)
Small rules decided while building Phase 2. They are implemented as written here; change them
with `/domain-change` if the business wants otherwise.
- Property `code`: 2–16 characters, Latin letters or digits in groups joined by single hyphens
  (the hyphens count); stored upper-case (`kos-a1` → `KOS-A1`).
- Coordinates: both or neither; latitude −90…90, longitude −180…180, at most 6 decimals (≈10 cm).
- Map link and calendar links: `https://` only.
- Amenities: duplicates are dropped; an item cannot be both included and not included.
- `linen_par_level`: at least 1 set.
- Contract: commission rate 0 ≤ r < 1 with at most 4 decimals (`0.1525` = 15.25 %); owner
  cleaning charge ≥ €0 in whole cents; the signed PDF is required; no signing time means "now".
- The sublease declaration number and the ΑΜΑ can be corrected but not removed once recorded.
- Uploads: the contract is a PDF; photos are JPG, PNG, WebP or HEIC (checked by the domain,
  on the file extension).
- Profile completeness: a property may have gaps while `ONBOARDING` (the checklist shows them);
  an `ACTIVE` property must keep a complete profile (`ProfileMustStayComplete`); an `INACTIVE`
  one may have gaps, and its return to `ACTIVE` checks the whole checklist again.
- The cleaners' own lockbox code can be removed again, so cleaners go back to the guests' code.

### Validation details (Phase 2b — to be confirmed by Petros)
- Account holder name: required, in any script, at most 70 characters (the SEPA limit for a payee
  name). Surrounding spaces are trimmed and repeated spaces collapsed.
- Property codes given automatically: `<prefix>-<number>`, with the number padded to 3 digits
  (`KOS-001`). The prefix (`KOS`) and the width are configuration. The next number is one more than
  the highest number in use with that prefix, so a code is never reused.
- A `CLOSE_MATCH` payee check needs the name the bank returned; the other results take none.
- Inviting an owner whose account is already active sends no new link: they get an email
  reminding them to log in, with the "forgot password" link.
- An invited owner's email may already be used by an account whose own reserved owner never
  registered (a sign-up that stopped at "contact us").
  - That account is connected to the invited owner.
  - Its password is dropped, and the owner chooses a new one through the invitation link.
    Whoever chose the old password signed up with that address, but is not trusted with the
    owner's data.
  - An account whose own owner registered is never moved, and the admin is told so.
- When the admin corrects an owner's email, an invitation not used yet follows the new address,
  and the links already sent to the old one stop working.
- An email link never changes anything when it is only opened: the owner presses a button
  (mail scanners open links). A login address has at most 150 characters.
- The owner starts the bank-account verification in the portal only for an unverified account.
  A verification under way is restarted by the IKE only, because a restart cancels the
  transfer that may have been sent.
- The owner uploads the signed contract once. A contract already recorded (by the owner, or by
  the IKE, e.g. signed on paper with its own terms) changes through the IKE: an upload never
  replaces it, nor its terms.
- When another owner takes the next property code at the same moment, the property gets the code
  after it.
- Listing text:
  - The text is at most 20,000 characters, and an owner may have it read 10 times an hour. Both
    limits are configuration, for cost.
  - The draft fills only the fields the owner left empty. Anything the owner already entered
    stays as it is.
  - An amenity is matched to the standard Yes/No list ignoring case, spaces and hyphens
    ("WiFi" is "Wi-Fi"); any other amenity is added to the free-text lists.
  - An amenity the draft gives both ways, however written, is left for the owner to answer.

---

## 6. Reservations context

### Aggregate: `ReservationCalendar` (one per property)
The consistency boundary of the no-overlap rule (Cosmic Python ch. 7). It holds:
- all reservations of one property;
- the state of its calendar feeds;
- the calendar events waiting for the admin.

Other contexts refer to a reservation by `reservation_id`.

It keeps its own copy of what it needs from the properties context (§4.1), kept up to date by
`PropertyCalendarSettingsChanged`:
- the property's code and name;
- whether the property is `ACTIVE`;
- its default check-in and check-out times;
- its feed URLs.

### Entity: `Reservation`
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
- The dates of an Airbnb or Booking.com reservation come only from its feed. The admin changes its
  check-in/out times and guest name.
- A `DIRECT` reservation is entered, changed and cancelled by the admin.

### iCal sync
- Each property has one iCal URL per channel. Poll every 30 minutes (configurable). Only `ACTIVE`
  properties are synced.
- Parse events into `ImportedCalendarEvent(uid, start, end, kind, confirmation_code)`.
  - The channel adapter reads each event's summary and description, to classify it (reservation,
    block or unknown) and to find the confirmation code.
  - The summary and description are not kept: an Airbnb description holds digits of the guest's
    phone.
- **Classification.** Airbnb typically marks reservations as "Reserved" and blocks as "Not
  available". Booking.com feeds do not distinguish the two.
  - An unknown event waits for the admin (`CalendarEventNeedsReview`, with a WhatsApp alert). The
    admin's answer is remembered by the event's UID.
  - An unknown event with exactly the dates of a confirmed reservation of another channel is that
    reservation's mirror, because the platforms' calendars are connected. It is a block.
  - Classification rules live in the channel adapter.
- **Changes.** Imported events are compared with the stored reservations by `external_uid`:
  - new → `ReservationImported`
  - dates changed → `ReservationRescheduled(old_dates, new_dates)`
  - disappeared from the feed, with the check-in date after today (in Athens) →
    `ReservationCancelled`. A stay in progress, or one starting today, is never cancelled by its
    feed.
- **Stays that have ended.** A stay whose check-out date is before today never changes from its
  feed. One first seen after it ended is recorded as ended, with no event.
- **Overlaps.** A reservation from a feed that would overlap a confirmed one is not saved. It waits
  as an overlap (`CalendarEventNeedsReview`, with a WhatsApp alert), and is imported once the
  double booking is resolved on the platforms and the feeds no longer overlap.
- **Idempotence.** Running the sync twice with the same feed produces no events.
- **Alerts.** Admin alerts go by WhatsApp to the configured admin number, through the outbox.
- **Feed health.** A sync of one feed fails when the fetch errors (network, HTTP status, unparseable
  content) or when it returns no events while that feed still has future confirmed reservations.
  A failed sync changes nothing: no reservation is cancelled, rescheduled or added from that feed.
- When a feed has kept failing for longer than the alert threshold (configuration, default 2 h =
  4 consecutive syncs), `CalendarFeedFailing(property_id, channel, since)` is raised and the admin
  receives one WhatsApp alert for that incident. The next successful sync ends the incident; a new
  incident alerts again.
- An empty feed is accepted only when the admin confirms it (e.g. listing closed, all bookings
  cancelled); its future reservations are then cancelled as usual.

`StayEnded` is raised by a scheduled job (12:00 Athens). It is raised once for every confirmed
stay whose check-out date has come, so a day the job missed is caught up.

### Validation details (Phase 3 — to be confirmed by Petros)
- **Alert threshold.** A feed's alert fires when it has been failing for at least the threshold,
  counted from its first failed sync.
- **Not modified.** A sync that the server answers with "not modified" (ETag) succeeds and changes
  nothing.
- **Reappearing UID.** The UID of a cancelled reservation that comes back in the feed is a new
  reservation.
- **Event times.** A feed event with a time, not just a date, takes its date in Athens.
- **Unreadable events.** An event with no UID or no valid dates makes its feed's read fail:
  nothing changes, and the admin is alerted after the threshold. Skipped instead, its
  reservation would be cancelled.
  - An event may give its length (DURATION) instead of its end.
  - An all-day event with neither lasts one day (RFC 5545).
- **Long validators.** An ETag or Last-Modified too long to store is ignored, and the feed is then
  read whole every time.
- **Stale reads.** A read is applied only if, while it was fetched:
  - the property stayed active;
  - the feed kept its link;
  - no newer read was applied, e.g. the admin's "sync now".
- **Extended stays.** A stay that ended and is then extended on its platform has not ended any
  more: StayEnded is raised again on its new check-out date.
- **Reactivation.** A property that becomes active again starts its feeds' health afresh: an old
  incident never silences a new one.
- **"Not modified".** A "not modified" answer withdraws the admin's empty-calendar confirmation,
  since the feed has its earlier content again.
- **History.** Stays that ended before KosPM learned of them are recorded as history, without the
  overlap check.

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

Owners log in (the login and the onboarding pages exist since Phase 2b, ADR 0017) and see: their
properties and onboarding status, reservations, money per reservation,
payouts, approved issues/charges, documents (contract, declarations), website-consent setting.
Built as read models (queries), never touching aggregates directly.

## 13. Public website (phase 3)

Next.js site for owners looking for management. Dynamic content via public API: number of managed
properties, owners with `show_on_website = True` (name/logo), testimonials, managed in Django admin.

**The form.** An `OwnerLead` needs a name and a phone number we can call; what the form does not offer
counts as not stated. It is not an `Owner`: nothing is registered, and the IKE gets an email and calls
back. Bots hear "ok" and send nothing, and one visitor's requests are limited (ADR 0021).

---

## 14. Open questions (do not implement guesses)
- Accountant: tax treatment IKE ↔ owner (sublease vs management fee).
- Accountant: exact guest fields required in the AADE declaration; retention period.
- Accountant: climate resilience fee rates per season / property type.
- **ΤΑΚ in the owner portal (Petros, 2026-11-12), for Phases 10–12.** Petros wants the owner to see,
  for the previous month, the nights booked and the fee they owe, e.g. 20 nights × 8 € in the summer
  season, together with the RF payment code to pay it. This conflicts with §10 and §11 as written:
  there the guest pays the fee on the platform, it passes through to the state, and the IKE
  declares. Before building it, settle:
  - who declares and pays the fee, the owner or the IKE;
  - whether the fee the guests paid reaches the owner, e.g. in the payout;
  - where the RF code comes from, and whether KosPM shows it or produces it;
  - the rates per season and property type (above).
- Consumables cost per cleaning (for margin reporting).
- E-signature provider (gov.gr digital signature by the owner?) — with the lawyer.
- ΑΜΑ under the sublease model: always a new ΑΜΑ in the IKE's name, or can an owner's existing ΑΜΑ
  be used? — accountant/lawyer.
- One contract per owner or one per property? — lawyer.
- Privacy notice for owner accounts (GDPR Art. 13) — lawyer. It must name Anthropic, which
  reads the listing text owners paste (ADR 0019).
- May an owner upload a new signed contract, e.g. for a renegotiated draft? Today a recorded
  contract changes through the IKE.
- Should a profile be refused when its directions contain the stored lockbox code? The guests'
  assistant may answer from the directions (§7), so a code there would bypass the code rule.
- A limit on listing readings for the whole platform per hour (cost), besides the one per owner?
- Bank payee check `NOT_POSSIBLE`: today it always means the test transfer was sent. Should
  the admin be able to record "not possible, not sent", and what happens to the account then?
- May payouts go to an account whose holder is not the owner (a spouse, a company)? Today the
  admin compares the payee with the owner's name and decides.
- Whether the WhatsApp `wa.me` link survives Airbnb's message filter (test on a real booking).
