"""Built-in game adapters shipped with this application module."""

from __future__ import annotations

from .protocol import GameAdapter
from .stellaris import StellarisSteamAdapter


def create_builtin_adapters() -> tuple[GameAdapter, ...]:
    return (StellarisSteamAdapter(),)


__all__ = ["create_builtin_adapters"]
