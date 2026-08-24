"""Read-only Windows security-product discovery for the diagnostics UI."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SecurityProduct:
    name: str
    executable: Path | None = None


def is_windows_security_product(product: SecurityProduct | str) -> bool:
    """Whether a product may safely use the fixed Windows Security URI fallback."""
    name = product.name if isinstance(product, SecurityProduct) else str(product)
    normalized = " ".join(name.casefold().split())
    return any(token in normalized for token in (
        "windows defender", "microsoft defender", "windows security",
    ))


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


__all__ = ["SecurityProduct", "discover_security_products", "is_windows_security_product"]
