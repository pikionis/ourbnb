# 0018 — Bank account verification: manual test transfer checked by the bank's payee check

- Status: accepted
- Date: 2026-10-28

## Context
Before the IKE pays an owner, it must know that the IBAN exists, accepts transfers and belongs to
the owner. DOMAIN §5 verifies it with a €0.01 test transfer that carries a 6-digit code in its
reference: the owner reads the code on their statement and enters it. Phase 2 built this with the
admin sending the transfer by hand. DOMAIN §14 left open which provider could automate it. Volume
is tiny (tens of owners a year), and the IKE is not a payment institution.

Research on 2026-10-28 found:
- **Verification of Payee (VoP)** is mandatory for euro-area banks since 9 October 2025
  (Regulation (EU) 2024/886, Art. 5c), for standard and instant SEPA transfers.
  - It is free for the payer and answers match / close match / no match / not possible.
  - Eurobank, Piraeus and NBG show the result in business e-banking.
  - Banks outside the euro area have until July 2027.
  - In its first days about 31 % of Greek transfer orders failed the check, mostly on spelling, so
    the holder name must be written as the bank holds it.
- **Automatic transfers by API:**
  - Revolut Business has a payee name check and a payments endpoint with a reference, usable by a
    small company on its own account (company plans, roughly €10 a month).
  - Wise API tokens cannot fund transfers for EU accounts.
  - The Greek banks' APIs are for licensed providers or corporate contracts.
- **Open banking**, where the owner logs in at their own bank and the provider returns the holder's
  name: Enable Banking covers NBG, Piraeus, Alpha and Eurobank, with a monthly minimum and a
  contract. Tink, Plaid and TrueLayer do not cover Greek banks, and GoCardless Bank Account Data
  has closed new sign-ups.

## Decision
- The admin keeps sending the €0.01 transfer from the IKE's e-banking (`ManualBankAccountVerifier`).
- The owner gives the **account holder name exactly as the bank holds it**, next to the IBAN.
- When sending, the admin records the bank's **payee check** (`PayeeCheck`):
  - `MATCH`, or `CLOSE_MATCH` with the name the bank returned: the transfer is sent;
  - `NOT_POSSIBLE` (e.g. a bank outside the euro area): the admin may still send it, and the code
    alone is the proof;
  - `NO_MATCH`: nothing is sent, the verification stops, and the owner corrects the name or IBAN.
- A new state `TRANSFER_SENT` sits between `PENDING` and `VERIFIED`.
  - `PENDING` means the IKE has to send the transfer; `TRANSFER_SENT` means the owner has to enter
    the code.
  - A code is accepted only after the transfer is recorded as sent.
- The `BankAccountVerifier` port stays, so an automatic sender can replace the admin without
  changing the handlers.
  - **When admin time matters:** a Revolut Business adapter (name check, then a payment carrying
    the code).
  - That adapter only enqueues the transfer in the outbox, and the worker calls Revolut (ADR 0005).
  - The account keeps a small balance, uses an IP allow-list, and each payment has an idempotent
    request id.
  - **If volume grows:** open banking through Enable Banking.
- For Phase 10: payout batches keep VoP on (no bulk opt-out), so every payout checks the names
  again, for free.

Rejected for now:
- Wise: EU accounts cannot fund transfers by API.
- GoCardless Bank Account Data: sign-ups closed.
- Tink, Plaid, TrueLayer: no Greek banks.
- SurePay, iPiD, Banfico: offered to banks and large companies only.
- A reverse micro-deposit, where the owner sends €0.01 to the IKE: more effort for the owner and
  nothing gained over VoP.

## Consequences
- No new vendor, secret or personal-data processor, and no cost.
- The admin spends a few minutes per owner, and the admin's list shows who is waiting for a
  transfer.
- **The proof is stronger than before.**
  - The bank confirms that the name matches the IBAN, and the code proves the owner can read that
    account's statement.
  - The check proves whose account an IBAN is, not that it is the owner's. Someone who took
    over an owner's portal account before the verification could enter their own IBAN and their
    own name, and the bank would confirm them. So the admin compares the payee with the owner's
    name before sending; the admin's instructions show both and say so.
  - On top of that, the portal locks the IBAN once it is verified (DOMAIN §5).
- `NOT_POSSIBLE` accounts rely on the code only. The admin decides case by case, and the result
  stays recorded.
- Revisit the decision when onboarding volume makes the manual transfer a burden.

Sources (checked 2026-10-28):
- PwC on VoP: https://legal.pwc.de/en/news/articles/verification-of-payee-requirements-vop-under-the-eus-instant-payments-regulation-ipr
- Eurobank VoP guide: https://www.eurobank.gr/-/media/eurobank/business/business-academy/pdf/verification-of-payee.pdf
- Revolut Business API: https://developer.revolut.com/docs/api/business/operations/validate-account-name.md and https://developer.revolut.com/docs/api/business/operations/create-payment.md
- Wise personal tokens: https://docs.wise.com/guides/developer/auth-and-security/personal-api-token
- Enable Banking, Greece: https://enablebanking.com/docs/markets/gr/
