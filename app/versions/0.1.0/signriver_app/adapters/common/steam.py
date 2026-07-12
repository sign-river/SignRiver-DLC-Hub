"""Read-only Steam library and app-manifest discovery."""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_VDF_BYTES = 4 * 1024 * 1024
MAX_VDF_DEPTH = 64


class VdfError(ValueError):
    """Raised when a Steam VDF/ACF document is malformed or unsafe."""


@dataclass(frozen=True, slots=True)
class SteamScanIssue:
    path: Path
    message: str


@dataclass(frozen=True, slots=True)
class SteamAppInstallation:
    app_id: str
    name: str
    install_dir: str
    root: Path
    library_root: Path
    manifest_path: Path
    build_id: str | None = None
    state_flags: str | None = None


class SteamInstallationLocator:
    """Locate installed Steam applications across configured libraries."""

    def __init__(self, steam_roots: Iterable[Path] | None = None) -> None:
        roots = (
            discover_windows_steam_roots()
            if steam_roots is None
            else tuple(Path(root) for root in steam_roots)
        )
        self._steam_roots = _deduplicate_paths(roots)
        self._last_issues: tuple[SteamScanIssue, ...] = ()

    @property
    def steam_roots(self) -> tuple[Path, ...]:
        return self._steam_roots

    @property
    def last_issues(self) -> tuple[SteamScanIssue, ...]:
        return self._last_issues

    def library_roots(self) -> tuple[Path, ...]:
        libraries, issues = self._read_library_roots()
        self._last_issues = tuple(issues)
        return libraries

    def find_app(self, app_id: str) -> tuple[SteamAppInstallation, ...]:
        if not isinstance(app_id, str) or not app_id.isdigit():
            raise ValueError("app_id must contain only decimal digits")

        libraries, issues = self._read_library_roots()
        found: list[SteamAppInstallation] = []
        for library in libraries:
            manifest = library / "steamapps" / f"appmanifest_{app_id}.acf"
            if not manifest.is_file():
                continue
            try:
                installation = _read_app_manifest(manifest, library, app_id)
            except (OSError, UnicodeError, VdfError) as exc:
                issues.append(SteamScanIssue(manifest, str(exc)))
                continue
            if installation.root.is_dir():
                found.append(installation)

        self._last_issues = tuple(issues)
        return tuple(found)

    def _read_library_roots(self) -> tuple[tuple[Path, ...], list[SteamScanIssue]]:
        libraries: list[Path] = []
        issues: list[SteamScanIssue] = []
        for steam_root in self._steam_roots:
            normalized_root = steam_root.expanduser().resolve(strict=False)
            if normalized_root.is_dir():
                libraries.append(normalized_root)
            library_file = normalized_root / "steamapps" / "libraryfolders.vdf"
            if not library_file.is_file():
                continue
            try:
                document = _read_vdf_file(library_file)
                libraries.extend(_library_paths_from_document(document))
            except (OSError, UnicodeError, VdfError) as exc:
                issues.append(SteamScanIssue(library_file, str(exc)))
        return _deduplicate_paths(libraries), issues


def discover_windows_steam_roots() -> tuple[Path, ...]:
    """Return existing Steam roots from environment, registry, and defaults."""

    candidates: list[Path] = []
    environment_path = os.environ.get("STEAM_PATH")
    if environment_path:
        candidates.append(Path(environment_path))

    try:
        import winreg
    except ImportError:
        winreg = None  # type: ignore[assignment]

    if winreg is not None:
        registry_locations = (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
        )
        for hive, key_name in registry_locations:
            try:
                with winreg.OpenKey(hive, key_name) as key:
                    for value_name in ("SteamPath", "InstallPath"):
                        try:
                            value, _ = winreg.QueryValueEx(key, value_name)
                        except OSError:
                            continue
                        if isinstance(value, str) and value.strip():
                            candidates.append(Path(value))
            except OSError:
                continue

    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "Steam")
    return tuple(path for path in _deduplicate_paths(candidates) if path.is_dir())


def parse_vdf(text: str) -> dict[str, Any]:
    """Parse the object subset used by Steam VDF and ACF files."""

    if not isinstance(text, str):
        raise TypeError("VDF input must be text")
    tokens = _tokenize_vdf(text)
    document = _parse_vdf_object(tokens, depth=0, expect_closing=False)
    try:
        extra = next(tokens)
    except StopIteration:
        return document
    raise VdfError(f"unexpected token after VDF document: {extra!r}")


