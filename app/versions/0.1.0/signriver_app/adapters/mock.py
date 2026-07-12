"""Deterministic in-memory game adapter used by tests and early UI slices."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from ..domain import (
    AdapterDescriptor,
    GameInstallation,
    GameState,
    InstallationCandidate,
    PathInput,
    ValidationResult,
)


def _normalized_path(value: PathInput) -> Path:
    """Return a comparable absolute path without requiring it to exist."""

    return Path(value).expanduser().resolve(strict=False)


def _path_key(value: Path) -> str:
    """Build a platform-appropriate key while retaining a ``Path`` in DTOs."""

    return os.path.normcase(os.path.normpath(str(value)))


class MockGameAdapter:
    """A side-effect-free adapter with caller-supplied discovery fixtures.

    Candidate roots are considered valid automatically.  ``valid_roots`` can
    additionally represent manually selected installations that discovery did
    not find.  All comparisons use normalized absolute paths, so equivalent
    spellings such as ``game/.`` match the same fixture.
    """

    def __init__(
        self,
        descriptor: AdapterDescriptor,
        candidates: Iterable[InstallationCandidate] = (),
        valid_roots: Iterable[PathInput] = (),
        state: GameState | None = None,
    ) -> None:
        if not isinstance(descriptor, AdapterDescriptor):
            raise TypeError("descriptor must be an AdapterDescriptor")

        candidate_snapshot = tuple(candidates)
        if not all(
            isinstance(candidate, InstallationCandidate)
            for candidate in candidate_snapshot
        ):
            raise TypeError("candidates must contain InstallationCandidate values")

        if state is not None and not isinstance(state, GameState):
            raise TypeError("state must be a GameState or None")

        self._descriptor = descriptor
        self._candidates = candidate_snapshot
        self._state = GameState() if state is None else state

        self._candidates_by_root: dict[str, tuple[Path, InstallationCandidate]] = {}
        for candidate in self._candidates:
            normalized = _normalized_path(candidate.root)
            self._candidates_by_root.setdefault(
                _path_key(normalized), (normalized, candidate)
            )

        self._valid_roots: dict[str, Path] = {}
        for root in valid_roots:
            normalized = _normalized_path(root)
            self._valid_roots.setdefault(_path_key(normalized), normalized)

    def discover(self) -> list[InstallationCandidate]:
        """Return a new list so callers cannot mutate the stored fixture set."""

        return list(self._candidates)

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    def validate(self, root: Path) -> ValidationResult:
        """Validate ``root`` against discovered candidates or explicit roots."""

        normalized = _normalized_path(root)
        key = _path_key(normalized)

        candidate_match = self._candidates_by_root.get(key)
        if candidate_match is not None:
            canonical_root, candidate = candidate_match
            return ValidationResult.success(
                canonical_root,
                executable=candidate.executable,
                platform=candidate.platform,
                source=candidate.source,
                store=candidate.store,
                metadata=candidate.metadata,
            )

        canonical_root = self._valid_roots.get(key)
        if canonical_root is not None:
            return ValidationResult.success(
                canonical_root,
                platform=self.descriptor.platforms[0],
                source="manual",
                store=(self.descriptor.stores[0] if len(self.descriptor.stores) == 1 else None),
            )

        return ValidationResult.failure(
            f"path is not a valid {self.descriptor.display_name} installation",
            normalized_root=normalized,
        )

    def inspect(self, installation: GameInstallation) -> GameState:
        """Return the configured state after verifying adapter ownership."""

        if installation.game_id != self.descriptor.game_id:
            raise ValueError(
                "installation game_id does not match this adapter's game_id"
            )
        if installation.adapter_id != self.descriptor.adapter_id:
            raise ValueError(
                "installation adapter_id does not match this adapter's adapter_id"
            )
        return self._state


__all__ = ["MockGameAdapter"]
