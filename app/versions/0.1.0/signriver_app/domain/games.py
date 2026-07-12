"""Domain models shared by game adapters and application services.

The objects in this module deliberately contain no discovery or filesystem
behaviour.  They form the immutable boundary between an adapter and the rest
of the application.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from os import PathLike
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping, TypeAlias


PathInput: TypeAlias = str | PathLike[str]
Metadata: TypeAlias = Mapping[str, Any]

_STABLE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


class AdapterCapability(StrEnum):
    """Optional operations exposed by a game adapter."""

    AUTO_DISCOVERY = "auto_discovery"
    INSTALL = "install"
    UPDATE = "update"
    UNINSTALL = "uninstall"
    REPAIR = "repair"
    ENABLE = "enable"
    LAUNCH = "launch"


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty and trimmed")
    return value


def _require_stable_id(value: object, field_name: str) -> str:
    text = _require_text(value, field_name)
    if _STABLE_ID_PATTERN.fullmatch(text) is None:
        raise ValueError(
            f"{field_name} must be a stable lowercase identifier containing only "
            "letters, digits, '.', '_' or '-'"
        )
    return text


def _optional_text(value: object | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name)


def _optional_stable_id(value: object | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_stable_id(value, field_name)


def _as_path(value: PathInput, field_name: str) -> Path:
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"{field_name} must be a non-empty path")
    try:
        return Path(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field_name} must be path-like") from exc


def _optional_path(value: PathInput | None, field_name: str) -> Path | None:
    if value is None:
        return None
    return _as_path(value, field_name)


def _normalized_root(value: PathInput, field_name: str = "root") -> Path:
    return _as_path(value, field_name).expanduser().resolve(strict=False)


def _normalized_executable(
    root: Path | None,
    value: PathInput | None,
    field_name: str = "executable",
) -> Path | None:
    executable = _optional_path(value, field_name)
    if executable is None:
        return None
    if not executable.is_absolute():
        if root is None:
            raise ValueError(f"a relative {field_name} requires a root path")
        executable = root / executable
    executable = executable.expanduser().resolve(strict=False)
    if root is not None:
        try:
            executable.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be located inside the game root") from exc
    return executable


def _text_tuple(
    values: Iterable[str],
    field_name: str,
    *,
    stable_ids: bool = False,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be an iterable of strings, not a string")
    try:
        copied = tuple(values)
    except TypeError as exc:
        raise TypeError(f"{field_name} must be an iterable of strings") from exc
    if not allow_empty and not copied:
        raise ValueError(f"{field_name} must contain at least one value")
    validator = _require_stable_id if stable_ids else _require_text
    return tuple(validator(item, f"{field_name} item") for item in copied)


def _freeze_metadata_value(value: Any) -> Any:
    """Copy and recursively freeze common mutable metadata containers."""

    if isinstance(value, Mapping):
        return _freeze_metadata_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_metadata_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_metadata_value(item) for item in value)
    return deepcopy(value)


def _freeze_metadata_mapping(value: Mapping[object, Any]) -> Metadata:
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        text_key = _require_text(key, "metadata key")
        frozen[text_key] = _freeze_metadata_value(item)
    return MappingProxyType(frozen)


def _readonly_metadata(value: Metadata | None) -> Metadata:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    return _freeze_metadata_mapping(value)


@dataclass(frozen=True, slots=True)
class AdapterDescriptor:
    """Stable identity and advertised capabilities of one adapter."""

    adapter_id: str
    adapter_version: str
    game_id: str
    display_name: str
    platforms: tuple[str, ...] = ("windows",)
    stores: tuple[str, ...] = ()
    capabilities: frozenset[AdapterCapability] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "adapter_id", _require_stable_id(self.adapter_id, "adapter_id")
        )
        object.__setattr__(
            self, "adapter_version", _require_text(self.adapter_version, "adapter_version")
        )
        object.__setattr__(self, "game_id", _require_stable_id(self.game_id, "game_id"))
        object.__setattr__(self, "display_name", _require_text(self.display_name, "display_name"))
        object.__setattr__(
            self,
            "platforms",
            _text_tuple(self.platforms, "platforms", stable_ids=True, allow_empty=False),
        )
        object.__setattr__(
            self, "stores", _text_tuple(self.stores, "stores", stable_ids=True)
        )
        if isinstance(self.capabilities, (str, bytes)):
            raise TypeError("capabilities must be an iterable of AdapterCapability values")
        try:
            capabilities = frozenset(
                capability
                if isinstance(capability, AdapterCapability)
                else AdapterCapability(capability)
                for capability in self.capabilities
            )
        except TypeError as exc:
            raise TypeError("capabilities must be an iterable of AdapterCapability values") from exc
        object.__setattr__(self, "capabilities", capabilities)


@dataclass(frozen=True, slots=True)
class InstallationCandidate:
    """A possible installation returned by automatic discovery."""

    root: Path
    source: str
    platform: str = "windows"
    store: str | None = None
    executable: Path | None = None
    metadata: Metadata = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", _as_path(self.root, "root"))
        object.__setattr__(self, "source", _require_stable_id(self.source, "source"))
        object.__setattr__(self, "platform", _require_stable_id(self.platform, "platform"))
        object.__setattr__(self, "store", _optional_stable_id(self.store, "store"))
        object.__setattr__(self, "executable", _optional_path(self.executable, "executable"))
        object.__setattr__(self, "metadata", _readonly_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Result of validating a candidate or user-selected game directory."""

    valid: bool
    normalized_root: Path | None = None
    executable: Path | None = None
    platform: str | None = None
    source: str | None = None
    store: str | None = None
    game_version: str | None = None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    metadata: Metadata = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self) -> None:
        if not isinstance(self.valid, bool):
            raise TypeError("valid must be a bool")
        normalized_root = (
            None
            if self.normalized_root is None
            else _normalized_root(self.normalized_root, "normalized_root")
        )
        errors = _text_tuple(self.errors, "errors")
        warnings = _text_tuple(self.warnings, "warnings")
        platform = _optional_stable_id(self.platform, "platform")
        source = _optional_stable_id(self.source, "source")
        store = _optional_stable_id(self.store, "store")
        if self.valid:
            if normalized_root is None:
                raise ValueError("a valid result requires normalized_root")
            if errors:
                raise ValueError("a valid result cannot contain errors")
            if platform is None:
                raise ValueError("a valid result requires platform")
            if source is None:
                raise ValueError("a valid result requires source")
        elif not errors:
            raise ValueError("an invalid result requires at least one error")

        object.__setattr__(self, "normalized_root", normalized_root)
        object.__setattr__(
            self,
            "executable",
            _normalized_executable(normalized_root, self.executable),
        )
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "store", store)
        object.__setattr__(
            self, "game_version", _optional_text(self.game_version, "game_version")
        )
        object.__setattr__(self, "errors", errors)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "metadata", _readonly_metadata(self.metadata))

    @classmethod
    def success(
        cls,
        normalized_root: PathInput,
        *,
        executable: PathInput | None = None,
        platform: str = "windows",
        source: str = "manual",
        store: str | None = None,
        game_version: str | None = None,
        warnings: Iterable[str] = (),
        metadata: Metadata | None = None,
    ) -> ValidationResult:
        """Build a consistent successful validation result."""

        return cls(
            valid=True,
            normalized_root=normalized_root,
            executable=executable,
            platform=platform,
            source=source,
            store=store,
            game_version=game_version,
            warnings=tuple(warnings),
            metadata={} if metadata is None else metadata,
        )

    @classmethod
    def failure(
        cls,
        errors: str | Iterable[str],
        *,
        normalized_root: PathInput | None = None,
        executable: PathInput | None = None,
        platform: str | None = None,
        source: str | None = None,
        store: str | None = None,
        game_version: str | None = None,
        warnings: Iterable[str] = (),
        metadata: Metadata | None = None,
    ) -> ValidationResult:
        """Build a consistent failed validation result."""

        error_items = (errors,) if isinstance(errors, str) else tuple(errors)
        return cls(
            valid=False,
            normalized_root=normalized_root,
            executable=executable,
            platform=platform,
            source=source,
            store=store,
            game_version=game_version,
            errors=error_items,
            warnings=tuple(warnings),
            metadata={} if metadata is None else metadata,
        )

    def to_installation(
        self,
        *,
        installation_id: str,
        game_id: str,
        adapter_id: str,
        selected: bool = True,
        last_seen: datetime | None = None,
    ) -> GameInstallation:
        """Convert a successful validation result into a persisted installation."""

        if not self.valid:
            raise ValueError("cannot create an installation from a failed validation")
        assert self.normalized_root is not None
        assert self.platform is not None
        assert self.source is not None
        return GameInstallation(
            installation_id=installation_id,
            game_id=game_id,
            adapter_id=adapter_id,
            root=self.normalized_root,
            executable=self.executable,
            platform=self.platform,
            source=self.source,
            store=self.store,
            selected=selected,
            last_seen=last_seen,
            metadata=self.metadata,
        )