def _read_vdf_file(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        raw = file.read(MAX_VDF_BYTES + 1)
    if len(raw) > MAX_VDF_BYTES:
        raise VdfError(f"Steam metadata file is too large: {path}")
    return parse_vdf(raw.decode("utf-8-sig"))


def _read_app_manifest(
    manifest_path: Path,
    library_root: Path,
    expected_app_id: str,
) -> SteamAppInstallation:
    document = _read_vdf_file(manifest_path)
    app_state = document.get("AppState")
    if not isinstance(app_state, Mapping):
        raise VdfError("Steam app manifest is missing AppState")
    app_id = _required_string(app_state, "appid")
    if app_id != expected_app_id:
        raise VdfError(
            f"Steam app manifest declares app {app_id}, expected {expected_app_id}"
        )
    install_dir = _required_string(app_state, "installdir")
    relative = Path(install_dir)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise VdfError("Steam installdir must be one safe directory name")

    common_root = (library_root / "steamapps" / "common").resolve(strict=False)
    game_root = (common_root / relative).resolve(strict=False)
    try:
        game_root.relative_to(common_root)
    except ValueError as exc:
        raise VdfError("Steam app installation escapes the common directory") from exc

    return SteamAppInstallation(
        app_id=app_id,
        name=_optional_string(app_state, "name") or install_dir,
        install_dir=install_dir,
        root=game_root,
        library_root=library_root.resolve(strict=False),
        manifest_path=manifest_path.resolve(strict=False),
        build_id=_optional_string(app_state, "buildid"),
        state_flags=_optional_string(app_state, "StateFlags"),
    )


def _library_paths_from_document(document: Mapping[str, Any]) -> tuple[Path, ...]:
    folders = document.get("libraryfolders")
    if not isinstance(folders, Mapping):
        raise VdfError("libraryfolders.vdf is missing the libraryfolders object")
    paths: list[Path] = []
    for value in folders.values():
        if isinstance(value, str):
            path_value = value
        elif isinstance(value, Mapping):
            candidate = value.get("path")
            path_value = candidate if isinstance(candidate, str) else ""
        else:
            continue
        if path_value.strip():
            candidate_path = Path(path_value).expanduser()
            if candidate_path.is_absolute():
                paths.append(candidate_path.resolve(strict=False))
    return tuple(paths)


def _required_string(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise VdfError(f"Steam metadata is missing {key}")
    return value


def _optional_string(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    return value if isinstance(value, str) and value else None


def _deduplicate_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        normalized = Path(path).expanduser().resolve(strict=False)
        key = os.path.normcase(os.path.normpath(str(normalized)))
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return tuple(result)


def _tokenize_vdf(text: str) -> Iterator[str]:
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character.isspace():
            index += 1
            continue
        if text.startswith("//", index):
            newline = text.find("\n", index + 2)
            index = length if newline < 0 else newline + 1
            continue
        if character in "{}":
            yield character
            index += 1
            continue
        if character == '"':
            index += 1
            value: list[str] = []
            while index < length:
                character = text[index]
                if character == '"':
                    index += 1
                    yield "".join(value)
                    break
                if character == "\\":
                    index += 1
                    if index >= length:
                        raise VdfError("unterminated VDF escape sequence")
                    escaped = text[index]
                    value.append({"n": "\n", "r": "\r", "t": "\t"}.get(escaped, escaped))
                    index += 1
                    continue
                value.append(character)
                index += 1
            else:
                raise VdfError("unterminated quoted VDF string")
            continue

        start = index
        while index < length and not text[index].isspace() and text[index] not in '{}"':
            index += 1
        if start == index:
            raise VdfError(f"unexpected VDF character at offset {index}")
        yield text[start:index]


def _parse_vdf_object(
    tokens: Iterator[str],
    *,
    depth: int,
    expect_closing: bool,
) -> dict[str, Any]:
    if depth > MAX_VDF_DEPTH:
        raise VdfError("VDF nesting exceeds the safety limit")
    result: dict[str, Any] = {}
    while True:
        try:
            token = next(tokens)
        except StopIteration:
            if expect_closing:
                raise VdfError("unterminated VDF object") from None
            return result
        if token == "}":
            if not expect_closing:
                raise VdfError("unexpected closing brace in VDF document")
            return result
        if token == "{":
            raise VdfError("VDF object is missing a key")
        key = token
        try:
            value = next(tokens)
        except StopIteration:
            raise VdfError(f"VDF key {key!r} is missing a value") from None
        if value == "{":
            result[key] = _parse_vdf_object(
                tokens,
                depth=depth + 1,
                expect_closing=True,
            )
        elif value == "}":
            raise VdfError(f"VDF key {key!r} is missing a value")
        else:
            result[key] = value


__all__ = [
    "SteamAppInstallation",
    "SteamInstallationLocator",
    "SteamScanIssue",
    "VdfError",
    "discover_windows_steam_roots",
    "parse_vdf",
]
