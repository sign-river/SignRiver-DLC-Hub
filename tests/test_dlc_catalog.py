from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from signriver_app.application import StellarisCatalogService
from signriver_app.infrastructure.catalog import GitLinkReleaseSource, GitLinkSourceConfig, PackageInspectionError, inspect_stellaris_package


def payload() -> bytes:
    return json.dumps({"status": 0, "releases": [{"id": "67956677", "tag_name": "ste", "name": "ste", "body": "4.4", "attachments": [
        {"id": 483832, "title": "dlc001_symbols_of_domination.zip", "filesize": "75.6 KB", "url": "/signriver/file-warehouse/releases/download/ste/dlc001_symbols_of_domination.zip"},
        {"id": 1, "title": "stellaris_appinfo.json", "filesize": "2.8 KB", "url": "/signriver/file-warehouse/releases/download/ste/stellaris_appinfo.json"},
    ]}]}).encode()


def make_source() -> GitLinkReleaseSource:
    return GitLinkReleaseSource(GitLinkSourceConfig("signriver", "file-warehouse"), fetch=lambda *_args: payload())


def test_gitlink_source_normalizes_release_and_assets() -> None:
    release = make_source().get_release_by_tag("ste")
    assert release.release_id == "67956677"
    assert release.assets[0].size_bytes == round(75.6 * 1024)
    assert release.assets[0].download_url.endswith("/ste/dlc001_symbols_of_domination.zip")


def test_stellaris_catalog_ignores_non_dlc_assets() -> None:
    entries = StellarisCatalogService(make_source()).refresh()
    assert [(item.dlc_id, item.display_name) for item in entries] == [("dlc001", "Symbols Of Domination")]


def write_package(path: Path) -> None:
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr("events/content.txt", "sample")
    descriptor = '\n'.join(['name = "Symbols of Domination"', 'archive = "dlc/dlc001_symbols_of_domination/dlc001.zip"', 'steam_id = 447680', 'category="content_pack"', 'thumbnail = "thumbnail.png"'])
    with zipfile.ZipFile(path, "w") as package:
        root = "dlc001_symbols_of_domination/"
        package.writestr(root + "dlc001.dlc", descriptor)
        package.writestr(root + "dlc001.zip", nested.getvalue())
        package.writestr(root + "thumbnail.png", b"png")


def test_inspect_stellaris_package_reads_descriptor_and_payload(tmp_path: Path) -> None:
    path = tmp_path / "dlc.zip"
    write_package(path)
    result = inspect_stellaris_package(path)
    assert (result.dlc_id, result.display_name, result.steam_id) == ("dlc001", "Symbols of Domination", "447680")
    assert result.category == "content_pack"
    assert result.payload_entries == 1
    assert len(result.package_sha256) == 64


def test_inspect_stellaris_package_rejects_traversal(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("../dlc001.dlc", 'name="x"\narchive="dlc/x.zip"')
    with pytest.raises(PackageInspectionError, match="unsafe ZIP member"):
        inspect_stellaris_package(path)


def test_gitlink_config_rejects_non_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        GitLinkSourceConfig("signriver", "file-warehouse", "http://example.test")
