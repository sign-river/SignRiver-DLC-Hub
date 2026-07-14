from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


class PublisherSettingsError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PublisherSettings:
    owner: str = "signriver"
    repository: str = "signriver-dlc-assets"
    token: str = ""

    @classmethod
    def load(cls, path: Path) -> "PublisherSettings":
        if not path.is_file():
            return cls()
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise PublisherSettingsError(f"无法读取发布器本地配置：{error}") from error
        if not isinstance(value, dict) or not isinstance(value.get("gitlink"), dict):
            raise PublisherSettingsError("发布器本地配置缺少 gitlink 对象")
        gitlink = value["gitlink"]
        owner = str(gitlink.get("owner", "")).strip()
        repository = str(gitlink.get("repository", "")).strip()
        token = str(gitlink.get("token", "")).strip()
        if not owner or not repository:
            raise PublisherSettingsError("GitLink owner 和 repository 不能为空")
        return cls(owner, repository, token)


def discover_settings_path() -> Path:
    explicit = os.environ.get("SIGNRIVER_PUBLISHER_CONFIG", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "publisher.local.json")
    candidates.extend(
        [
            Path.cwd() / "config" / "publisher.local.json",
            Path(__file__).resolve().parents[2] / "config" / "publisher.local.json",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]
