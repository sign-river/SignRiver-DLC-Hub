"""Persistent repair workflow journal used to resume or diagnose interrupted repairs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class RepairJournalState:
    game_id: str
    game_root: str
    phase: str
    requested_dlc_ids: tuple[str, ...]
    completed_dlc_ids: tuple[str, ...]
    status: str
    message: str
    updated_at: float


class RepairJournal:
    """Small atomic journal outside the download cache.

    A new repair invocation can reuse the requested set from an unfinished
    journal and safely repeat idempotent preparation/patch/install stages.
    """

    def __init__(self, data_root: Path, *, clock=time.time) -> None:
        self.root = Path(data_root).resolve() / "repair-journals" / "v1"
        self._clock = clock

    def path_for(self, game_id: str, game_root: Path) -> Path:
        identity = f"{game_id.strip().casefold()}|{os.path.normcase(str(Path(game_root).resolve()))}"
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return self.root / f"{key}.json"

    def load(self, game_id: str, game_root: Path) -> RepairJournalState | None:
        path = self.path_for(game_id, game_root)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("schema") != 1:
                return None
            if value.get("game_id") != game_id:
                return None
            if Path(str(value.get("game_root"))).resolve() != Path(game_root).resolve():
                return None
            return RepairJournalState(
                game_id=game_id,
                game_root=str(value["game_root"]),
                phase=str(value.get("phase") or "unknown"),
                requested_dlc_ids=tuple(str(item) for item in value.get("requested_dlc_ids", ())),
                completed_dlc_ids=tuple(str(item) for item in value.get("completed_dlc_ids", ())),
                status=str(value.get("status") or "active"),
                message=str(value.get("message") or ""),
                updated_at=float(value.get("updated_at") or 0),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def update(
        self,
        game_id: str,
        game_root: Path,
        *,
        phase: str,
        requested_dlc_ids: Iterable[str],
        completed_dlc_ids: Iterable[str] = (),
        status: str = "active",
        message: str = "",
    ) -> None:
        path = self.path_for(game_id, game_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schema": 1,
            "game_id": game_id,
            "game_root": str(Path(game_root).resolve()),
            "phase": phase,
            "requested_dlc_ids": list(dict.fromkeys(str(item) for item in requested_dlc_ids)),
            "completed_dlc_ids": list(dict.fromkeys(str(item) for item in completed_dlc_ids)),
            "status": status,
            "message": message,
            "updated_at": self._clock(),
        }
        payload = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        handle = tempfile.NamedTemporaryFile(
            "wb", delete=False, dir=str(path.parent), prefix=".repair-", suffix=".tmp"
        )
        try:
            with handle as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(handle.name, path)
        except Exception:
            Path(handle.name).unlink(missing_ok=True)
            raise

    def complete(self, game_id: str, game_root: Path) -> None:
        self.path_for(game_id, game_root).unlink(missing_ok=True)


__all__ = ["RepairJournal", "RepairJournalState"]
