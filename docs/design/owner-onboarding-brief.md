# Owner onboarding — design brief (Phase 2b)

- Status: approved direction, 2026-10-28. Screens are built from this brief; changes to it are
  discussed with Petros first.
- Rules: `docs/DOMAIN.md` §5 (checklist, owner portal, bank account). Decisions: ADR 0017
  (server-rendered pages, Django auth), ADR 0018 (bank account verification).

## 1. Why

Today the admin types in every owner's data and chases missing checklist items by phone. In Phase
2b owners register and complete the activation checklist themselves. Success means an owner gets
from sign-up (or an invitation) to "only the ΑΜΑ is missing" without calling us. We watch three
signals: how long onboarding takes, how many support calls it causes, and which form errors repeat.

## 2. Who uses it

- **Owners on Kos.** Most are Greek, many are over 45, and most will use a phone, often in between
  other things. Some are foreign owners who read English. They know e-banking and gov.gr but not
  web apps, and they often hand paperwork to a relative or their accountant.
- **The admin (Petros)** follows the same checklist in the Django admin and is not a user of these
  pages.

Constraints: slow mobile data outside the town, photos taken on the spot, documents signed on
gov.gr in another tab, and some users who have the account set up for them by a relative.

## 3. Principles

1. **One job per page.** The dashboard always says what comes next.
2. **Plain words in the owner's language.** Greek by default with an English toggle, formal
   "εσείς", and the terms of the glossary (DOMAIN §3).
3. **Mobile first, no JavaScript needed.** Large targets (at least 44 px), labels above fields,
   errors next to the field plus a summary at the top.
4. **Show progress, never blame.** Every error says how to fix it (the domain's refusals are
   translated in `entrypoints/texts.py`).
5. **Earn trust.** Say who we are, why we ask for the ΑΦΜ and the IBAN, and what we never ask for:
   gov.gr, bank or platform passwords.
6. **Fast and private.** No third-party scripts, fonts, analytics or maps; one stylesheet; a page
   without photos stays under 100 KB.
7. **Secrets stay secret.** Lockbox codes are typed into masked fields and never shown again. The
   IBAN is shown only to its owner.

## 4. Journeys

**J1 — Sign up (self-registration)**
1. Create account: email and password. The page links to the privacy notice.
2. "Check your email" page, with a "send it again" form.
3. The link in the email confirms the address and leads to the login page.
4. Login, then the "Your details" form (J3).

The account reserves the id of the owner it will be linked to, so step 1 of the onboarding
(`RegisterOwner`) uses that id.

