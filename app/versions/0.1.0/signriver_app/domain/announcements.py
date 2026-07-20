"""Remote announcement documents shown after the desktop shell starts."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
ANNOUNCEMENT_SCHEMA = 1
ANNOUNCEMENT_ASSET_NAME = "announcement.json"


@dataclass(frozen=True, slots=True)
class Announcement:
    """One remote notice identified by a stable revision id."""

    schema_version: int
    announcement_id: str
    title: str
    body: str
    updated_at: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != ANNOUNCEMENT_SCHEMA:
            raise ValueError(
                f"unsupported announcement schema {self.schema_version}"
            )
        if not _SAFE_ID.fullmatch(self.announcement_id):
            raise ValueError("announcement_id must be a short stable token")
        if not self.title.strip():
            raise ValueError("announcement title is required")
        if not self.body.strip():
            raise ValueError("announcement body is required")

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "Announcement":
        return cls(
            schema_version=int(value.get("schema_version") or 0),
            announcement_id=str(
                value.get("id") or value.get("announcement_id") or ""
            ).strip(),
            title=str(value.get("title") or "").strip(),
            body=str(value.get("body") or "").strip(),
            updated_at=str(value.get("updated_at") or "").strip(),
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "id": self.announcement_id,
            "title": self.title,
            "body": self.body,
        }
        if self.updated_at:
            payload["updated_at"] = self.updated_at
        return payload


__all__ = [
    "ANNOUNCEMENT_ASSET_NAME",
    "ANNOUNCEMENT_SCHEMA",
    "Announcement",
]
