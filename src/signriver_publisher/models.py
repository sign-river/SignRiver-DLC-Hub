from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from pathlib import PurePosixPath


def _validate_interference_files(value: object, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} 必须是数组")
    result: list[str] = []
    for item in value:
        raw = str(item).strip().replace("\\", "/")
        path = PurePosixPath(raw)
        if (
            not raw or "\x00" in raw or path.is_absolute() or ".." in path.parts
            or any(char in raw for char in "*?[]")
            or any(":" in part or part in {"", "."} for part in path.parts)
        ):
            raise ValueError(f"{field_name} 包含不安全的显式相对文件路径：{item!r}")
        result.append(path.as_posix())
    if len({item.casefold() for item in result}) != len(result):
        raise ValueError(f"{field_name} 不得包含重复路径")
    return tuple(result)


BUILTIN_PATCH_PLATFORMS: dict[str, dict[str, dict[str, object]]] = {
    "stellaris": {
        "steamos": {
            "executable_relative_path": "stellaris", "dlc_relative_dir": "dlc",
            "unlocker_dll_name": "libsteam_api.so",
            "runtime_original_library_name": "libsteam_api_o.so",
            "ini_target_name": "SmokeAPI.config.json", "config_format": "smokeapi_json",
        },
        "macos": {
            "executable_relative_path": "stellaris.app/Contents/MacOS/stellaris",
            "dlc_relative_dir": "dlc", "install_relative_dir": "stellaris.app/Contents/MacOS",
            "unlocker_dll_name": "libsteam_api.dylib",
            "runtime_original_library_name": "libsteam_api_o.dylib",
            "ini_target_name": "icecream.ini", "config_format": "cream_ini",
        },
    },
    "civilization_6": {
        "steamos": {
            "executable_relative_path": "Civ6", "dlc_relative_dir": "DLC",
            "install_relative_dir": ".", "unlocker_dll_name": "libsteam_api.so",
            "runtime_original_library_name": "libsteam_api_o.so",
            "ini_target_name": "SmokeAPI.config.json", "config_format": "smokeapi_json",
        },
        "macos": {
            "executable_relative_path": "Civilization VI.app/Contents/MacOS/Civilization VI",
            "dlc_relative_dir": "DLC", "install_relative_dir": "Civilization VI.app/Contents/MacOS",
            "unlocker_dll_name": "libsteam_api.dylib",
            "runtime_original_library_name": "libsteam_api_o.dylib",
            "ini_target_name": "icecream.ini", "config_format": "cream_ini",
        },
    },
    "hearts_of_iron_4": {
        "steamos": {
            "executable_relative_path": "hoi4", "dlc_relative_dir": "dlc",
            "unlocker_dll_name": "libsteam_api.so",
            "runtime_original_library_name": "libsteam_api_o.so",
            "ini_target_name": "SmokeAPI.config.json", "config_format": "smokeapi_json",
        },
        "macos": {
            "executable_relative_path": "hoi4.app/Contents/MacOS/hoi4",
            "dlc_relative_dir": "dlc", "install_relative_dir": "hoi4.app/Contents/MacOS",
            "unlocker_dll_name": "libsteam_api.dylib",
            "runtime_original_library_name": "libsteam_api_o.dylib",
            "ini_target_name": "icecream.ini", "config_format": "cream_ini",
        },
    },
    "cities_skylines": {
        "steamos": {
            "executable_relative_path": "Cities.x64", "dlc_relative_dir": "Files",
            "unlocker_dll_name": "libsteam_api.so",
            "runtime_original_library_name": "libsteam_api_o.so",
            "ini_target_name": "SmokeAPI.config.json", "config_format": "smokeapi_json",
        },
        "macos": {
            "executable_relative_path": "Cities.app/Contents/MacOS/Cities",
            "dlc_relative_dir": "Files", "install_relative_dir": "Cities.app/Contents/Plugins",
            "unlocker_dll_name": "libsteam_api.dylib",
            "runtime_original_library_name": "libsteam_api_o.dylib",
            "ini_target_name": "icecream.ini", "config_format": "cream_ini",
        },
    },
    "rimworld": {
        "steamos": {
            "executable_relative_path": "RimWorldLinux", "dlc_relative_dir": "Data",
            "install_relative_dir": "RimWorldLinux_Data/Plugins/x86_64",
            "unlocker_dll_name": "libsteam_api.so",
            "runtime_original_library_name": "libsteam_api_o.so",
            "ini_target_name": "SmokeAPI.config.json", "config_format": "smokeapi_json",
        },
        "macos": {
            "executable_relative_path": "RimWorldMac.app/Contents/MacOS/RimWorldMac",
            "dlc_relative_dir": "Data", "install_relative_dir": "RimWorldMac.app/Contents/Plugins",
            "unlocker_dll_name": "libsteam_api.dylib",
            "runtime_original_library_name": "libsteam_api_o.dylib",
            "ini_target_name": "icecream.ini", "config_format": "cream_ini",
        },
    },
}


