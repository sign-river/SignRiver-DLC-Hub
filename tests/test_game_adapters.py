from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from signriver_app.adapters.errors import (
    AdapterNotFoundError,
    DuplicateAdapterError,
    InvalidAdapterError,
)
from signriver_app.adapters.mock import MockGameAdapter
from signriver_app.adapters.protocol import GameAdapter
from signriver_app.adapters.registry import AdapterRegistry
from signriver_app.domain import (
    AdapterCapability,
    AdapterDescriptor,
    GameInstallation,
    GameState,
    InstallationCandidate,
    ValidationResult,
)


def make_descriptor(
    adapter_id: str = "alpha.mock",
    game_id: str = "alpha",
    *,
    display_name: str = "Alpha Game",
) -> AdapterDescriptor:
    return AdapterDescriptor(
        adapter_id=adapter_id,
        adapter_version="1.0.0",
        game_id=game_id,
        display_name=display_name,
        platforms=("windows",),
        stores=("mock",),
        capabilities={AdapterCapability.AUTO_DISCOVERY, AdapterCapability.REPAIR},
    )


def make_adapter(
    adapter_id: str = "alpha.mock",
    game_id: str = "alpha",
) -> MockGameAdapter:
    return MockGameAdapter(make_descriptor(adapter_id, game_id))


def make_installation(
    root: Path,
    *,
    game_id: str = "alpha",
    adapter_id: str = "alpha.mock",
) -> GameInstallation:
    return GameInstallation(
        installation_id="alpha.local",
        game_id=game_id,
        adapter_id=adapter_id,
        root=root,
        executable=None,
        platform="windows",
        source="manual",
    )


def test_mock_adapter_satisfies_runtime_protocol() -> None:
    adapter = make_adapter()

    assert isinstance(adapter, GameAdapter)
    assert not isinstance(object(), GameAdapter)
    with pytest.raises(AttributeError):
        adapter.descriptor = make_descriptor("other.mock", "other")  # type: ignore[misc]


def test_mock_discovery_is_an_isolated_snapshot(tmp_path: Path) -> None:
    candidate = InstallationCandidate(
        root=tmp_path / "Alpha",
        source="registry",
        store="mock",
    )
    source = [candidate]
    adapter = MockGameAdapter(make_descriptor(), candidates=source)
    source.clear()

    first = adapter.discover()
    second = adapter.discover()
    first.clear()

    assert first is not second
    assert second == [candidate]
    assert adapter.discover() == [candidate]


def test_mock_validates_discovered_and_manual_roots(tmp_path: Path) -> None:
    candidate_root = tmp_path / "games" / "Alpha"
    executable = candidate_root / "alpha.exe"
    candidate = InstallationCandidate(
        root=candidate_root,
        executable=executable,
        source="registry",
        store="mock",
        metadata={"build": "stable"},
    )
    manual_root = tmp_path / "manual" / "Alpha"
    adapter = MockGameAdapter(
        make_descriptor(),
        candidates=[candidate],
        valid_roots=[manual_root],
    )

    discovered = adapter.validate(candidate_root.parent / "." / "Alpha")
    manual = adapter.validate(manual_root / ".")
    missing = adapter.validate(tmp_path / "missing")

    assert discovered.valid is True
    assert discovered.normalized_root == candidate_root.resolve()
    assert discovered.executable == executable
    assert discovered.platform == "windows"
    assert discovered.source == "registry"
    assert discovered.store == "mock"
    assert discovered.metadata == {"build": "stable"}
    assert manual.valid is True
    assert manual.normalized_root == manual_root.resolve()
    assert manual.platform == "windows"
    assert manual.source == "manual"
    assert manual.store == "mock"
    assert missing.valid is False
    assert missing.normalized_root == (tmp_path / "missing").resolve()
    assert missing.errors


