from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError
from .jsonio import read_json


@dataclass(frozen=True)
class UpdateSettings:
    manifest_url: str = ""
    channel: str = "stable"
    check_on_startup: bool = False
    timeout_seconds: int = 20
    allow_insecure_http: bool = False

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
            for candidate in (defaults_path, path, user_path):
                if candidate is not None and candidate.exists():
                    value.update(read_json(candidate))
            settings = cls(
                manifest_url=value.get("manifest_url", ""),
                channel=value.get("channel", "stable"),
                check_on_startup=value.get("check_on_startup", False),
                timeout_seconds=value.get("timeout_seconds", 20),
                allow_insecure_http=value.get("allow_insecure_http", False),
            )
        except (OSError, ValueError, TypeError) as error:
            raise ConfigurationError(f"Invalid update config: {error}") from error
        if not isinstance(settings.manifest_url, str) or not isinstance(settings.channel, str):
            raise ConfigurationError("Update URL and channel must be strings")
        if not isinstance(settings.check_on_startup, bool) or not isinstance(settings.allow_insecure_http, bool):
            raise ConfigurationError("Update boolean options have invalid types")
        if not isinstance(settings.timeout_seconds, int) or not 1 <= settings.timeout_seconds <= 120:
            raise ConfigurationError("timeout_seconds must be between 1 and 120")
        return settings
