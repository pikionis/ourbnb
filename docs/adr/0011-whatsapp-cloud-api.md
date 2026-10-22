# 0011 — WhatsApp through Meta's WhatsApp Cloud API

- Status: accepted
- Date: 2026-10-22

## Context
Cleaners, the admin and, in v2, guests already use WhatsApp. The platform sends daily schedules,
"schedule changed" notices and admin alerts, and it receives guest messages. WhatsApp has two rules
(DOMAIN.md §7):
- business-initiated messages must use pre-approved templates;
- free-form text is allowed only within 24 hours of the user's last message.

## Decision
We use the **Meta WhatsApp Cloud API** (Graph API) directly, without an intermediary provider.
- Only the outbox worker sends outbound messages, through the `MessageSender` port.
  `WhatsAppCloudSender` is used in production and `ConsoleSender` in development and tests.
- Templates are **versioned in code** in `messaging/templates.py`. Each one has a name, Greek and
  English variants, and a parameter order.
- `whatsapp_sync_templates` creates or updates the templates through the API. Petros runs it by
  hand with his token.
- The **24-hour window rule** lives in code: free text inside the window, a template otherwise.
- The inbound webhook `/webhooks/whatsapp/` does the following:
  - verifies the handshake token and the `X-Hub-Signature-256` signature;
  - stores the raw message;
  - stays idempotent per message id;
  - emits `InboundMessageReceived`.
- The access token and the app secret come only from environment variables.

## Consequences
- Meta must approve a template before it can be used, so the code and Meta can drift apart. The sync
  command and a parameter-rendering test keep them aligned.
- Meta bills business-initiated template messages, so the volume needs watching.
- Delivery is at-least-once (ADR 0005), so message texts are written to be harmless if they
  arrive twice.
- Another channel (e.g. Viber, in the backlog) needs a new adapter, not domain changes.