@dataclass(frozen=True, slots=True)
class GameInstallation:
    """A validated game installation selected by the user."""

    installation_id: str
    game_id: str
    adapter_id: str
    root: Path
    executable: Path | None
    platform: str
    source: str
    store: str | None = None
    selected: bool = True
    last_seen: datetime | None = None
    metadata: Metadata = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "installation_id",
            _require_stable_id(self.installation_id, "installation_id"),
        )
        object.__setattr__(self, "game_id", _require_stable_id(self.game_id, "game_id"))
        object.__setattr__(
            self, "adapter_id", _require_stable_id(self.adapter_id, "adapter_id")
        )
        root = _normalized_root(self.root)
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "executable", _normalized_executable(root, self.executable))
        object.__setattr__(self, "platform", _require_stable_id(self.platform, "platform"))
        object.__setattr__(self, "source", _require_stable_id(self.source, "source"))
        object.__setattr__(self, "store", _optional_stable_id(self.store, "store"))
        if not isinstance(self.selected, bool):
            raise TypeError("selected must be a bool")
        if self.last_seen is not None:
            if not isinstance(self.last_seen, datetime):
                raise TypeError("last_seen must be a datetime or None")
            if self.last_seen.tzinfo is None or self.last_seen.utcoffset() is None:
                raise ValueError("last_seen must be timezone-aware")
            object.__setattr__(self, "last_seen", self.last_seen.astimezone(timezone.utc))
        object.__setattr__(self, "metadata", _readonly_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class GameState:
    """Adapter-neutral snapshot of a validated installation."""

    game_version: str | None = None
    running: bool = False
    healthy: bool = True
    installed_content: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    metadata: Metadata = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self) -> None:
        if not isinstance(self.running, bool):
            raise TypeError("running must be a bool")
        if not isinstance(self.healthy, bool):
            raise TypeError("healthy must be a bool")
        object.__setattr__(
            self, "game_version", _optional_text(self.game_version, "game_version")
        )
        object.__setattr__(
            self,
            "installed_content",
            _text_tuple(self.installed_content, "installed_content"),
        )
        object.__setattr__(self, "warnings", _text_tuple(self.warnings, "warnings"))
        object.__setattr__(self, "metadata", _readonly_metadata(self.metadata))


__all__ = [
    "AdapterCapability",
    "AdapterDescriptor",
    "GameInstallation",
    "GameState",
    "InstallationCandidate",
    "Metadata",
    "PathInput",
    "ValidationResult",
]
