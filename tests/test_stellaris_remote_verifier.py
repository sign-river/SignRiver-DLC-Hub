"""Regression: shared directory validation accepts current and legacy cards."""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

from signriver_app.adapters.document_cartridge import build_cartridge_from_document
from signriver_app.domain import CartridgeDocument


def _stellaris_document() -> CartridgeDocument:
    return CartridgeDocument.from_dict(
        {
            "schema_version": 1,
            "engine": "steam_configured_v1",
            "game_id": "stellaris",
            "display_name": "?? (Stellaris)",
            "store_app_id": "281990",
            "release_tag": "stellaris",
            "executable_relative_path": "stellaris.exe",
            "dlc_relative_dir": "dlc",
            "package_inspector": "directory",
            "patch": {
                "unlocker_dll_name": "steam_api64.dll",
                "runtime_original_library_name": "steam_api64_o.dll",
                "appinfo_asset_name": "stellaris_appinfo.json",
                "install_relative_dir": ".",
                "ini_target_name": "cream_api.ini",
                "language": "schinese",
                "unlock_all": True,
                "extra_protection": False,
                "force_offline": False,
            },
        }
    )


def _write_stellaris_package(path: Path) -> None:
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr("events/content.txt", "sample")
    descriptor = "\n".join(
        [
            'name = "Symbols of Domination"',
            'archive = "dlc/dlc001_symbols_of_domination/dlc001.zip"',
            'steam_id = 447680',
        ]
    )
    with zipfile.ZipFile(path, "w") as package:
        root = "dlc001_symbols_of_domination/"
        package.writestr(root + "dlc001.dlc", descriptor)
        package.writestr(root + "dlc001.zip", nested.getvalue())


def test_remote_stellaris_cartridge_uses_shared_directory_verifier(
    tmp_path: Path,
) -> None:
    cartridge = build_cartridge_from_document(
        _stellaris_document(), platform="windows"
    )
    package = tmp_path / "dlc001_symbols_of_domination.zip"
    _write_stellaris_package(package)
    known = hashlib.sha256(package.read_bytes()).hexdigest()

    metadata = cartridge.inspect_package(
        package,
        asset_name="dlc001_symbols_of_domination.zip",
        known_sha256=known,
    )

    assert metadata.dlc_id == "dlc001"
    assert metadata.display_name == "Symbols Of Domination"


def test_legacy_stellaris_inspector_label_remains_compatible(tmp_path: Path) -> None:
    payload = _stellaris_document().to_dict()
    payload["package_inspector"] = "stellaris_zip"
    cartridge = build_cartridge_from_document(
        CartridgeDocument.from_dict(payload), platform="windows"
    )
    package = tmp_path / "dlc001_symbols_of_domination.zip"
    _write_stellaris_package(package)

    assert cartridge.inspect_package(package).dlc_id == "dlc001"