**J2 — Invitation (owner registered by the admin)**
1. The admin presses "Invite to the portal" on the owner's page.
2. The email (Greek and English, because we do not know the owner's language yet) holds a link to
   "Choose your password".
3. After choosing a password the owner logs in. Their details are already filled in, and they
   check them.

**J3 — Your details (onboarding step 1)**
The owner enters name, phone, ΑΦΜ, IBAN and the account holder's name. The email is the login
email, shown and not editable. If another owner already has that ΑΦΜ or email, the form says so and
points to "contact us" (DOMAIN §5: an account never attaches itself to an existing owner).

**J4 — Bank account**
1. The owner presses "Verify my account". The page says we will send €0.01 with a 6-digit code in
   its reference.
2. The admin sends the transfer and records the bank's name check. On "no match" the owner sees
   why and corrects the holder name or the IBAN.
3. Once the transfer is sent, the owner sees a code field with the hint "it may take 1–2 working
   days to appear on your statement".
4. After the right code the account shows "Verified" and is locked: changes go through the IKE
   (ADR 0018).

**J5 — Add and complete a property**
1. "Add a property": the owner gives a name, and the code is assigned automatically (e.g.
   `KOS-014`).
2. The property page shows its checklist in onboarding order (DOMAIN §5): profile, contract,
   sublease declaration, ΑΜΑ (done by us), bank account.
3. Each row leads to its own page.

**J6 — Fill the profile from listing text (AI)**
1. On the profile page, "Fill in from your listing" opens a text box for pasting the listing text
   (not its link).
2. The profile form comes back filled in. Fields that came from the text are marked "check this".
3. Nothing is saved until the owner presses Save. Lockbox codes are never filled in.

**J7 — Contract**
1. The owner downloads the contract the IKE prepared for this property. If there is none yet, the
   page says "we are preparing it".
2. They sign it themselves (e.g. on gov.gr) and upload the signed PDF. The page reminds them that
   we never ask for their credentials.

**J8 — Sublease declaration**
One field for the number of the declaration filed at AADE by the owner or their accountant, with a
help text that says what it is.

**J9 — Forgot password**
Email → "if an account exists we sent a link" (the same answer either way) → new password → login.

**J10 — Everywhere**
A language toggle (ΕΛ | EN), log out, and a "contact us" link in the footer.

## 5. Pages

| Page | URL | States | Main action |
|---|---|---|---|
| Login | `/owner/login/` | normal, wrong credentials, email not confirmed (with resend), throttled | Log in |
| Create account | `/owner/signup/` | normal, field errors, email taken (generic wording), throttled | Create account |
| Check your email | `/owner/signup/sent/` | — | Send again |
| Confirm email | `/owner/verify/<id>/<token>/` | confirmed → login; expired or used | — |
| Choose password (invitation) | `/owner/invitation/<id>/<token>/` | form; expired or used | Save password |
| Forgot / reset password | `/owner/password/…` | request, sent, new password, done, expired | Send / Save |
| Dashboard | `/owner/` | no details yet (only J3 open); details done (bank and properties open) | Next missing item |
| Your details | `/owner/details/` | first time (register); later (edit name and phone) | Save |
| Bank account | `/owner/bank/` | unverified, waiting for our transfer, transfer sent (code form), no name match, verified (locked) | Request verification / Confirm code |
| Add a property | `/owner/properties/new/` | — | Add |
| Property | `/owner/properties/<code>/` | onboarding (checklist with links), active / inactive / offboarded (read-only) | Next missing item |
| Profile | `/owner/properties/<code>/profile/` | empty, partly filled, complete, filled in from the listing (unsaved) | Save |
| Listing text | `/owner/properties/<code>/listing/` | form, AI unavailable or limit reached | Fill in the profile |
| Contract | `/owner/properties/<code>/contract/` | not prepared yet, ready to download, signed (download both) | Upload signed PDF |
| Sublease declaration | `/owner/properties/<code>/sublease/` | empty, recorded (can be corrected, not removed) | Save |
| Privacy notice | `/owner/privacy/` | placeholder until the lawyer's text | — |
| File | `/owner/files/<code>/<kind>/` | served only to the property's owner | — |

## 6. Who changes what

| Item | Owner in the portal | IKE in the admin |
|---|---|---|
| Name, phone | yes | yes |
| Email | no (the login email; contact us) | yes |
| ΑΦΜ | at registration only | yes |
| IBAN, holder name | until the account is verified | yes |
| Property name, address, coordinates, guide, photos, lockbox codes, amenities | while the property is `ONBOARDING` | yes |
| Contract to sign (PDF and terms) | download | upload |
| Signed contract | upload, while `ONBOARDING` | upload |
| Sublease declaration number | while `ONBOARDING` | yes |
| ΑΜΑ, calendar feeds, preferred cleaner, linen sets, check-in/out times | not shown | yes |
| Activation | no ("we activate it when everything is ready") | yes |

## 7. Wireframes (360 px wide)

Dashboard:
```
+--------------------------------------+
| [logo] KosPM                ΕΛ | EN  |
+--------------------------------------+
| Καλώς ήρθατε, Μαρία                  |
| Ας ετοιμάσουμε τα ακίνητά σας.       |
|                                      |
| (✓) Τα στοιχεία σας               >  |
| (…) Τραπεζικός λογαριασμός        >  |
|     Θα σας στείλουμε €0,01           |
|                                      |
| Τα ακίνητά σας                       |
| +----------------------------------+ |
| | Villa Elena · KOS-014            | |
| | Σε εξέλιξη · 3 από 5 έτοιμα    > | |
| +----------------------------------+ |
| [ + Προσθήκη ακινήτου ]              |
|                                      |
| Επικοινωνία · Προσωπικά δεδομένα     |
+--------------------------------------+
```

Property (onboarding):
```
+--------------------------------------+
| < Τα ακίνητά σας                     |
| Villa Elena                          |
| KOS-014 · Σε εξέλιξη                 |
|                                      |
| Τι χρειάζεται για να ξεκινήσει       |
| (✓) 1 Προφίλ και οδηγίες          >  |
| (!) 2 Συμβόλαιο                   >  |
|     Κατεβάστε, υπογράψτε, ανεβάστε   |
| (!) 3 Δήλωση υπεκμίσθωσης         >  |
| (…) 4 ΑΜΑ · το καταχωρίζουμε εμείς   |
| (…) 5 Τραπεζικός λογαριασμός      >  |
|                                      |
| Όταν όλα είναι έτοιμα, ενεργοποιούμε |
| εμείς το ακίνητο.                    |
+--------------------------------------+
```

Bank account, transfer sent:
```
+--------------------------------------+
| < Αρχική                             |
| Τραπεζικός λογαριασμός               |
| GR16 0110 1250 0000 0001 2300 695    |
| Δικαιούχος: PAPADOPOULOU MARIA       |
|                                      |
| (i) Στείλαμε €0,01 στις 28/10. Ο     |
|     6ψήφιος κωδικός είναι στην       |
|     αιτιολογία της μεταφοράς.        |
|                                      |
| Κωδικός                              |
| [ _ _ _ _ _ _ ]                      |
| [        Επιβεβαίωση          ]      |
+--------------------------------------+
```

Profile (excerpt):
```
| Διεύθυνση                            |
| [ Λάμπη, Κως 853 00              ]   |
| Συντεταγμένες                        |
| [ 36.89301, 27.28770             ]   |
| Στο Google Maps πατήστε παρατεταμένα |
| στο σπίτι και αντιγράψτε τους        |
| αριθμούς.                            |
| Φωτογραφία εξωτερικού χώρου          |
| [ εικόνα ]  [ Αλλαγή φωτογραφίας ]   |
| Κωδικός κουτιού κλειδιών (επισκέπτες)|
| [ ●●●● ] Αποθηκευμένος · Αλλαγή      |
| Παροχές                 Ναι   Όχι    |
| Wi-Fi                   (•)   ( )    |
| Κλιματισμός             (•)   ( )    |
| Πισίνα                  ( )   (•)    |
| Άλλες παροχές (μία ανά γραμμή)       |
```

## 8. Content

- **Voice.** Polite and short, the way a good office answers the phone: "Συμπληρώστε…", "Θα σας
  στείλουμε…". English is plain and friendly ("Fill in…", "We will send you…").
- **Help texts** (Greek / English) for the fields people get wrong:
  - **Account holder.** «Γράψτε το όνομα όπως το έχει η τράπεζά σας, συνήθως με λατινικά κεφαλαία
    (π.χ. PAPADOPOULOU MARIA).» / "Write the name exactly as your bank holds it, often in Latin
    capitals (e.g. PAPADOPOULOU MARIA)."
  - **Code.** «Ο 6ψήφιος κωδικός από την αιτιολογία της μεταφοράς των €0,01.» / "The 6-digit code
    in the reference of our €0.01 transfer."
  - **Sublease declaration.** «Ο αριθμός της δήλωσης υπεκμίσθωσης που υποβάλατε εσείς ή ο λογιστής
    σας στην ΑΑΔΕ.» / "The number of the sublease declaration that you or your accountant filed
    with AADE."
  - **Contract.** «Υπογράψτε το ψηφιακά, π.χ. στο gov.gr, με τους δικούς σας κωδικούς. Εμείς δεν
    ζητάμε ποτέ τους κωδικούς σας.» / "Sign it digitally, e.g. on gov.gr, with your own
    credentials. We never ask for your passwords."
  - **Lockbox code.** «Ο κωδικός του κουτιού κλειδιών για τους επισκέπτες. Δεν εμφανίζεται ξανά
    μετά την αποθήκευση.» / "The key box code for guests. It is not shown again after saving."
  - **Listing text.** «Επικολλήστε το κείμενο της αγγελίας σας, όχι τον σύνδεσμο. Συμπληρώνουμε
    όσα πεδία βρούμε και εσείς τα ελέγχετε πριν την αποθήκευση.» / "Paste the text of your
    listing, not its link. We fill in what we find, and you check it before saving."
- **Known refusals.**
  - **Duplicate ΑΦΜ / email.** «Υπάρχει ήδη ιδιοκτήτης με αυτό το ΑΦΜ. Επικοινωνήστε μαζί μας για
    να σας στείλουμε πρόσκληση.»
  - **Expired link.** «Ο σύνδεσμος έληξε ή χρησιμοποιήθηκε ήδη. Ζητήστε νέο.»
  - **Throttled.** «Πολλές προσπάθειες. Δοκιμάστε ξανά σε λίγα λεπτά.»
  - **Locked after activation.** «Το ακίνητο είναι ενεργό. Για αλλαγές επικοινωνήστε μαζί μας.»
- **Amenities offered as Yes / No.** Wi-Fi, air conditioning, heating, kitchen, washing machine,
  dishwasher, free parking, pool, sea view, balcony or terrace, baby cot, hair dryer, iron, TV.
  Unanswered items stay unknown. Extras are typed one per line. The stored names are the English
  ones, so the list reads the same in the admin and to the AI.
- **Coordinates.** One field takes "36.89301, 27.28770", as Google Maps copies it after a long
  press. More than 6 decimals are rounded to 6 (about 10 cm). No map widget in 2b, because maps
  would need a third-party script.

## 9. Visual direction

There is no IKE brand yet, so the pages use a neutral placeholder that a logo and two colours can
replace later.

- **Colours** (CSS custom properties):
  - background `#f7f5f0` (warm limestone), surface `#ffffff`, text `#1f2933`, muted text
    `#5b6672`, borders `#d9d4ca`;
  - accent `#0b5d8c` (Aegean blue) for buttons and links;
  - states: done `#15803d`, waiting `#1d4ed8`, missing `#b45309`, error `#b42318`, neutral
    `#6b7280`. These match the admin's badges.
  - A state is never shown by colour alone: it always has an icon and a word.
- **Type.** The system font stack, 17 px base size, line height 1.5, headings at 1.5 and
  1.25 rem.
- **Layout.** One column, at most 40 rem wide, 16 px side margins. Buttons are full width on
  phones.
- **Components:**
  - header (name or logo, language toggle, log out) and footer (contact, privacy);
  - page title with a back link;
  - checklist row (icon, label, status text, chevron) and card;
  - primary and secondary buttons;
  - field with label, help text and error;
  - file field (current file plus "replace") and masked field ("stored · change");
  - alerts (info, success, warning, error) and status badge.
- **Theme.** Light only in 2b.

## 10. Quality bar

- **Accessibility:** WCAG 2.2 AA.
  - Contrast of at least 4.5:1 and a visible focus.
  - Every field has a label and the right `autocomplete` (`email`, `current-password`,
    `new-password`, `name`, `tel`).
  - `inputmode="numeric"` for the code and the ΑΦΜ.
  - An error summary that links to the fields, and a `lang` attribute that follows the toggle.
- **Checked** at 360×640, at 200 % zoom and with the keyboard only.
- **Photos.** JPG, PNG, WebP and HEIC up to 15 MB (configuration). Uploaded photos are shown
  scaled down; HEIC files, which most browsers cannot show, appear as "photo uploaded ✓".

## 11. Security and privacy in the interface

- **Links in emails** (verification, invitation, password reset) work once and expire.
- **Passwords.** Password rules are shown before the owner types, and no page says whether an email
  has an account.
- **Throttling.** Login, sign-up and reset are throttled.
- **Files.** Every page and file is scoped to the logged-in owner: another owner's property is
  "not found".
- **Lockbox codes.** Masked inputs with `autocomplete="off"`, never echoed back. The IBAN is shown
  in full only on the bank page.
- **Forms.** Every form is CSRF-protected, and log-out is a POST.

## 12. Not in Phase 2b

- The v3 portal content: reservations, statements, payouts, a documents list and the website
  consent toggle (Phase 12).
- Reminders and notifications to owners or the admin. Missing items show on the dashboard only.
- A map picker, changing the login email, two-factor login, access for an owner's accountant, and
  closing an account (handled by the admin on request).

## 13. Inputs still needed from Petros

- The IKE's name, logo and two brand colours.
- Contact details for "contact us": phone, email, WhatsApp.
- The privacy notice for owner accounts, from the lawyer (DOMAIN §14).
- The contract PDFs to upload per property, from the lawyer.
- The sender address and SMTP provider for emails (Phase 7). Development prints emails to the
  console.
