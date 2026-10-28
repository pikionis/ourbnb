# 0019 — Listing text read by the Claude API into a draft profile

- Status: accepted
- Date: 2026-10-28

## Context
Most owners already have a listing on Airbnb or Booking.com. It has the description, the
amenities and often the directions. Typing all of it again into the portal is the slowest
onboarding step (design brief J6).

Two rules limit how the portal can use a listing:
- The platform never fetches a listing by its URL (ADR 0012, DOMAIN §2.1).
- The AI only interprets text; it never decides a business rule (DOMAIN §2.4).

Petros approved the `anthropic` dependency and sending the text an owner pastes to Anthropic, with
a configurable model.

## Decision
- **What the owner does.** The owner pastes the text of their listing (never its link) on the
  portal's "Fill in from your listing" page.
- **What the AI does.** The Claude API reads the text into a draft of the profile: address,
  directions in Greek and English, and amenities.
- **What happens to the draft.**
  - It only pre-fills the profile form, and fills only the fields the owner left empty.
  - The owner checks it, with the filled fields marked "check this", and saves with the usual
    `UpdatePropertyProfile`.
- **Ports and adapters.**
  - The port is `ListingTextExtractor`, in the service layer.
  - `ClaudeListingExtractor` uses the official SDK.
  - `UnavailableListingExtractor` is used when `ANTHROPIC_API_KEY` is empty; the owner then fills
    in the profile by hand.
- **The request treats the text as data.**
  - The text is sent inside `<listing>` tags, and the system prompt says to take facts only and
    never to follow instructions written in the text.
  - The answer must fit a JSON schema that has no field for a code (structured outputs).
  - No tools are offered.
  - On a refusal, the API retries on a fallback model by itself (`fallbacks: "default"`, beta
    `server-side-fallback-2026-07-01`).
  - Any failure ends as `ListingNotRead`, and the owner fills in the profile by hand.
- **Configuration.**
  - The model and effort default to `claude-opus-5-5` and `low`.
  - The timeout is 60 s, with one retry.
  - The text is at most 20,000 characters.
  - An owner may have text read 10 times an hour.

## Consequences
- **Faster onboarding.** The owner still adds the photos and the key-box code, which the draft
  never contains.
- **Personal data goes to a processor.**
  - The pasted text goes to Anthropic. KosPM does not keep it, log it or put it in error reports.
  - Anthropic keeps API inputs and outputs for a limited time under its own policy, unless a
    zero-data-retention agreement applies.
  - The page tells the owner who reads the text and asks them not to paste codes or passwords.
  - The privacy notice (DOMAIN §14, with the lawyer) must name Anthropic and any transfer of the
    data outside the EU.
- **A new vendor, secret and cost.**
  - Set a monthly spend limit for the key in the Anthropic Console.
  - The per-owner limit caps the cost per account. A global limit is an open question.
- **Codes in the directions.** The directions are free text. The model is asked not to copy codes
  into them, but only the owner's check guarantees it. An open question asks whether a save should
  be refused when the directions contain the stored code.
- **The page waits for the answer.** The web server's timeout must be longer than twice the
  extractor's timeout (Phase 7).
- **SDK changes are caught.** The SDK is pinned to its major version (`anthropic>=2.3,<3`). A test
  runs the real SDK against a mock transport, so a change in the SDK fails the build, not an
  owner's page.
