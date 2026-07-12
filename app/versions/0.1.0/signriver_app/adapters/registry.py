"""In-memory registry for game adapters."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from threading import RLock
from typing import Any, cast

from ..domain import AdapterDescriptor
from .errors import (
    AdapterNotFoundError,
    DuplicateAdapterError,
    InvalidAdapterError,
)
from .protocol import GameAdapter


@dataclass(frozen=True, slots=True)
class _RegistryEntry:
    adapter: GameAdapter
    descriptor: AdapterDescriptor


class AdapterRegistry:
    """Store validated adapters by their globally unique adapter id.

    Registration order is preserved for predictable UI presentation.  More
    than one adapter may target the same game (for example, different stores),
    but an ``adapter_id`` is unique within a registry.
    """

    def __init__(self, adapters: Iterable[GameAdapter] = ()) -> None:
        self._adapters: dict[str, _RegistryEntry] = {}
        self._lock = RLock()
        self.register_many(adapters)

    def register(self, adapter: GameAdapter) -> None:
        """Validate and register one adapter."""

        self.register_many((adapter,))

    def register_many(self, adapters: Iterable[GameAdapter]) -> None:
        """Validate and register a group of adapters atomically.

        If iteration, validation, or duplicate detection fails, none of the
        adapters from this call are added.
        """

        with self._lock:
            pending: list[tuple[str, _RegistryEntry]] = []
            reserved_ids = set(self._adapters)

            for candidate in adapters:
                adapter_id, adapter, descriptor = self._validate(candidate)
                if adapter_id in reserved_ids:
                    raise DuplicateAdapterError(adapter_id)
                reserved_ids.add(adapter_id)
                pending.append((adapter_id, _RegistryEntry(adapter, descriptor)))

            # Mutation deliberately happens only after the whole iterable has
            # been consumed and validated, preserving batch atomicity even for
            # generators that fail part-way through iteration.
            self._adapters.update(pending)

    def unregister(self, adapter_id: str) -> GameAdapter:
        """Remove and return an adapter, or raise if it is unknown."""

        with self._lock:
            try:
                return self._adapters.pop(adapter_id).adapter
            except KeyError as exc:
                raise AdapterNotFoundError(adapter_id) from exc

    def get(self, adapter_id: str) -> GameAdapter:
        """Return a registered adapter by id."""

        with self._lock:
            try:
                entry = self._adapters[adapter_id]
            except KeyError as exc:
                raise AdapterNotFoundError(adapter_id) from exc
            return self._verified_adapter(entry)

    def all(self) -> tuple[GameAdapter, ...]:
        """Return an immutable snapshot in registration order."""

        with self._lock:
            return tuple(self._verified_adapter(entry) for entry in self._adapters.values())

    def for_game(self, game_id: str) -> tuple[GameAdapter, ...]:
        """Return all adapters targeting ``game_id`` in registration order."""

        with self._lock:
            return tuple(
                self._verified_adapter(entry)
                for entry in self._adapters.values()
                if entry.descriptor.game_id == game_id
            )

    def game_ids(self) -> tuple[str, ...]:
        """Return unique game ids in first-adapter registration order."""

        with self._lock:
            entries = tuple(self._adapters.values())
            for entry in entries:
                self._verified_adapter(entry)
            return tuple(
                dict.fromkeys(
                    entry.descriptor.game_id
                    for entry in entries
                )
            )

    def __len__(self) -> int:
        with self._lock:
            return len(self._adapters)

    def __iter__(self) -> Iterator[GameAdapter]:
        return iter(self.all())

    def __contains__(self, adapter_id: object) -> bool:
        if not isinstance(adapter_id, str):
            return False
        with self._lock:
            return adapter_id in self._adapters

    @staticmethod
    def _validate(candidate: Any) -> tuple[str, GameAdapter, AdapterDescriptor]:
        if candidate is None:
            raise InvalidAdapterError("adapter object must not be None")

        try:
            descriptor = candidate.descriptor
        except Exception as exc:
            raise InvalidAdapterError(
                "missing or unreadable descriptor",
                adapter=candidate,
            ) from exc

        if not isinstance(descriptor, AdapterDescriptor):
            raise InvalidAdapterError(
                "descriptor must be an AdapterDescriptor",
                adapter=candidate,
            )

        adapter_id = descriptor.adapter_id
        if not isinstance(adapter_id, str) or not adapter_id.strip():
            raise InvalidAdapterError(
                "descriptor.adapter_id must be a non-empty string",
                adapter=candidate,
            )

        game_id = descriptor.game_id
        if not isinstance(game_id, str) or not game_id.strip():
            raise InvalidAdapterError(
                "descriptor.game_id must be a non-empty string",
                adapter=candidate,
            )

        for method_name in ("discover", "validate", "inspect"):
            try:
                method = getattr(candidate, method_name)
            except Exception as exc:
                raise InvalidAdapterError(
                    f"missing or unreadable {method_name}() method",
                    adapter=candidate,
                ) from exc
            if not callable(method):
                raise InvalidAdapterError(
                    f"{method_name} must be callable",
                    adapter=candidate,
                )

        return adapter_id, cast(GameAdapter, candidate), descriptor

    @staticmethod
    def _verified_adapter(entry: _RegistryEntry) -> GameAdapter:
        try:
            current_descriptor = entry.adapter.descriptor
        except Exception as exc:
            raise InvalidAdapterError(
                "descriptor became unreadable after registration",
                adapter=entry.adapter,
            ) from exc
        if current_descriptor != entry.descriptor:
            raise InvalidAdapterError(
                "descriptor changed after registration",
                adapter=entry.adapter,
            )
        return entry.adapter
