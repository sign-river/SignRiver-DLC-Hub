from pathlib import Path

import pytest

from signriver_app.domain import UserSettings
from signriver_app.infrastructure.persistence import Database, UserSettingsRepository


def test_user_settings_defaults_and_round_trip(tmp_path: Path) -> None:
    repository = UserSettingsRepository(Database(tmp_path / "hub.db"))
    assert repository.load() == UserSettings()
    settings = UserSettings(
        download_concurrency=4, bandwidth_limit_kib=2048,
        onboarding_completed=True,
    )
    repository.save(settings)
    assert repository.load() == settings


def test_user_settings_validation() -> None:
    with pytest.raises(ValueError, match="between"):
        UserSettings(download_concurrency=0)
    with pytest.raises(ValueError, match="positive"):
        UserSettings(bandwidth_limit_kib=0)
