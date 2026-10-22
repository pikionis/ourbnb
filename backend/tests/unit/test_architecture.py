"""Architecture rules that the import-linter contracts cannot express (ADR 0013).

1. Every DomainEvent and Command, in every context, is a frozen keyword-only dataclass.
2. Pure layers reach, directly or through any chain of imports, only the standard library and
   pure kospm modules; a domain reaches only `kospm.shared.domain` and its own domain. The
   import-linter "forbidden" contracts are deny-lists, so a new third-party package, or a kospm
   module outside the listed layers (say `kospm.messaging.templates`), would slip through them;
   this test is the allow-list that closes that gap.
"""

import dataclasses
import importlib
import pkgutil
import sys
from collections.abc import Iterator

import grimp

import kospm
from kospm.shared.domain import Command, DomainEvent

# Modules outside a domain/ or service_layer/ package that must stay free of Django and friends.
PURE_MODULES = frozenset(
    {"kospm.shared.messagebus", "kospm.shared.unit_of_work", "kospm.shared.clock"}
)
PURE_SEGMENTS = frozenset({"domain", "service_layer"})


# --- 1. Messages are immutable value objects --------------------------------------------------


def _import_every_kospm_module() -> list[str]:
    """Import all of kospm (migrations aside), so that every message class is defined."""
    imported = []
    for module in pkgutil.walk_packages(kospm.__path__, prefix=f"{kospm.__name__}."):
        if "migrations" in module.name.split("."):
            continue
        importlib.import_module(module.name)
        imported.append(module.name)
    return imported


def _subclasses(base: type) -> Iterator[type]:
    for subclass in base.__subclasses__():
        yield subclass
        yield from _subclasses(subclass)


def _message_class_problems(cls: type) -> list[str]:
    # The class itself must be decorated: a plain subclass of a frozen dataclass is mutable.
    params = vars(cls).get("__dataclass_params__")
    if params is None:
        return ["not decorated with @dataclass(frozen=True, kw_only=True)"]
    problems = []
    if not params.frozen:
        problems.append("not frozen")
    if not params.kw_only or not all(field.kw_only for field in dataclasses.fields(cls)):
        problems.append("not kw_only")
    return problems


def test_every_domain_event_and_command_is_a_frozen_keyword_only_dataclass() -> None:
    imported = _import_every_kospm_module()
    assert "kospm.shared.domain.messages" in imported

    classes = [DomainEvent, Command, *_subclasses(DomainEvent), *_subclasses(Command)]
    problems = {
        f"{cls.__module__}.{cls.__qualname__}": found
        for cls in classes
        if (found := _message_class_problems(cls))
    }
    assert problems == {}


def test_the_message_check_reports_mutable_positional_or_undecorated_classes() -> None:
    @dataclasses.dataclass
    class Mutable:
        value: int

    @dataclasses.dataclass(frozen=True)
    class Positional:
        value: int

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class Good:
        value: int

    class Undecorated(Good):
        extra: int = 0

    assert _message_class_problems(Mutable) == ["not frozen", "not kw_only"]
    assert _message_class_problems(Positional) == ["not kw_only"]
    assert _message_class_problems(Good) == []
    assert _message_class_problems(Undecorated) != []


# --- 2. Pure layers: standard library + pure kospm modules -------------------------------------

SHARED_DOMAIN = f"{kospm.__name__}.shared.domain"


def _is_kospm(module: str) -> bool:
    return module == kospm.__name__ or module.startswith(f"{kospm.__name__}.")


