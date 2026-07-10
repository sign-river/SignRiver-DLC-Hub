from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigurationError
from .jsonio import atomic_write_json, read_json
from .versioning import Version


@dataclass
class InstallState:
    active_version: str
    previous_version: str | None = None
    pending_version: str | None = None
    bad_versions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict) -> "InstallState":
        active = value.get("active_version")
        if not isinstance(active, str):
            raise ConfigurationError("app/state.json is missing active_version")
        Version.parse(active)
        previous = value.get("previous_version")
        pending = value.get("pending_version")
        bad = value.get("bad_versions", [])
        if previous is not None and not isinstance(previous, str):
            raise ConfigurationError("previous_version must be a string or null")
        if pending is not None and not isinstance(pending, str):
            raise ConfigurationError("pending_version must be a string or null")
        if previous is not None:
            Version.parse(previous)
        if pending is not None:
            Version.parse(pending)
        if not isinstance(bad, list) or not all(isinstance(item, str) for item in bad):
            raise ConfigurationError("bad_versions must be a string array")
        return cls(active, previous, pending, list(dict.fromkeys(bad)))

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "active_version": self.active_version,
            "previous_version": self.previous_version,
            "pending_version": self.pending_version,
            "bad_versions": self.bad_versions,
        }


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> InstallState:
        try:
            return InstallState.from_dict(read_json(self.path))
        except FileNotFoundError as error:
            raise ConfigurationError(f"Missing application state: {self.path}") from error
        except ValueError as error:
            raise ConfigurationError(str(error)) from error

    def save(self, state: InstallState) -> None:
        atomic_write_json(self.path, state.to_dict())

    def bootstrap(self, version: str) -> InstallState:
        Version.parse(version)
        state = InstallState(active_version=version)
        self.save(state)
        return state

    def activate(self, version: str) -> InstallState:
        Version.parse(version)
        state = self.load()
        if version == state.active_version:
            return state
        state.previous_version = state.active_version
        state.active_version = version
        state.pending_version = version
        state.bad_versions = [item for item in state.bad_versions if item != version]
        self.save(state)
        return state

    def mark_healthy(self, version: str) -> InstallState:
        state = self.load()
        if state.active_version != version:
            raise ConfigurationError("Cannot mark an inactive module as healthy")
        if state.pending_version == version:
            state.pending_version = None
            self.save(state)
        return state

    def rollback_pending(self, failed_version: str) -> InstallState:
        state = self.load()
        if state.active_version != failed_version or state.pending_version != failed_version:
            return state
        if not state.previous_version:
            raise ConfigurationError("The failed module has no rollback target")
        rollback_version = state.previous_version
        state.bad_versions = list(dict.fromkeys([*state.bad_versions, failed_version]))
        state.active_version = rollback_version
        state.previous_version = None
        state.pending_version = None
        self.save(state)
        return state
