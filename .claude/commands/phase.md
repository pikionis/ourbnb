---
description: Start or continue a phase from docs/BUILD_PLAN.md
argument-hint: <phase number>
---
We work on **Phase $ARGUMENTS** of `docs/BUILD_PLAN.md`, and only that phase.

1. Re-read `CLAUDE.md`, the Phase $ARGUMENTS section of `docs/BUILD_PLAN.md`, and the sections of
   `docs/DOMAIN.md` that this phase touches.
2. Check which boxes of this phase are already ticked and what exists in the repo.
3. Present a plan: files to create or change, the tests you will write first, and any open question
   from DOMAIN.md that blocks this phase. Name the Cosmic Python pattern behind each part.
4. Wait for my approval. Then work test-first, task by task, ticking boxes in BUILD_PLAN.md.
5. Finish with `make check` green and a short summary in Greek of what was built and why.
