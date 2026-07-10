from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from .api import HostContext
from .errors import ModuleLoadError, PackageError
from .jsonio import read_json
from .models import ModuleMetadata


class ModuleLoader:
    def __init__(self, versions_dir: Path) -> None:
        self.versions_dir = versions_dir

    def create_application(self, version: str, context: HostContext) -> Any:
        root = (self.versions_dir / version).resolve()
        if self.versions_dir.resolve() not in root.parents or not root.is_dir():
            raise ModuleLoadError(f"Application module is not installed: {version}")
        try:
            metadata = ModuleMetadata.from_dict(read_json(root / "module.json"))
        except (OSError, ValueError, PackageError) as error:
            raise ModuleLoadError(f"Cannot read module metadata: {error}") from error
        if metadata.version != version:
            raise ModuleLoadError(
                f"State selects {version}, but module metadata declares {metadata.version}"
            )
        file_name, callable_name = metadata.entrypoint.rsplit(":", 1)
        entrypoint = (root / file_name).resolve()
        if root not in entrypoint.parents or not entrypoint.is_file():
            raise ModuleLoadError(f"Invalid module entrypoint: {file_name}")
        module = self._load_python_module(entrypoint, version, root)
        factory = getattr(module, callable_name, None)
        if not callable(factory):
            raise ModuleLoadError(f"Entrypoint callable not found: {callable_name}")
        try:
            application = factory(context)
        except Exception as error:
            raise ModuleLoadError(f"Application initialization failed: {error}") from error
        if not callable(getattr(application, "run", None)):
            raise ModuleLoadError("Application factory must return an object with run()")
        return application

    @staticmethod
    def _load_python_module(entrypoint: Path, version: str, root: Path) -> ModuleType:
        package_name = f"_signriver_app_{version.replace('.', '_').replace('-', '_')}"
        relative_entrypoint = entrypoint.relative_to(root)
        if entrypoint.suffix != ".py":
            raise ModuleLoadError("Application entrypoint must be a Python file")
        module_parts = relative_entrypoint.with_suffix("").parts
        module_name = ".".join((package_name, *module_parts))

        package = ModuleType(package_name)
        package.__package__ = package_name
        package.__path__ = [str(root)]  # type: ignore[attr-defined]
        sys.modules[package_name] = package
        parent_path = root
        for index, part in enumerate(module_parts[:-1], start=1):
            parent_path /= part
            parent_name = ".".join((package_name, *module_parts[:index]))
            parent = ModuleType(parent_name)
            parent.__package__ = parent_name
            parent.__path__ = [str(parent_path)]  # type: ignore[attr-defined]
            sys.modules[parent_name] = parent

        spec = importlib.util.spec_from_file_location(module_name, entrypoint)
        if spec is None or spec.loader is None:
            raise ModuleLoadError(f"Unable to create module spec for {entrypoint}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as error:
            for loaded_name in tuple(sys.modules):
                if loaded_name == package_name or loaded_name.startswith(f"{package_name}."):
                    sys.modules.pop(loaded_name, None)
            raise ModuleLoadError(f"Unable to import application module: {error}") from error
        return module
