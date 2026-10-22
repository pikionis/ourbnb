---
description: Apply a business-rule change — docs first, then code
argument-hint: <the rule change, in plain words>
---
The business rule changes: **$ARGUMENTS**

1. Find every place in `docs/DOMAIN.md` affected and propose the exact text change. Wait for approval.
2. After approval, update DOMAIN.md, then list the code and tests affected.
3. Change the tests first (they must fail), then the code, then run `make check`.
4. If the change contradicts an ADR or another rule, stop and ask.
