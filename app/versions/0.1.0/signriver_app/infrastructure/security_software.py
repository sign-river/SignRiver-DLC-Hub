"""Read-only Windows security-product discovery for the diagnostics UI."""
from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SecurityProduct:
    name: str
    executable: Path | None = None


def is_lenovo_security_product(product: SecurityProduct | str) -> bool:
    """Whether the Security Center product is Lenovo PC Manager's AV module."""
    name = product.name if isinstance(product, SecurityProduct) else str(product)
    normalized = " ".join(name.casefold().split())
    return "lenovo" in normalized and ("anti-virus" in normalized or "anti virus" in normalized or "huorong" in normalized)


def is_windows_security_product(product: SecurityProduct | str) -> bool:
    """Whether a product may safely use the fixed Windows Security URI fallback."""
    name = product.name if isinstance(product, SecurityProduct) else str(product)
    normalized = " ".join(name.casefold().split())
    return any(token in normalized for token in (
        "windows defender", "microsoft defender", "windows security",
    ))


def _uninstall_entries() -> tuple[dict[str, str], ...]:
    """Read only the uninstall metadata needed to locate Lenovo PC Manager."""
    try:
        import winreg
    except ImportError:
        return ()
    entries: list[dict[str, str]] = []
    roots = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    for root in roots:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root) as uninstall_root:
                count = winreg.QueryInfoKey(uninstall_root)[0]
                for index in range(count):
                    try:
                        subkey_name = winreg.EnumKey(uninstall_root, index)
                        with winreg.OpenKey(uninstall_root, subkey_name) as subkey:
                            display_name = str(winreg.QueryValueEx(subkey, "DisplayName")[0])
                            display_icon = str(winreg.QueryValueEx(subkey, "DisplayIcon")[0])
                    except OSError:
                        continue
                    try:
                        install_location = str(winreg.QueryValueEx(subkey, "InstallLocation")[0])
                    except OSError:
                        install_location = ""
                    entries.append({
                        "display_name": display_name,
                        "display_icon": display_icon,
                        "install_location": install_location,
                    })
        except OSError:
            continue
    return tuple(entries)


def _display_icon_executable(value: str) -> Path | None:
    candidate = value.strip()
    if not candidate:
        return None
    candidate = candidate.split(",", 1)[0].strip().strip('"')
    path = Path(candidate)
    return path if path.name.casefold() == "lenovopcmanager.exe" else None


def find_lenovo_pc_manager_executable(
    entries: Iterable[Mapping[str, str]] | None = None,
) -> Path | None:
    """Return the verified Lenovo PC Manager launcher, never its AV submodule."""
    for entry in entries if entries is not None else _uninstall_entries():
        name = str(entry.get("display_name") or "").casefold()
        if not (("lenovo" in name or "联想" in name) and ("pcmanager" in name or "pc manager" in name or "电脑管家" in name)):
            continue
        candidates = [_display_icon_executable(str(entry.get("display_icon") or ""))]
        install_location = str(entry.get("install_location") or "").strip()
        if install_location:
            candidates.append(Path(install_location) / "LenovoPcManager.exe")
        for candidate in candidates:
            if candidate is not None and candidate.is_file():
                return candidate
    return None


def preferred_security_product_executable(product: SecurityProduct) -> Path | None:
    """Choose a product-management UI over a lower-level security module."""
    if is_lenovo_security_product(product):
        return find_lenovo_pc_manager_executable()
    return product.executable


_POWER_SHELL = (
    "Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct "
    "| Select-Object displayName,pathToSignedProductExe "
    "| ConvertTo-Json -Compress"
)


def discover_security_products(*, runner=subprocess.run) -> tuple[SecurityProduct, ...]:
    """Return Security Center products without changing their configuration."""
    try:
        completed = runner(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _POWER_SHELL],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if completed.returncode != 0 or not completed.stdout.strip():
        return ()
    try:
        decoded = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ()
    items = decoded if isinstance(decoded, list) else [decoded]
    products: list[SecurityProduct] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("displayName") or "").strip()
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        raw_path = str(item.get("pathToSignedProductExe") or "").strip()
        executable = Path(raw_path) if raw_path and Path(raw_path).is_absolute() else None
        products.append(SecurityProduct(name=name, executable=executable))
    return tuple(products)


__all__ = [
    "SecurityProduct",
    "discover_security_products",
    "find_lenovo_pc_manager_executable",
    "is_lenovo_security_product",
    "is_windows_security_product",
    "preferred_security_product_executable",
]
