from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .api import HostContext
from .config import UpdateSettings
from .errors import ConfigurationError, ModuleLoadError, SignRiverError
from .loader import ModuleLoader
from .paths import RuntimePaths
from .state import StateStore
from .updater import UpdateClient
from .versioning import Version


def _configure_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("signriver")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    file_handler = RotatingFileHandler(
        log_dir / "launcher.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    if not getattr(sys, "frozen", False):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)
    return logger


def _bootstrap_state(paths: RuntimePaths, store: StateStore) -> None:
    if paths.state_file.exists():
        return
    installed: list[tuple[Version, str]] = []
    for directory in paths.versions_dir.iterdir():
        if not directory.is_dir():
            continue
        try:
            installed.append((Version.parse(directory.name), directory.name))
        except ValueError:
            continue
    if not installed:
        raise ConfigurationError("No application module is installed")
    store.bootstrap(max(installed)[1])


def _show_fatal_error(message: str) -> None:
    try:
        from tkinter import messagebox

        messagebox.showerror("唏嘘南溪DLC一键解锁", message)
    except Exception:
        print(message, file=sys.stderr)


def main() -> int:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "SignRiver.DLCHub.1"
            )
        except Exception:
            pass
    paths = RuntimePaths.discover()
    paths.ensure()
    logger = _configure_logging(paths.log_dir)
    store = StateStore(paths.state_file)
    try:
        _bootstrap_state(paths, store)
        settings = UpdateSettings.load(paths.update_config_file)
        updater = UpdateClient(paths, settings, store)
        loader = ModuleLoader(paths.versions_dir)

        state = store.load()
        try:
            context = HostContext.create(
                state.active_version,
                paths.root,
                paths.data_dir,
                paths.cache_dir,
                updater,
                logger,
            )
            application = loader.create_application(state.active_version, context)
            store.mark_healthy(state.active_version)
        except ModuleLoadError:
            if state.pending_version != state.active_version:
                raise
            logger.exception("New module failed during initialization; rolling back")
            state = store.rollback_pending(state.active_version)
            context = HostContext.create(
                state.active_version,
                paths.root,
                paths.data_dir,
                paths.cache_dir,
                updater,
                logger,
            )
            application = loader.create_application(state.active_version, context)

        logger.info("Starting application module %s", state.active_version)
        application.run()
        return 0
    except (SignRiverError, OSError, ValueError) as error:
        logger.error("Fatal launcher error: %s\n%s", error, traceback.format_exc())
        _show_fatal_error(str(error))
        return 1
