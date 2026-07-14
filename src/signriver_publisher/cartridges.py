"""Built-in publisher cartridges.

Disk cartridges under ``publisher-workspace/games`` remain the source of
truth. Built-ins are only used to seed an empty publisher workspace.
"""

from __future__ import annotations

from .models import PublisherCartridge


def create_builtin_cartridges() -> tuple[PublisherCartridge, ...]:
    return (PublisherCartridge.create("stellaris", "Stellaris", "281990"),)


__all__ = ["create_builtin_cartridges"]
