from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


ANNOUNCEMENT_SCHEMA_VERSION = 1
_SAFE_ANNOUNCEMENT_ID = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
)


class AnnouncementValidationError(ValueError):
    """Raised when a publisher announcement cannot be used by the client."""


@dataclass(frozen=True, slots=True)
class AnnouncementDraft:
    announcement_id: str = ""
    title: str = ""
    updated_at: str = ""
    body: str = ""
    enabled: bool = False

    @classmethod
    def empty(cls) -> "AnnouncementDraft":
        today = date.today().isoformat()
        return cls(
            announcement_id=f"{today}-notice",
            updated_at=today,
        )

    @classmethod
    def from_dict(
        cls, value: dict[str, object], *, enabled: bool | None = None
    ) -> "AnnouncementDraft":
        raw_enabled = value.get("enabled", False) if enabled is None else enabled
        return cls(
            announcement_id=str(value.get("id", "")).strip(),
            title=str(value.get("title", "")).strip(),
            updated_at=str(value.get("updated_at", "")).strip(),
            body=str(value.get("body", "")).strip(),
            enabled=bool(raw_enabled),
        )

    def validate(self) -> "AnnouncementDraft":
        announcement_id = self.announcement_id.strip()
        title = self.title.strip()
        updated_at = self.updated_at.strip()
        body = self.body.strip()
        if not _SAFE_ANNOUNCEMENT_ID.fullmatch(announcement_id):
            raise AnnouncementValidationError(
                "公告版本 ID 只能包含字母、数字、点、下划线和短横线，且不能超过 128 个字符"
            )
        if not title:
            raise AnnouncementValidationError("公告标题不能为空")
        if not body:
            raise AnnouncementValidationError("公告正文不能为空")
        try:
            date.fromisoformat(updated_at)
        except ValueError as error:
            raise AnnouncementValidationError(
                "公告日期必须使用 YYYY-MM-DD 格式"
            ) from error
        return AnnouncementDraft(
            announcement_id=announcement_id,
            title=title,
            updated_at=updated_at,
            body=body,
            enabled=self.enabled,
        )

    def to_announcement_dict(self) -> dict[str, object]:
        value = self.validate()
        return {
            "schema_version": ANNOUNCEMENT_SCHEMA_VERSION,
            "id": value.announcement_id,
            "title": value.title,
            "updated_at": value.updated_at,
            "body": value.body,
        }

    def to_draft_dict(self) -> dict[str, object]:
        return {
            "schema_version": ANNOUNCEMENT_SCHEMA_VERSION,
            "enabled": self.enabled,
            "id": self.announcement_id.strip(),
            "title": self.title.strip(),
            "updated_at": self.updated_at.strip(),
            "body": self.body.strip(),
        }


__all__ = [
    "ANNOUNCEMENT_SCHEMA_VERSION",
    "AnnouncementDraft",
    "AnnouncementValidationError",
]
