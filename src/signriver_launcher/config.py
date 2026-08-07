from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from .errors import ConfigurationError
from .jsonio import read_json


@dataclass(frozen=True)
class UpdateSettings:
    manifest_url: str = ""
    manifest_urls: dict[str, str] = field(default_factory=dict)
    download_source: str = "gitlink"
    channel: str = "stable"
    check_on_startup: bool = False
    timeout_seconds: int = 20
    allow_insecure_http: bool = False

    @property
    def active_manifest_url(self) -> str:
        return self.manifest_urls.get(self.download_source, "") or self.manifest_url

    def with_download_source(self, source: str) -> "UpdateSettings":
        normalized = str(source or "").strip().lower()
        if normalized not in {"gitlink", "github"}:
            raise ConfigurationError("download_source must be gitlink or github")
        return replace(self, download_source=normalized)

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        defaults_path: Path | None = None,
        user_path: Path | None = None,
    ) -> "UpdateSettings":
        try:
            value: dict = {}
            manifest_urls: dict[str, str] = {}
            for candidate in (defaults_path, path, user_path):
                if candidate is not None and candidate.exists():
                    layer = read_json(candidate)
                    layer_urls = layer.pop("manifest_urls", None)
                    if layer_urls is not None:
                        if not isinstance(layer_urls, dict):
                            raise TypeError("manifest_urls must be an object")
                        manifest_urls.update(layer_urls)
                    value.update(layer)
            settings = cls(
                manifest_url=value.get("manifest_url", ""),
                manifest_urls=manifest_urls,
                download_source=value.get("download_source", "gitlink"),
                channel=value.get("channel", "stable"),
                check_on_startup=value.get("check_on_startup", False),
                timeout_seconds=value.get("timeout_seconds", 20),
                allow_insecure_http=value.get("allow_insecure_http", False),
            )
        except (OSError, ValueError, TypeError) as error:
            raise ConfigurationError(f"Invalid update config: {error}") from error
        if not isinstance(settings.manifest_url, str) or not isinstance(settings.channel, str):
            raise ConfigurationError("Update URL and channel must be strings")
        if settings.download_source not in {"gitlink", "github"}:
            raise ConfigurationError("download_source must be gitlink or github")
        if any(
            source not in {"gitlink", "github"} or not isinstance(url, str)
            for source, url in settings.manifest_urls.items()
        ):
            raise ConfigurationError(
                "manifest_urls may only contain string gitlink/github URLs"
            )
        if not isinstance(settings.check_on_startup, bool) or not isinstance(settings.allow_insecure_http, bool):
            raise ConfigurationError("Update boolean options have invalid types")
        if not isinstance(settings.timeout_seconds, int) or not 1 <= settings.timeout_seconds <= 120:
            raise ConfigurationError("timeout_seconds must be between 1 and 120")
        return settings
