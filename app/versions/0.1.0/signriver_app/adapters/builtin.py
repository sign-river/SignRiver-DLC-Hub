"""Built-in game adapters shipped with this application module."""

from __future__ import annotations

from .cartridge import GameCartridge
from .protocol import GameAdapter
from .stellaris import StellarisGameCartridge


def create_builtin_cartridges() -> tuple[GameCartridge, ...]:
    return (StellarisGameCartridge(),)


def create_builtin_adapters() -> tuple[GameAdapter, ...]:
    return tuple(cartridge.adapter for cartridge in create_builtin_cartridges())


__all__ = ["create_builtin_adapters", "create_builtin_cartridges"]