def _within(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


def _must_be_pure(module: str) -> bool:
    return module in PURE_MODULES or not PURE_SEGMENTS.isdisjoint(module.split("."))


def _domain_of(module: str) -> str | None:
    """The domain package (or module) that `module` belongs to, if any."""
    parts = module.split(".")
    if "domain" not in parts:
        return None
    return ".".join(parts[: parts.index("domain") + 1])


def _is_stdlib(module: str) -> bool:
    return module.split(".")[0] in sys.stdlib_module_names


def _may_reach(module: str, reached: str) -> bool:
    """May pure `module` import `reached`, directly or through other modules?"""
    if not _is_kospm(reached):
        # External packages appear in the graph as their top-level name ("django", "grimp").
        return _is_stdlib(reached)
    domain = _domain_of(module)
    if domain is not None:
        return _within(reached, SHARED_DOMAIN) or _within(reached, domain)
    return _must_be_pure(reached)


def _purity_violations(graph: grimp.ImportGraph) -> dict[str, list[str]]:
    """Every pure kospm module mapped to what it reaches but must not, transitively."""
    violations = {}
    for module in sorted(graph.modules):
        if not (_is_kospm(module) and _must_be_pure(module)):
            continue
        bad = sorted(
            reached
            for reached in graph.find_upstream_modules(module)
            if not _may_reach(module, reached)
        )
        if bad:
            violations[module] = bad
    return violations


def test_pure_layers_reach_only_the_standard_library_and_pure_kospm_modules() -> None:
    graph = grimp.build_graph(kospm.__name__, include_external_packages=True, cache_dir=None)
    pure = {module for module in graph.modules if _is_kospm(module) and _must_be_pure(module)}
    assert {
        "kospm.shared.domain.messages",
        "kospm.shared.domain.local_time",
        "kospm.shared.clock",
        "kospm.shared.unit_of_work",
        "kospm.shared.messagebus",
        "kospm.shared.outbox.domain",
        "kospm.shared.outbox.service_layer.ports",
    } <= pure

    assert _purity_violations(graph) == {}


def _graph(*imports: tuple[str, str]) -> grimp.ImportGraph:
    graph = grimp.ImportGraph()
    for importer, imported in imports:
        graph.add_import(importer=importer, imported=imported)
    return graph


def test_a_third_party_package_reached_through_a_helper_is_a_violation() -> None:
    graph = _graph(
        ("kospm.shared.domain.canary", "kospm.shared.helpers"),
        ("kospm.shared.helpers", "typing_extensions"),
    )

    assert _purity_violations(graph) == {
        "kospm.shared.domain.canary": ["kospm.shared.helpers", "typing_extensions"]
    }


def test_a_domain_reaches_only_the_shared_domain_and_its_own_domain() -> None:
    graph = _graph(
        ("kospm.properties.domain.model", "kospm.properties.domain.events"),
        ("kospm.properties.domain.model", "kospm.shared.domain"),
        ("kospm.properties.domain.model", "decimal"),
        ("kospm.properties.domain.model", "kospm.properties.templates"),
        ("kospm.properties.domain.model", "kospm.housekeeping.domain"),
        ("kospm.shared.domain.money", "kospm.shared.config"),
        ("kospm.shared.domain.money", "kospm.shared.clock"),
    )

    assert _purity_violations(graph) == {
        "kospm.properties.domain.model": [
            "kospm.housekeeping.domain",
            "kospm.properties.templates",
        ],
        "kospm.shared.domain.money": ["kospm.shared.clock", "kospm.shared.config"],
    }


def test_a_service_layer_reaches_only_pure_modules() -> None:
    graph = _graph(
        ("kospm.properties.service_layer.handlers", "kospm.properties.domain"),
        ("kospm.properties.service_layer.handlers", "kospm.shared.unit_of_work"),
        ("kospm.properties.service_layer.handlers", "kospm.properties.templates"),
        ("kospm.properties.templates", "sqlparse"),
        ("kospm.shared.unit_of_work", "collections.abc"),
    )

    assert _purity_violations(graph) == {
        "kospm.properties.service_layer.handlers": ["kospm.properties.templates", "sqlparse"]
    }


def test_only_the_standard_library_counts_as_external() -> None:
    assert _may_reach("kospm.shared.clock", "zoneinfo")
    assert _may_reach("kospm.shared.clock", "collections.abc")
    for third_party in ("django", "tzdata", "typing_extensions", "cryptography", "kospmx"):
        assert not _may_reach("kospm.shared.clock", third_party)


def test_pure_modules_are_recognised_at_any_depth() -> None:
    assert _must_be_pure("kospm.properties.domain")
    assert _must_be_pure("kospm.housekeeping.domain.planning")
    assert _must_be_pure("kospm.shared.outbox.service_layer.worker")
    assert _must_be_pure("kospm.shared.clock")
    assert not _must_be_pure("kospm.shared.adapters.crypto")
    assert not _must_be_pure("kospm.properties.adapters.repository")
    assert not _must_be_pure("kospm.bootstrap")
