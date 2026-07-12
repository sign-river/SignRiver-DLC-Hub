"""Game installation discovery and user-selected path use cases."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from ..adapters import AdapterRegistry, GameAdapter
from ..domain import (
    AdapterCapability,
    GameInstallation,
    InstallationCandidate,
    ValidationResult,
)
from ..infrastructure.persistence import (
    GameInstallationRepository,
    InstallationNotFoundError,
)


class InstallationAvailability(StrEnum):
    """Current usability of a saved or newly discovered installation."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class InstallationOrigin(StrEnum):
    """How an installation entered the current scan report."""

    DISCOVERED = "discovered"
    SAVED = "saved"


class DiscoveryStage(StrEnum):
    """Stage that produced a non-fatal discovery issue."""

    DISCOVER = "discover"
    VALIDATE = "validate"


@dataclass(frozen=True, slots=True)
class DiscoveryIssue:
    adapter_id: str
    stage: DiscoveryStage
    message: str
    root: Path | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.adapter_id, str) or not self.adapter_id:
            raise ValueError("adapter_id must be a non-empty string")
        if not isinstance(self.stage, DiscoveryStage):
            object.__setattr__(self, "stage", DiscoveryStage(self.stage))
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message must be a non-empty string")
        if self.root is not None:
            object.__setattr__(
                self,
                "root",
                Path(self.root).expanduser(),
            )


@dataclass(frozen=True, slots=True)
class InstallationStatus:
    installation: GameInstallation
    availability: InstallationAvailability
    origin: InstallationOrigin
    validation_errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.installation, GameInstallation):
            raise TypeError("installation must be a GameInstallation")
        if not isinstance(self.availability, InstallationAvailability):
            object.__setattr__(
                self,
                "availability",
                InstallationAvailability(self.availability),
            )
        if not isinstance(self.origin, InstallationOrigin):
            object.__setattr__(self, "origin", InstallationOrigin(self.origin))
        errors = tuple(self.validation_errors)
        if not all(isinstance(error, str) and error for error in errors):
            raise ValueError("validation_errors must contain non-empty strings")
        if self.availability is InstallationAvailability.AVAILABLE and errors:
            raise ValueError("an available installation cannot contain validation errors")
        object.__setattr__(self, "validation_errors", errors)


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    installations: tuple[InstallationStatus, ...] = ()
    issues: tuple[DiscoveryIssue, ...] = ()

    def __post_init__(self) -> None:
        installations = tuple(self.installations)
        issues = tuple(self.issues)
        if not all(isinstance(item, InstallationStatus) for item in installations):
            raise TypeError("installations must contain InstallationStatus values")
        if not all(isinstance(item, DiscoveryIssue) for item in issues):
            raise TypeError("issues must contain DiscoveryIssue values")
        object.__setattr__(self, "installations", installations)
        object.__setattr__(self, "issues", issues)

    @property
    def available(self) -> tuple[GameInstallation, ...]:
        return tuple(
            status.installation
            for status in self.installations
            if status.availability is InstallationAvailability.AVAILABLE
        )


class GameDiscoveryError(Exception):
    """Base class for failures that prevent a requested discovery use case."""


class InvalidAdapterResultError(GameDiscoveryError):
    """Raised when an adapter violates the discovery result contract."""


class GamePathValidationError(GameDiscoveryError):
    """Raised when a user-selected game path fails adapter validation."""

    def __init__(
        self,
        adapter_id: str,
        root: Path,
        errors: Iterable[str],
    ) -> None:
        self.adapter_id = adapter_id
        self.root = Path(root).expanduser()
        self.errors = tuple(errors)
        message = "; ".join(self.errors) or "game path validation failed"
        super().__init__(message)


