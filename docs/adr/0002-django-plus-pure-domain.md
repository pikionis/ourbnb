# 0002 — Django 5.2 LTS for infrastructure, domain in pure Python

- Status: accepted
- Date: 2026-10-22

## Context
We need a back-office, authentication, i18n (Greek/English), migrations and a mature ORM on
PostgreSQL, and Django provides all of them. The business rules in DOMAIN.md (activation
invariant, `plan_day`, money formulas) must be testable in milliseconds without a database and must
not depend on a web framework. *Architecture Patterns with Python* (Cosmic Python), Appendix D,
shows this split on Django.

## Decision
- Python 3.12, pinned in `backend/.python-version`.
- Django 5.2 LTS (`django>=5.2.18,<5.3` in `backend/pyproject.toml`), supported until April 2028. A move to 6.x happens only as a
  deliberate upgrade.
- Django Ninja for the JSON API (owner portal, public API). It is added in the phase that first
  needs it, not before.
- The domain model is plain Python: dataclasses, Enums and `Decimal`. Django models in
  `<context>/models.py` are persistence only. Repositories in `<context>/adapters/repository.py`
  map ORM rows to domain objects and back (`to_domain()` / `from_domain()`) and return domain
  objects, never Django models.
- Settings are split into `config.settings.base`, `dev`, `prod` and `test`. Secrets come from
  environment variables (django-environ; in development, the repo-root `.env`). There is no
  `ATOMIC_REQUESTS`, because the Unit of Work owns transactions. The custom user model
  `identity.User` exists from the first migration.

## Consequences
- Domain and handler tests run with fake repositories, with no Django and no database.
- Every aggregate needs an explicit mapping layer. That is more code than "fat models", but business
  rules cannot leak into models, forms or the admin.
- Django features that treat the model as the domain (ModelForms that save directly, signals with
  business logic) are not used for data that has invariants.
- Windows has no system timezone database, so `tzdata` is a runtime dependency.
- The upgrade to the next LTS (6.2, expected April 2027) is planned work before April 2028.
