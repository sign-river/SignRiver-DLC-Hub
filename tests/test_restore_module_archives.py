from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from tools import restore_module_archives as rma


def _module_archive(version: str = "0.1.3") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr(
            "module.json",
            json.dumps({"version": version, "entrypoint": "app_entry.py"}),
        )
        package.writestr("app_entry.py", "print('ok')\n")
    return buffer.getvalue()


def _catalog(payload: bytes, version: str = "0.1.3") -> dict:
    return {
        "schema_version": 1,
        "repository": "sign-river/signriver-dlc-assets",
        "repositories": {
            "github": "sign-river/signriver-dlc-assets",
            "gitlink": "signriver/signriver-dlc-assets",
        },
        "release": "modules",
        "modules": [
            {
                "version": version,
                "filename": f"SignRiver-DLC-Hub-module-v{version}.zip",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
            }
        ],
    }


def test_repository_for_prefers_platform_specific_owner() -> None:
    catalog = _catalog(b"x")
    assert rma.repository_for(catalog, "gitlink") == "signriver/signriver-dlc-assets"
    assert rma.repository_for(catalog, "github") == "sign-river/signriver-dlc-assets"


def test_repository_for_falls_back_to_legacy_field() -> None:
    catalog = _catalog(b"x")
    del catalog["repositories"]
    assert rma.repository_for(catalog, "gitlink") == "sign-river/signriver-dlc-assets"
    assert rma.repository_for(catalog, "github") == "sign-river/signriver-dlc-assets"


def test_download_builds_platform_correct_direct_urls(tmp_path, monkeypatch) -> None:
    payload = _module_archive()
    catalog = _catalog(payload)
    module = catalog["modules"][0]
    monkeypatch.setattr(rma, "ROOT", tmp_path)
    captured: list[str] = []

    class _FakeResponse(io.BytesIO):
        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *_args) -> None:
            self.close()

    def fake_urlopen(url: str, **_kwargs) -> _FakeResponse:
        captured.append(url)
        return _FakeResponse(payload)

    monkeypatch.setattr(rma.urllib.request, "urlopen", fake_urlopen)

    gitlink_archive = rma.download(module, catalog, "gitlink", refresh=True)
    assert captured[-1] == (
        "https://gitlink.org.cn/signriver/signriver-dlc-assets/"
        "releases/download/modules/SignRiver-DLC-Hub-module-v0.1.3.zip"
    )
    assert gitlink_archive.is_file()

    github_archive = rma.download(module, catalog, "github", refresh=True)
    assert captured[-1] == (
        "https://github.com/sign-river/signriver-dlc-assets/"
        "releases/download/modules/SignRiver-DLC-Hub-module-v0.1.3.zip"
    )
    assert github_archive.is_file()


def test_download_skips_network_when_local_archive_is_valid(tmp_path, monkeypatch) -> None:
    payload = _module_archive()
    catalog = _catalog(payload)
    module = catalog["modules"][0]
    monkeypatch.setattr(rma, "ROOT", tmp_path)
    cached = tmp_path / "dist" / "modules" / module["filename"]
    cached.parent.mkdir(parents=True)
    cached.write_bytes(payload)
    calls: list[str] = []

    def fake_urlopen(url: str, **_kwargs):
        calls.append(url)
        raise AssertionError("network must not be used")

    monkeypatch.setattr(rma.urllib.request, "urlopen", fake_urlopen)
    archive = rma.download(module, catalog, "gitlink", refresh=False)
    assert archive.is_file()
    assert calls == []


def test_download_rejects_non_archive_response(tmp_path, monkeypatch) -> None:
    payload = _module_archive()
    catalog = _catalog(payload)
    module = catalog["modules"][0]
    monkeypatch.setattr(rma, "ROOT", tmp_path)

    class _HtmlResponse(io.BytesIO):
        def __enter__(self) -> "_HtmlResponse":
            return self

        def __exit__(self, *_args) -> None:
            self.close()

    def fake_urlopen(url: str, **_kwargs) -> _HtmlResponse:
        return _HtmlResponse(b"<!doctype html><html>login page</html>")

    monkeypatch.setattr(rma.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(SystemExit, match="integrity check failed"):
        rma.download(module, catalog, "gitlink", refresh=True)