@dataclass(slots=True)
class GameDiscoveryService:
    """Coordinate adapters and persistence without performing UI work."""

    registry: AdapterRegistry
    repository: GameInstallationRepository
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(timezone.utc),
        repr=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.registry, AdapterRegistry):
            raise TypeError("registry must be an AdapterRegistry")
        if not isinstance(self.repository, GameInstallationRepository):
            raise TypeError("repository must be a GameInstallationRepository")
        if not callable(self.clock):
            raise TypeError("clock must be callable")

    def scan(self) -> DiscoveryReport:
        """Discover installations and revalidate saved paths.

        Adapter failures are isolated into ``DiscoveryIssue`` values.  Valid
        installations are saved atomically; invalid historical records remain
        persisted and are returned as unavailable instead of being deleted.
        """

        now = self._now()
        saved = self.repository.list()
        saved_by_key: dict[tuple[str, str, str], list[GameInstallation]] = {}
        for installation in saved:
            key = _installation_key(
                installation.adapter_id,
                installation.root,
                installation.platform,
            )
            saved_by_key.setdefault(key, []).append(installation)

        statuses: dict[str, InstallationStatus] = {}
        issues: list[DiscoveryIssue] = []
        matched_saved_ids: set[str] = set()
        seen_discovered_keys: set[tuple[str, str]] = set()

        adapters = self.registry.all()
        adapters_by_id = {adapter.descriptor.adapter_id: adapter for adapter in adapters}
        for adapter in adapters:
            if AdapterCapability.AUTO_DISCOVERY not in adapter.descriptor.capabilities:
                continue
            candidates = self._discover_candidates(adapter, issues)
            for candidate in candidates:
                status = self._validate_candidate(
                    adapter,
                    candidate,
                    now,
                    saved_by_key,
                    matched_saved_ids,
                    seen_discovered_keys,
                    issues,
                )
                if status is not None:
                    statuses[status.installation.installation_id] = status

        for installation in saved:
            if installation.installation_id in matched_saved_ids:
                continue
            status = self._revalidate_saved(
                installation,
                adapters_by_id.get(installation.adapter_id),
                now,
                issues,
            )
            statuses[installation.installation_id] = status

        _auto_select_single_installations(statuses)
        ordered = tuple(
            sorted(
                statuses.values(),
                key=lambda item: (
                    item.installation.game_id,
                    not item.installation.selected,
                    item.installation.installation_id,
                ),
            )
        )
        available = tuple(
            status.installation
            for status in ordered
            if status.availability is InstallationAvailability.AVAILABLE
        )
        if available:
            self.repository.save_many(available)
        return DiscoveryReport(ordered, tuple(issues))

    def add_manual(
        self,
        adapter_id: str,
        root: Path,
        *,
        select: bool = True,
    ) -> GameInstallation:
        """Validate and persist a user-selected game directory."""

        if not isinstance(select, bool):
            raise TypeError("select must be a bool")
        adapter = self.registry.get(adapter_id)
        normalized_input = _normalize_input_path(root)
        result = self._call_validate(adapter, normalized_input)
        if not result.valid:
            raise GamePathValidationError(adapter_id, normalized_input, result.errors)
        self._check_result_compatibility(adapter, result)
        assert result.normalized_root is not None
        assert result.platform is not None

        existing = self._find_saved_by_path(
            adapter_id,
            result.normalized_root,
            result.platform,
        )
        installation_id = (
            existing.installation_id
            if existing is not None
            else _installation_id(adapter_id, result.normalized_root, result.platform)
        )
        metadata = _merged_metadata(existing, result)
        installation = result.to_installation(
            installation_id=installation_id,
            game_id=adapter.descriptor.game_id,
            adapter_id=adapter_id,
            selected=select or bool(existing and existing.selected),
            last_seen=self._now(),
        )
        installation = replace(
            installation,
            source="manual",
            metadata=metadata,
        )
        return self.repository.save(installation)

    def select(self, installation_id: str) -> GameInstallation:
        """Revalidate and select a saved installation."""

        installation = self.repository.get(installation_id)
        if installation is None:
            raise InstallationNotFoundError(
                f"installation {installation_id!r} is not persisted"
            )
        adapter = self.registry.get(installation.adapter_id)
        if adapter.descriptor.game_id != installation.game_id:
            raise InvalidAdapterResultError(
                "saved installation game_id does not match its adapter"
            )
        result = self._call_validate(adapter, installation.root)
        if not result.valid:
            raise GamePathValidationError(
                installation.adapter_id,
                installation.root,
                result.errors,
            )
        self._check_result_compatibility(adapter, result)
        refreshed = result.to_installation(
            installation_id=installation.installation_id,
            game_id=installation.game_id,
            adapter_id=installation.adapter_id,
            selected=True,
            last_seen=self._now(),
        )
        refreshed = replace(
            refreshed,
            source=installation.source,
            metadata=_merged_metadata(installation, result),
        )
        return self.repository.save(refreshed)

    def forget(self, installation_id: str) -> bool:
        """Forget a saved installation without touching the game directory."""

        return self.repository.delete(installation_id)

    def _discover_candidates(
        self,
        adapter: GameAdapter,
        issues: list[DiscoveryIssue],
    ) -> tuple[InstallationCandidate, ...]:
        try:
            discovered = tuple(adapter.discover())
        except Exception as exc:
            issues.append(
                DiscoveryIssue(
                    adapter.descriptor.adapter_id,
                    DiscoveryStage.DISCOVER,
                    f"adapter discovery failed: {exc}",
                )
            )
            return ()

        valid: list[InstallationCandidate] = []
        for candidate in discovered:
            if isinstance(candidate, InstallationCandidate):
                valid.append(candidate)
                continue
            issues.append(
                DiscoveryIssue(
                    adapter.descriptor.adapter_id,
                    DiscoveryStage.DISCOVER,
                    "adapter returned a non-InstallationCandidate value",
                )
            )
        return tuple(valid)

    def _validate_candidate(
        self,
        adapter: GameAdapter,
        candidate: InstallationCandidate,
        now: datetime,
        saved_by_key: dict[tuple[str, str, str], list[GameInstallation]],
        matched_saved_ids: set[str],
        seen_discovered_keys: set[tuple[str, str, str]],
        issues: list[DiscoveryIssue],
    ) -> InstallationStatus | None:
        try:
            result = self._call_validate(adapter, candidate.root)
            self._check_result_compatibility(adapter, result)
        except Exception as exc:
            issues.append(
                DiscoveryIssue(
                    adapter.descriptor.adapter_id,
                    DiscoveryStage.VALIDATE,
                    f"candidate validation failed: {exc}",
                    candidate.root,
                )
            )
            return None
        if not result.valid:
            issues.append(
                DiscoveryIssue(
                    adapter.descriptor.adapter_id,
                    DiscoveryStage.VALIDATE,
                    "; ".join(result.errors),
                    candidate.root,
                )
            )
            return None

        assert result.normalized_root is not None
        assert result.platform is not None
        key = _installation_key(
            adapter.descriptor.adapter_id,
            result.normalized_root,
            result.platform,
        )
        if key in seen_discovered_keys:
            return None
        seen_discovered_keys.add(key)

        saved_matches = [
            item
            for item in saved_by_key.get(key, [])
            if item.game_id == adapter.descriptor.game_id
        ]
        existing = next(
            (item for item in saved_matches if item.selected),
            saved_matches[0] if saved_matches else None,
        )
        if existing is not None:
            matched_saved_ids.add(existing.installation_id)
        installation = result.to_installation(
            installation_id=(
                existing.installation_id
                if existing is not None
                else _installation_id(
                    adapter.descriptor.adapter_id,
                    result.normalized_root,
                    result.platform,
                )
            ),
            game_id=adapter.descriptor.game_id,
            adapter_id=adapter.descriptor.adapter_id,
            selected=bool(existing and existing.selected),
            last_seen=now,
        )
        installation = replace(
            installation,
            source=(existing.source if existing is not None else installation.source),
            metadata=_merged_metadata(existing, result, candidate.metadata),
        )
        return InstallationStatus(
            installation,
            InstallationAvailability.AVAILABLE,
            InstallationOrigin.DISCOVERED,
        )

    def _revalidate_saved(
        self,
        installation: GameInstallation,
        adapter: GameAdapter | None,
        now: datetime,
        issues: list[DiscoveryIssue],
    ) -> InstallationStatus:
        if adapter is None:
            message = "saved installation adapter is not registered"
            issues.append(
                DiscoveryIssue(
                    installation.adapter_id,
                    DiscoveryStage.VALIDATE,
                    message,
                    installation.root,
                )
            )
            return InstallationStatus(
                installation,
                InstallationAvailability.UNAVAILABLE,
                InstallationOrigin.SAVED,
                (message,),
            )
        if installation.game_id != adapter.descriptor.game_id:
            message = "saved installation game_id does not match its adapter"
            issues.append(
                DiscoveryIssue(
                    installation.adapter_id,
                    DiscoveryStage.VALIDATE,
                    message,
                    installation.root,
                )
            )
            return InstallationStatus(
                installation,
                InstallationAvailability.UNAVAILABLE,
                InstallationOrigin.SAVED,
                (message,),
            )

        try:
            result = self._call_validate(adapter, installation.root)
            self._check_result_compatibility(adapter, result)
        except Exception as exc:
            message = f"saved path validation failed: {exc}"
            issues.append(
                DiscoveryIssue(
                    installation.adapter_id,
                    DiscoveryStage.VALIDATE,
                    message,
                    installation.root,
                )
            )
            return InstallationStatus(
                installation,
                InstallationAvailability.UNAVAILABLE,
                InstallationOrigin.SAVED,
                (message,),
            )
        if not result.valid:
            issues.append(
                DiscoveryIssue(
                    installation.adapter_id,
                    DiscoveryStage.VALIDATE,
                    "; ".join(result.errors),
                    installation.root,
                )
            )
            return InstallationStatus(
                installation,
                InstallationAvailability.UNAVAILABLE,
                InstallationOrigin.SAVED,
                result.errors,
            )

        refreshed = result.to_installation(
            installation_id=installation.installation_id,
            game_id=installation.game_id,
            adapter_id=installation.adapter_id,
            selected=installation.selected,
            last_seen=now,
        )
        refreshed = replace(
            refreshed,
            source=installation.source,
            metadata=_merged_metadata(installation, result),
        )
        return InstallationStatus(
            refreshed,
            InstallationAvailability.AVAILABLE,
            InstallationOrigin.SAVED,
        )

    def _call_validate(self, adapter: GameAdapter, root: Path) -> ValidationResult:
        try:
            result = adapter.validate(root)
        except Exception as exc:
            raise GameDiscoveryError(f"adapter validation raised an error: {exc}") from exc
        if not isinstance(result, ValidationResult):
            raise InvalidAdapterResultError(
                "adapter.validate() must return a ValidationResult"
            )
        return result

    @staticmethod
    def _check_result_compatibility(
        adapter: GameAdapter,
        result: ValidationResult,
    ) -> None:
        if not result.valid:
            return
        descriptor = adapter.descriptor
        if result.platform not in descriptor.platforms:
            raise InvalidAdapterResultError(
                f"adapter returned unsupported platform {result.platform!r}"
            )
        if (
            result.store is not None
            and descriptor.stores
            and result.store not in descriptor.stores
        ):
            raise InvalidAdapterResultError(
                f"adapter returned unsupported store {result.store!r}"
            )

    def _find_saved_by_path(
        self,
        adapter_id: str,
        root: Path,
        platform: str,
    ) -> GameInstallation | None:
        key = _installation_key(adapter_id, root, platform)
        return next(
            (
                installation
                for installation in self.repository.list(adapter_id=adapter_id)
                if _installation_key(
                    installation.adapter_id,
                    installation.root,
                    installation.platform,
                )
                == key
            ),
            None,
        )

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime):
            raise TypeError("clock must return a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)


def _installation_key(
    adapter_id: str,
    root: Path,
    platform: str,
) -> tuple[str, str, str]:
    normalized = os.path.normpath(str(_normalize_input_path(root)))
    if platform == "windows":
        normalized = normalized.casefold()
    return adapter_id, platform, normalized


def _installation_id(adapter_id: str, root: Path, platform: str) -> str:
    key = _installation_key(adapter_id, root, platform)[2]
    digest = hashlib.sha256(f"{platform}\0{key}".encode("utf-8")).hexdigest()
    return f"{adapter_id}.{digest}"


def _normalize_input_path(root: Path) -> Path:
    try:
        return Path(root).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise GameDiscoveryError(f"could not normalize game path {root!r}") from exc


def _merged_metadata(
    existing: GameInstallation | None,
    result: ValidationResult,
    additional: Mapping[str, object] | None = None,
) -> dict[str, object]:
    merged: dict[str, object] = {}
    if existing is not None:
        merged.update(existing.metadata)
    if additional is not None:
        merged.update(additional)
    merged.update(result.metadata)
    return merged


def _auto_select_single_installations(
    statuses: dict[str, InstallationStatus],
) -> None:
    by_game: dict[str, list[InstallationStatus]] = {}
    for status in statuses.values():
        by_game.setdefault(status.installation.game_id, []).append(status)
    for game_statuses in by_game.values():
        if any(status.installation.selected for status in game_statuses):
            continue
        available = [
            status
            for status in game_statuses
            if status.availability is InstallationAvailability.AVAILABLE
        ]
        if len(available) != 1:
            continue
        current = available[0]
        statuses[current.installation.installation_id] = replace(
            current,
            installation=replace(current.installation, selected=True),
        )


__all__ = [
    "DiscoveryIssue",
    "DiscoveryReport",
    "DiscoveryStage",
    "GameDiscoveryError",
    "GameDiscoveryService",
    "GamePathValidationError",
    "InstallationAvailability",
    "InstallationOrigin",
    "InstallationStatus",
    "InvalidAdapterResultError",
]
