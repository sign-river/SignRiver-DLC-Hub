from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from signriver_app.application import OriginalStateRestoreService, RestoreScope


class FakeRepository:
    def __init__(self) -> None:
        self.receipts = {
            "dlc001": SimpleNamespace(dlc_id="dlc001", transaction_id="tx-1"),
        }
        self.marked = []

    def active(self, game_id):
        assert game_id == "game"
        return tuple(self.receipts.values())

    def find_active(self, game_id, dlc_id):
        assert game_id == "game"
        return self.receipts.get(dlc_id)

    def mark_uninstalled(self, transaction_id, *, restore_previous=False):
        self.marked.append((transaction_id, restore_previous))


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
        self.removed = []

    def discover_installed_dlc(self, game_root, catalog_entries=()):
        return {"dlc001": Path(game_root) / "dlc001", "dlc002": Path(game_root) / "dlc002"}

    def remove_installed_dlc(self, game_root, dlc_id):
        self.removed.append(dlc_id)


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

    result = service.restore(Path("C:/game"), RestoreScope.SAFE)

    assert [item[1] for item in installs.uninstalled] == ["dlc001"]
    assert cartridge.removed == []
    assert patch.restored is True
    assert result.restored_dlc_ids == ("dlc001",)
    assert result.failures == ()


def test_full_restore_removes_every_detected_dlc() -> None:
    service, cartridge, patch, installs, repository = make_service()

    result = service.restore(Path("C:/game"), RestoreScope.FULL)

    assert installs.uninstalled == []
    assert cartridge.removed == ["dlc001", "dlc002"]
    assert repository.marked == [("tx-1", False)]
    assert result.restored_dlc_ids == ("dlc001", "dlc002")


def test_restore_refuses_to_start_when_patch_backup_is_not_provable() -> None:
    from signriver_app.application import RestoreOriginalError

    service, cartridge, patch, installs, repository = make_service(patch_ready=False)

    try:
        service.restore(Path("C:/game"), RestoreScope.SAFE)
    except RestoreOriginalError as error:
        assert "备份缺失" in str(error)
    else:
        raise AssertionError("restore should have been refused")
    assert installs.uninstalled == []
    assert patch.restored is False