def test_mock_inspects_only_its_own_game_and_adapter(tmp_path: Path) -> None:
    state = GameState(
        game_version="2.4.1",
        healthy=False,
        installed_content=("sample-dlc",),
        warnings=("fixture warning",),
    )
    adapter = MockGameAdapter(make_descriptor(), state=state)
    installation = make_installation(tmp_path)

    assert adapter.inspect(installation) is state
    with pytest.raises(ValueError, match="game_id"):
        adapter.inspect(replace(installation, game_id="beta"))
    with pytest.raises(ValueError, match="adapter_id"):
        adapter.inspect(replace(installation, adapter_id="alpha.other"))


def test_registry_registers_and_looks_up_in_order() -> None:
    first = make_adapter("alpha.mock", "alpha")
    second = make_adapter("beta.mock", "beta")
    registry = AdapterRegistry()

    assert registry.register(first) is None
    registry.register(second)

    assert registry.get("alpha.mock") is first
    assert registry.all() == (first, second)
    assert tuple(registry) == (first, second)
    assert len(registry) == 2
    assert "alpha.mock" in registry
    assert first not in registry


def test_registry_filters_by_game_and_keeps_first_game_order() -> None:
    alpha_first = make_adapter("alpha.steam", "alpha")
    beta = make_adapter("beta.mock", "beta")
    alpha_second = make_adapter("alpha.gog", "alpha")
    registry = AdapterRegistry([alpha_first, beta, alpha_second])

    assert registry.for_game("alpha") == (alpha_first, alpha_second)
    assert registry.for_game("unknown") == ()
    assert registry.game_ids() == ("alpha", "beta")


def test_registry_rejects_existing_and_in_batch_duplicates() -> None:
    existing = make_adapter("alpha.mock", "alpha")
    registry = AdapterRegistry([existing])

    with pytest.raises(DuplicateAdapterError) as existing_error:
        registry.register(make_adapter("alpha.mock", "other-game"))
    assert existing_error.value.adapter_id == "alpha.mock"
    assert registry.all() == (existing,)

    first = make_adapter("beta.mock", "beta")
    duplicate = make_adapter("beta.mock", "beta")
    with pytest.raises(DuplicateAdapterError):
        registry.register_many([first, duplicate])
    assert registry.all() == (existing,)


def test_registry_reports_unknown_adapter_and_unregisters() -> None:
    adapter = make_adapter()
    registry = AdapterRegistry([adapter])

    assert registry.unregister("alpha.mock") is adapter
    assert registry.all() == ()
    with pytest.raises(AdapterNotFoundError) as get_error:
        registry.get("missing")
    assert get_error.value.adapter_id == "missing"
    with pytest.raises(AdapterNotFoundError):
        registry.unregister("missing")


def test_registry_rejects_invalid_adapter_objects() -> None:
    registry = AdapterRegistry()

    with pytest.raises(InvalidAdapterError, match="invalid adapter"):
        registry.register(object())  # type: ignore[arg-type]

    class IncompleteAdapter:
        descriptor = make_descriptor()

        def discover(self):
            return []

        def validate(self, root):
            return ValidationResult.failure("not implemented", normalized_root=root)

        inspect = None

    with pytest.raises(InvalidAdapterError, match="inspect must be callable"):
        registry.register(IncompleteAdapter())  # type: ignore[arg-type]
    assert registry.all() == ()


def test_registry_detects_descriptor_mutation_after_registration() -> None:
    class MutableAdapter:
        def __init__(self) -> None:
            self.descriptor = make_descriptor()

        def discover(self):
            return []

        def validate(self, root):
            return ValidationResult.failure("not implemented", normalized_root=root)

        def inspect(self, installation):
            return GameState()

    adapter = MutableAdapter()
    registry = AdapterRegistry([adapter])
    adapter.descriptor = make_descriptor("beta.mock", "beta")

    with pytest.raises(InvalidAdapterError, match="descriptor changed"):
        registry.get("alpha.mock")
    assert registry.unregister("alpha.mock") is adapter


