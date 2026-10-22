---
name: ddd-hexagonal
description: How to write domain models, repositories, unit of work, handlers, events and adapters in this repo (Cosmic Python style on Django). Use whenever creating or changing code inside a bounded context under backend/src/kospm/.
---
# DDD + hexagonal in this repo

Reference: *Architecture Patterns with Python* (cosmicpython.com), Appendix D for Django.

## Where things go
| Thing | Location | May import |
|---|---|---|
| Entity, Value Object, Aggregate, domain event, command, domain service | `<ctx>/domain/` | stdlib, `kospm.shared.domain`, own domain |
| Command/event handlers, abstract UoW and ports | `<ctx>/service_layer/` | own domain, shared |
| Django models, repositories, external APIs | `<ctx>/adapters/`, `<ctx>/models.py` | anything |
| API (Django Ninja), webhooks, admin, management commands | `<ctx>/entrypoints/` | service layer, adapters |
| Wiring of handlers and adapters | `kospm/bootstrap.py` | everything |

## Recipes

**Value object**
```python
@dataclass(frozen=True)
class GuestContact:
    phone: str
    channel: MessagingChannel
```

**Aggregate with invariant and events**
```python
class Property(Aggregate):
    def activate(self) -> None:
        missing = self._missing_for_activation()
        if missing:
            raise PropertyNotReadyForActivation(missing)
        self.status = PropertyStatus.ACTIVE
        self.events.append(PropertyActivated(property_id=self.id))
```

**Repository (port + Django adapter)**
```python
class PropertyRepository(Protocol):
    def get(self, property_id: PropertyId) -> Property: ...
    def add(self, prop: Property) -> None: ...

class DjangoPropertyRepository:
    def get(self, property_id):
        return to_domain(models.Property.objects.get(pk=property_id))
```
Fake for tests: a class holding a `dict`, same methods.

**Handler**
```python
def activate_property(cmd: ActivateProperty, uow: AbstractUnitOfWork) -> None:
    with uow:
        prop = uow.properties.get(cmd.property_id)
        prop.activate()
        uow.commit()   # events collected and published by the bus after commit
```

**External side effect** — never call WhatsApp from a handler directly:
`uow.outbox.enqueue(OutboxMessage(channel=..., template=..., payload=...))`.

## Testing
- Domain and handlers: `tests/unit/`, fakes only, no DB, milliseconds.
- Repositories and adapters: `tests/integration/`, `@pytest.mark.integration`, real Postgres.
- A few `tests/e2e/` per phase through the API or a management command.
- Time via `FixedClock`; money via `Money("12.00")`; never float.

## Smells to avoid
- Business rules in Django models, serializers, admin or views.
- A handler that loads two aggregates and changes both (use an event instead).
- Importing another context's domain model (use its ID and an event).
- `datetime.now()` or `float` anywhere in domain code.
