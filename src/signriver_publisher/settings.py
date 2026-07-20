"""Publisher local configuration for mirrored GitLink / GitHub targets."""

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
    github_owner: str = "sign-river"
    github_repository: str = "signriver-dlc-assets"
    github_token: str = ""
    publish_target: str = "gitlink"

    def __post_init__(self) -> None:
        target = str(self.publish_target or "gitlink").strip().lower()
        if target not in {"gitlink", "github"}:
            raise ValueError("publish_target must be gitlink or github")
        object.__setattr__(self, "publish_target", target)

    @property
    def active_owner(self) -> str:
        return self.github_owner if self.publish_target == "github" else self.owner

    @property
    def active_repository(self) -> str:
        return (
            self.github_repository
            if self.publish_target == "github"
            else self.repository
        )

    @property
    def active_token(self) -> str:
        return self.github_token if self.publish_target == "github" else self.token

    def with_publish_target(self, target: str) -> "PublisherSettings":
        return PublisherSettings(
            owner=self.owner,
            repository=self.repository,
            token=self.token,
            github_owner=self.github_owner,
            github_repository=self.github_repository,
            github_token=self.github_token,
            publish_target=target,
        )

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
        github = value.get("github") if isinstance(value.get("github"), dict) else {}
        github_owner = str(github.get("owner", "")).strip() or "sign-river"
        github_repository = (
            str(github.get("repository", "")).strip() or "signriver-dlc-assets"
        )
        github_token = str(github.get("token", "")).strip()
        target = str(value.get("publish_target") or "gitlink").strip().lower()
        if target not in {"gitlink", "github"}:
            raise PublisherSettingsError("publish_target 只能是 gitlink 或 github")
        return cls(
            owner, repository, token,
            github_owner, github_repository, github_token, target,
        )


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