def test_registry_batch_registration_is_atomic() -> None:
    existing = make_adapter("alpha.mock", "alpha")
    valid = make_adapter("beta.mock", "beta")
    registry = AdapterRegistry([existing])

    with pytest.raises(InvalidAdapterError):
        registry.register_many([valid, object()])  # type: ignore[list-item]
    assert registry.all() == (existing,)

    def broken_batch():
        yield valid
        raise RuntimeError("fixture iteration failed")

    with pytest.raises(RuntimeError, match="fixture iteration failed"):
        registry.register_many(broken_batch())
    assert registry.all() == (existing,)


def test_descriptor_normalizes_capabilities_and_is_immutable() -> None:
    descriptor = AdapterDescriptor(
        adapter_id="alpha.mock",
        adapter_version="1.0.0",
        game_id="alpha",
        display_name="Alpha Game",
        capabilities={"repair", AdapterCapability.AUTO_DISCOVERY},
    )

    assert descriptor.capabilities == frozenset(
        {AdapterCapability.REPAIR, AdapterCapability.AUTO_DISCOVERY}
    )
    with pytest.raises(FrozenInstanceError):
        descriptor.game_id = "beta"  # type: ignore[misc]
    with pytest.raises(ValueError, match="stable lowercase identifier"):
        replace(descriptor, adapter_id="Not Stable")


def test_domain_metadata_is_copied_and_recursively_read_only(tmp_path: Path) -> None:
    metadata = {"tags": ["original"], "nested": {"channel": "stable"}}
    candidate = InstallationCandidate(
        root=tmp_path,
        source="manual",
        metadata=metadata,
    )
    metadata["tags"].append("changed")
    metadata["nested"]["channel"] = "preview"

    assert candidate.metadata["tags"] == ("original",)
    assert candidate.metadata["nested"]["channel"] == "stable"
    with pytest.raises(TypeError):
        candidate.metadata["new"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        candidate.metadata["nested"]["channel"] = "changed"  # type: ignore[index]

    with pytest.raises(TypeError, match="metadata key must be a string"):
        InstallationCandidate(
            root=tmp_path,
            source="manual",
            metadata={1: "invalid"},  # type: ignore[dict-item]
        )


def test_validation_result_enforces_success_and_failure_invariants(
    tmp_path: Path,
) -> None:
    assert ValidationResult.success(tmp_path).valid is True
    assert ValidationResult.failure("missing executable").valid is False

    with pytest.raises(ValueError, match="requires normalized_root"):
        ValidationResult(valid=True)
    with pytest.raises(ValueError, match="cannot contain errors"):
        ValidationResult(valid=True, normalized_root=tmp_path, errors=("bad",))
    with pytest.raises(ValueError, match="requires at least one error"):
        ValidationResult(valid=False)


def test_validation_result_creates_complete_installation(tmp_path: Path) -> None:
    root = tmp_path / "Alpha"
    result = ValidationResult.success(
        root,
        executable=Path("bin") / "alpha.exe",
        platform="windows",
        source="registry",
        store="mock",
        metadata={"build": "stable"},
    )

    installation = result.to_installation(
        installation_id="alpha.local",
        game_id="alpha",
        adapter_id="alpha.mock",
    )

    assert installation.root == root.resolve()
    assert installation.executable == (root / "bin" / "alpha.exe").resolve()
    assert installation.platform == "windows"
    assert installation.source == "registry"
    assert installation.store == "mock"
    assert installation.metadata == {"build": "stable"}

    with pytest.raises(ValueError, match="inside the game root"):
        ValidationResult.success(root, executable=tmp_path / "outside.exe")
    with pytest.raises(ValueError, match="failed validation"):
        ValidationResult.failure("invalid").to_installation(
            installation_id="alpha.local",
            game_id="alpha",
            adapter_id="alpha.mock",
        )


def test_installation_requires_aware_time_and_normalizes_it_to_utc(
    tmp_path: Path,
) -> None:
    local_zone = timezone(timedelta(hours=8))
    seen = datetime(2026, 7, 11, 12, 30, tzinfo=local_zone)
    installation = replace(make_installation(tmp_path), last_seen=seen)

    assert installation.last_seen == datetime(
        2026, 7, 11, 4, 30, tzinfo=timezone.utc
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(installation, last_seen=datetime(2026, 7, 11, 12, 30))
