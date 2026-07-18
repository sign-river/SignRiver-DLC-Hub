from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from signriver_app.application import OriginalStateRestoreService


class FakeRepository:
    def __init__(self) -> None:
        self.receipts = {
            "dlc001": SimpleNamespace(dlc_id="dlc001", transaction_id="tx-1"),
        }

    def active(self, game_id):
        assert game_id == "game"
        return tuple(self.receipts.values())


class FakeInstallService:
    def __init__(self) -> None:
        self.uninstalled = []

    def uninstall(self, game_id, dlc_id, game_root):
        self.uninstalled.append((game_id, dlc_id, Path(game_root)))


class FakePatchEngine:
    def __init__(self, *, ready=True, reason="") -> None:
        self.ready = ready
        self.reason = reason
        self.restored = False

    def inspect_original_restore(self, game_root):
        return SimpleNamespace(ready=self.ready, reason=self.reason)

    def restore_original(self, game_root):
        self.restored = True
        return ("steam_api64_o.dll", "cream_api.ini")


class FakeCartridge:
    def __init__(self) -> None:
        self.adapter = SimpleNamespace(descriptor=SimpleNamespace(game_id="game"))

    def discover_installed_dlc(self, game_root, catalog_entries=()):
        raise AssertionError("safe restore must not scan all game DLC directories")

    def remove_installed_dlc(self, game_root, dlc_id):
        raise AssertionError("safe restore must not remove untracked game DLC")


def make_service(*, patch_ready=True):
    cartridge = FakeCartridge()
    patch = FakePatchEngine(ready=patch_ready, reason="原版备份缺失")
    installs = FakeInstallService()
    repository = FakeRepository()
    return (
        OriginalStateRestoreService(cartridge, patch, installs, repository),
        cartridge,
        patch,
        installs,
        repository,
    )


def test_safe_restore_only_uninstalls_receipted_dlc() -> None:
    service, cartridge, patch, installs, repository = make_service()

    result = service.restore(Path("C:/game"))

    assert [item[1] for item in installs.uninstalled] == ["dlc001"]
    assert patch.restored is True
    assert result.restored_dlc_ids == ("dlc001",)
    assert result.failures == ()


def test_restore_preview_uses_receipts_without_scanning_game_dlc() -> None:
    service, _cartridge, _patch, _installs, _repository = make_service()

    preview = service.preview(Path("C:/game"))

    assert preview.tracked_dlc_ids == ("dlc001",)
    assert preview.dlc_count == 1


def test_restore_refuses_to_start_when_patch_backup_is_not_provable() -> None:
    from signriver_app.application import RestoreOriginalError

    service, cartridge, patch, installs, repository = make_service(patch_ready=False)

    try:
        service.restore(Path("C:/game"))
    except RestoreOriginalError as error:
        assert "备份缺失" in str(error)
    else:
        raise AssertionError("restore should have been refused")
    assert installs.uninstalled == []
    assert patch.restored is False