@dataclass(frozen=True, slots=True)
class PublisherCartridge:
    """One server-side game cartridge and its complete release contract."""

    game_id: str
    display_name: str
    release_tag: str
    appinfo_name: str
    steam_app_id: str = ""
    patch_unlocker_name: str = "steam_api64.dll"
    patch_runtime_original_name: str = "steam_api64_o.dll"
    dlc_relative_dir: str = "dlc"
    patch_relative_dir: str = "."
    dlc_archive_root_mode: str = "source"
    dlc_import_naming_mode: str = "manual_prefixed"
    dlc_import_layout_mode: str = "single_directory"
    # For games where one logical DLC is spread across several parallel
    # directory branches. Each value is relative to ``dlc_relative_dir`` and
    # contains category directories whose immediate children are DLC names.
    dlc_group_search_roots: tuple[str, ...] = ()
    # Client-facing fields exported into the remote hub cartridge documents.
    executable_relative_path: str = ""
    package_inspector: str = "directory"
    install_directory_from_slug: bool = False
    ini_target_name: str = "cream_api.ini"
    patch_language: str = "schinese"
    patch_unlock_all: bool = True
    patch_extra_protection: bool = False
    patch_force_offline: bool = False
    patch_platforms: dict[str, dict[str, object]] = field(default_factory=dict)
    # Exact cloud availability explicitly confirmed by the publisher.  This is
    # intentionally separate from ``patch_platforms``: a platform may have a
    # cartridge variant while its patch files have not been uploaded yet.
    # ``None`` keeps old profiles compatible and lets the workspace derive the
    # conservative Windows-only state from a completed remote publish record.
    published_platform_resources: dict[str, dict[str, bool]] | None = None
    # ``built_in`` means the game ships DLC payloads with its base install;
    # publishing only supplies the unlock patch and AppInfo metadata.
    dlc_delivery_mode: str = "download_packages"
    # Additional game-relative directories that require the same complete
    # proxy-library patch transaction as ``patch_relative_dir``.
    patch_additional_relative_dirs: tuple[str, ...] = ()
    patch_interference_files: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "patch_interference_files",
            _validate_interference_files(
                self.patch_interference_files,
                field_name="patch_interference_files",
            ),
        )
        if not self.patch_platforms and self.game_id in BUILTIN_PATCH_PLATFORMS:
            object.__setattr__(
                self,
                "patch_platforms",
                {
                    platform: dict(spec)
                    for platform, spec in BUILTIN_PATCH_PLATFORMS[self.game_id].items()
                },
            )

    @classmethod
    def create(cls, game_id: str, display_name: str, steam_app_id: str = "") -> "PublisherCartridge":
        """Create a cartridge using the shared release naming convention."""
        return cls(game_id, display_name, game_id, f"{game_id}_appinfo.json", steam_app_id)

    @property
    def patch_asset_names(self) -> tuple[str, ...]:
        """Stable release-side names; cartridges map them to game filenames."""
        return ("unlocker.dll", "original.dll")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["dlc_group_search_roots"] = list(self.dlc_group_search_roots)
        payload["patch_additional_relative_dirs"] = list(
            self.patch_additional_relative_dirs
        )
        payload["patch_interference_files"] = list(self.patch_interference_files)
        return payload

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "PublisherCartridge":
        game_id = str(value["game_id"])
        raw_patch_platforms = value.get("patch_platforms")
        patch_platforms = (
            {
                str(platform): dict(spec)
                for platform, spec in raw_patch_platforms.items()
                if isinstance(spec, dict)
            }
            if isinstance(raw_patch_platforms, dict)
            else {
                platform: dict(spec)
                for platform, spec in BUILTIN_PATCH_PLATFORMS.get(game_id, {}).items()
            }
        )
        for spec in patch_platforms.values():
            if "runtime_original_library_name" not in spec and spec.get("original_backup_dll_name"):
                spec["runtime_original_library_name"] = spec.pop("original_backup_dll_name")
            spec["interference_files"] = list(
                _validate_interference_files(
                    spec.get("interference_files"),
                    field_name="patch_platforms.interference_files",
                )
            )

        raw_resources = value.get("published_platform_resources")
        published_platform_resources: dict[str, dict[str, bool]] | None = None
        if raw_resources is not None:
            if isinstance(raw_resources, str):
                raw_resources = raw_resources.strip()
                if not raw_resources:
                    raw_resources = None
                else:
                    import json
                    try:
                        raw_resources = json.loads(raw_resources)
                    except json.JSONDecodeError as error:
                        raise ValueError("已发布平台资源必须是 JSON 对象") from error
            if raw_resources is None:
                pass
            elif not isinstance(raw_resources, dict):
                raise ValueError("已发布平台资源必须是 JSON 对象")
            else:
                published_platform_resources = {
                    str(platform).strip().lower().split("-", 1)[0]: {
                        "patch": bool(spec.get("patch")),
                        "dlc": bool(spec.get("dlc")),
                    }
                    for platform, spec in raw_resources.items()
                    if isinstance(spec, dict) and str(platform).strip()
                }
        raw_group_roots = value.get("dlc_group_search_roots", ())
        group_roots = tuple(
            str(item).strip() for item in raw_group_roots if str(item).strip()
        ) if isinstance(raw_group_roots, (list, tuple)) else tuple(
            item.strip() for item in str(raw_group_roots or "").split(";") if item.strip()
        )
        if game_id == "age_of_wonders_4" and not group_roots:
            group_roots = (".",)

        auto_prefix_games = {
            "civilization_6", "cities_skylines", "rimworld",
            "workers_resources_soviet_republic", "civilization_7",
            "age_of_wonders_4",
        }
        legacy_steam_ids = {
            "stellaris": "281990",
            "civilization_6": "289070",
            "hearts_of_iron_4": "394360",
            "cities_skylines": "255710",
            "rimworld": "294100",
            "crusader_kings_3": "1158310",
            "victoria_3": "529340",
            "workers_resources_soviet_republic": "784150",
            "civilization_7": "1295660",
            "age_of_wonders_4": "1669000",
        }
        builtin_naming_modes = {gid: "auto_prefix" for gid in auto_prefix_games}
        builtin_layout_modes = {gid: "children_if_root" for gid in auto_prefix_games}
        builtin_archive_modes = {gid: "strip_id_prefix" for gid in auto_prefix_games}
        builtin_dlc_dirs = {
            "civilization_6": "DLC",
            "cities_skylines": "Files",
            "rimworld": "Data",
            "crusader_kings_3": "game/dlc",
            "victoria_3": "game/dlc",
            "workers_resources_soviet_republic": "media_soviet",
            "civilization_7": "DLC",
            "age_of_wonders_4": "Launcher/dlc",
        }
        builtin_patch_dirs = {
            "civilization_6": "Base/Binaries/Win64Steam",
            "rimworld": "RimWorldWin64_Data/Plugins/x86_64",
            "crusader_kings_3": "binaries",
            "victoria_3": "binaries",
            "civilization_7": "Base/Binaries/Win64",
        }
        builtin_executables = {
            "stellaris": "stellaris.exe",
            "civilization_6": "Base/Binaries/Win64Steam/CivilizationVI.exe",
            "hearts_of_iron_4": "hoi4.exe",
            "cities_skylines": "Cities.exe",
            "rimworld": "RimWorldWin64.exe",
            "crusader_kings_3": "binaries/ck3.exe",
            "victoria_3": "binaries/victoria3.exe",
            "workers_resources_soviet_republic": "SOVIET64.exe",
            "civilization_7": "Base/Binaries/Win64/Civ7_Win64_DX12_FinalRelease.exe",
            "age_of_wonders_4": "AOW4.exe",
        }
        return cls(
            game_id=game_id,
            display_name=str(value["display_name"]),
            release_tag=str(value["release_tag"]),
            appinfo_name=str(value.get("appinfo_name") or f"{game_id}_appinfo.json"),
            steam_app_id=str(value.get("steam_app_id") or legacy_steam_ids.get(game_id, "")),
            patch_unlocker_name=str(value.get("patch_unlocker_name") or "steam_api64.dll"),
            patch_runtime_original_name=str(
                value.get("patch_runtime_original_name")
                or value.get("patch_original_backup_name")
                or "steam_api64_o.dll"
            ),
            dlc_relative_dir=str(
                value.get("dlc_relative_dir") or builtin_dlc_dirs.get(game_id, "dlc")
            ),
            dlc_delivery_mode=str(
                value.get("dlc_delivery_mode") or "download_packages"
            ),
            patch_relative_dir=str(
                value.get("patch_relative_dir") or builtin_patch_dirs.get(game_id, ".")
            ),
            patch_additional_relative_dirs=tuple(
                str(item).strip()
                for item in value.get("patch_additional_relative_dirs", ())
                if str(item).strip()
            ) if isinstance(value.get("patch_additional_relative_dirs", ()), (list, tuple)) else tuple(
                item.strip()
                for item in str(value.get("patch_additional_relative_dirs") or "").split(";")
                if item.strip()
            ),
            patch_interference_files=_validate_interference_files(
                value.get("patch_interference_files"),
                field_name="patch_interference_files",
            ),
            dlc_archive_root_mode=str(
                value.get("dlc_archive_root_mode")
                or ("source" if game_id == "age_of_wonders_4" else builtin_archive_modes.get(game_id, "source"))
            ),
            dlc_import_naming_mode=str(
                value.get("dlc_import_naming_mode")
                or builtin_naming_modes.get(game_id, "manual_prefixed")
            ),
            dlc_import_layout_mode=str(
                value.get("dlc_import_layout_mode")
                or ("shared_file_pairs" if game_id == "age_of_wonders_4" else builtin_layout_modes.get(game_id, "single_directory"))
            ),
            dlc_group_search_roots=group_roots,
            executable_relative_path=str(
                value.get("executable_relative_path")
                or builtin_executables.get(game_id, "")
            ),
            package_inspector=str(
                value.get("package_inspector")
                or ("grouped_directory" if game_id == "age_of_wonders_4" else "directory")
            ),
            install_directory_from_slug=bool(
                value.get(
                    "install_directory_from_slug",
                    False if game_id == "age_of_wonders_4" else game_id in auto_prefix_games,
                )
            ),
            ini_target_name=str(value.get("ini_target_name") or "cream_api.ini"),
            patch_language=str(value.get("patch_language") or "schinese"),
            patch_unlock_all=bool(value.get("patch_unlock_all", True)),
            patch_extra_protection=bool(value.get("patch_extra_protection", False)),
            patch_force_offline=bool(value.get("patch_force_offline", False)),
            patch_platforms=patch_platforms,
            published_platform_resources=published_platform_resources,
        )


# Backwards-compatible import name for older modules. New server code and
# documentation use PublisherCartridge to match the client cartridge model.
GameProfile = PublisherCartridge


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    kind: str
    resource_id: str
    display_name: str
    asset_name: str
    source_path: Path
    output_path: Path
    size_bytes: int
    sha256: str

    def manifest_dict(self) -> dict[str, object]:
        return {
            "id": self.resource_id,
            "name": self.display_name,
            "asset_name": self.asset_name,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class PublishAsset:
    path: Path
    name: str
    size_bytes: int
    sha256: str
