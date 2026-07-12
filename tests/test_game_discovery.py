from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from signriver_app.adapters import AdapterRegistry, MockGameAdapter
from signriver_app.application import (
    DiscoveryStage,
    GameDiscoveryService,
    GamePathValidationError,
    InstallationAvailability,
    InstallationOrigin,
    InvalidAdapterResultError,
)
from signriver_app.domain import (
    AdapterCapability,
    AdapterDescriptor,
    GameInstallation,
    GameState,
    InstallationCandidate,
    ValidationResult,
)
from signriver_app.infrastructure.persistence import (
    Database,
    GameInstallationRepository,
    InstallationNotFoundError,
)


NOW = datetime(2026, 7, 12, 1, 30, tzinfo=timezone.utc)


def descriptor(
    adapter_id: str = "alpha.mock",
    game_id: str = "alpha",
    *,
    auto_discovery: bool = True,
) -> AdapterDescriptor:
    capabilities = (
        frozenset({AdapterCapability.AUTO_DISCOVERY})
        if auto_discovery
        else frozenset()
    )
    return AdapterDescriptor(
        adapter_id=adapter_id,
        adapter_version="1.0.0",
        game_id=game_id,
        display_name=f"{game_id.title()} Game",
        platforms=("windows",),
        stores=("mock",),
        capabilities=capabilities,
    )


def repository(tmp_path: Path) -> GameInstallationRepository:
    return GameInstallationRepository(Database(tmp_path / "hub.sqlite3"))


def service(
    repo: GameInstallationRepository,
    *adapters,
) -> GameDiscoveryService:
    return GameDiscoveryService(
        AdapterRegistry(adapters),
        repo,
        clock=lambda: NOW,
    )


def saved_installation(
    root: Path,
    *,
    installation_id: str = "alpha.saved",
    game_id: str = "alpha",
    adapter_id: str = "alpha.mock",
    selected: bool = True,
    last_seen: datetime | None = None,
) -> GameInstallation:
    return GameInstallation(
        installation_id=installation_id,
        game_id=game_id,
        adapter_id=adapter_id,
        root=root,
        executable=root / "alpha.exe",
        platform="windows",
        source="manual",
        store="mock",
        selected=selected,
        last_seen=last_seen,
        metadata={"saved": True},
    )


def test_scan_discovers_deduplicates_and_persists_stable_installation(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    root = tmp_path / "games" / "Alpha"
    candidate = InstallationCandidate(
        root=root,
        executable=root / "alpha.exe",
        source="registry",
        store="mock",
        metadata={"build": "stable"},
    )
    duplicate = replace(candidate, root=root / ".")
    adapter = MockGameAdapter(descriptor(), candidates=(candidate, duplicate))
    discovery = service(repo, adapter)

    first = discovery.scan()
    second = discovery.scan()

    assert len(first.installations) == 1
    status = first.installations[0]
    assert status.availability is InstallationAvailability.AVAILABLE
    assert status.origin is InstallationOrigin.DISCOVERED
    assert status.installation.source == "registry"
    assert status.installation.last_seen == NOW
    assert status.installation.metadata["build"] == "stable"
    assert first.issues == ()
    assert repo.get(status.installation.installation_id) == status.installation
    assert second.installations[0].installation.installation_id == (
        status.installation.installation_id
    )


def test_scan_isolates_adapter_discovery_failures(tmp_path: Path) -> None:
    class FailingAdapter:
        descriptor = descriptor("broken.mock", "broken")

        def discover(self):
            raise OSError("fixture discovery failure")

        def validate(self, root):
            return ValidationResult.failure("not used", normalized_root=root)

        def inspect(self, installation):
            return GameState()

    repo = repository(tmp_path)
    valid_root = tmp_path / "Alpha"
    valid = MockGameAdapter(
        descriptor(),
        candidates=(
            InstallationCandidate(
                root=valid_root,
                source="registry",
                store="mock",
            ),
        ),
    )

    report = service(repo, FailingAdapter(), valid).scan()

    assert len(report.available) == 1
    assert len(report.issues) == 1
    assert report.issues[0].adapter_id == "broken.mock"
    assert report.issues[0].stage is DiscoveryStage.DISCOVER
    assert "fixture discovery failure" in report.issues[0].message


def test_scan_reports_invalid_candidates_without_persisting_them(
    tmp_path: Path,
) -> None:
    class RejectingAdapter:
        descriptor = descriptor()

        def discover(self):
            return [
                InstallationCandidate(
                    root=tmp_path / "invalid",
                    source="registry",
                    store="mock",
                ),
                object(),
            ]

        def validate(self, root):
            return ValidationResult.failure("missing game executable")

        def inspect(self, installation):
            return GameState()

    repo = repository(tmp_path)

    report = service(repo, RejectingAdapter()).scan()

    assert report.installations == ()
    assert repo.list() == ()
    assert {issue.stage for issue in report.issues} == {
        DiscoveryStage.DISCOVER,
        DiscoveryStage.VALIDATE,
    }
    assert any("missing game executable" in issue.message for issue in report.issues)


def test_scan_revalidates_saved_paths_not_returned_by_discovery(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    root = tmp_path / "manual" / "Alpha"
    saved = saved_installation(
        root,
        last_seen=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    repo.save(saved)
    adapter = MockGameAdapter(
        descriptor(auto_discovery=False),
        valid_roots=(root,),
    )

    report = service(repo, adapter).scan()

    assert len(report.installations) == 1
    status = report.installations[0]
    assert status.availability is InstallationAvailability.AVAILABLE
    assert status.origin is InstallationOrigin.SAVED
    assert status.installation.installation_id == saved.installation_id
    assert status.installation.selected is True
    assert status.installation.source == "manual"
    assert status.installation.last_seen == NOW
    assert status.installation.metadata["saved"] is True
    assert repo.get(saved.installation_id) == status.installation


def test_scan_keeps_invalid_or_unhandled_saved_paths(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    invalid = saved_installation(tmp_path / "missing")
    missing_adapter = saved_installation(
        tmp_path / "orphaned",
        installation_id="orphan.saved",
        game_id="orphan",
        adapter_id="orphan.mock",
        selected=False,
    )
    repo.save_many((invalid, missing_adapter))
    adapter = MockGameAdapter(descriptor(auto_discovery=False))

    report = service(repo, adapter).scan()

    assert len(report.installations) == 2
    assert all(
        status.availability is InstallationAvailability.UNAVAILABLE
        for status in report.installations
    )
    assert repo.get(invalid.installation_id) == invalid
    assert repo.get(missing_adapter.installation_id) == missing_adapter
    assert any("not registered" in issue.message for issue in report.issues)
    assert any("not a valid" in issue.message for issue in report.issues)


def test_manual_paths_are_stable_selectable_and_forgettable(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    first_root = tmp_path / "first" / "Alpha"
    second_root = tmp_path / "second" / "Alpha"
    adapter = MockGameAdapter(
        descriptor(auto_discovery=False),
        valid_roots=(first_root, second_root),
    )
    discovery = service(repo, adapter)

    first = discovery.add_manual("alpha.mock", first_root)
    repeated = discovery.add_manual("alpha.mock", first_root / ".")
    second = discovery.add_manual("alpha.mock", second_root)

    assert repeated.installation_id == first.installation_id
    assert repeated.source == "manual"
    assert second.installation_id != first.installation_id
    assert repo.get_selected("alpha") == second
    assert repo.get(first.installation_id) == replace(first, selected=False)

    selected = discovery.select(first.installation_id)
    assert selected.selected is True
    assert selected.last_seen == NOW
    assert repo.get_selected("alpha") == selected
    assert discovery.forget(second.installation_id) is True
    assert discovery.forget(second.installation_id) is False


def test_manual_invalid_path_does_not_change_persistence(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    adapter = MockGameAdapter(descriptor(auto_discovery=False))
    discovery = service(repo, adapter)

    with pytest.raises(GamePathValidationError) as error:
        discovery.add_manual("alpha.mock", tmp_path / "missing")

    assert error.value.adapter_id == "alpha.mock"
    assert error.value.errors
    assert repo.list() == ()


def test_select_revalidates_saved_path_and_reports_missing_records(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    installation = saved_installation(tmp_path / "missing")
    repo.save(installation)
    discovery = service(
        repo,
        MockGameAdapter(descriptor(auto_discovery=False)),
    )

    with pytest.raises(GamePathValidationError):
        discovery.select(installation.installation_id)
    with pytest.raises(InstallationNotFoundError):
        discovery.select("unknown.installation")

    assert repo.get(installation.installation_id) == installation


def test_adapter_result_must_match_declared_platform_and_store(
    tmp_path: Path,
) -> None:
    class IncompatibleAdapter:
        descriptor = descriptor()

        def discover(self):
            return [
                InstallationCandidate(
                    root=tmp_path / "Alpha",
                    source="registry",
                    store="mock",
                )
            ]

        def validate(self, root):
            return ValidationResult.success(
                root,
                platform="linux",
                source="registry",
                store="other",
            )

        def inspect(self, installation):
            return GameState()

    repo = repository(tmp_path)
    discovery = service(repo, IncompatibleAdapter())

    report = discovery.scan()
    assert report.installations == ()
    assert len(report.issues) == 1
    assert "unsupported platform" in report.issues[0].message

    with pytest.raises(InvalidAdapterResultError, match="unsupported platform"):
        discovery.add_manual("alpha.mock", tmp_path / "Alpha")


def test_saved_game_identity_mismatch_is_reported_not_rewritten(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    corrupted = saved_installation(
        tmp_path / "Alpha",
        game_id="wrong-game",
    )
    repo.save(corrupted)
    adapter = MockGameAdapter(
        descriptor(auto_discovery=False),
        valid_roots=(corrupted.root,),
    )

    report = service(repo, adapter).scan()

    assert report.installations[0].availability is InstallationAvailability.UNAVAILABLE
    assert "does not match" in report.installations[0].validation_errors[0]
    assert repo.get(corrupted.installation_id) == corrupted

