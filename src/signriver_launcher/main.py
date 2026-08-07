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
from .jsonio import read_json
from .models import ModuleMetadata
from .paths import RuntimePaths
from .state import StateStore
from .updater import UpdateClient
from .versioning import Version
from .full_update import FullUpdateManager
from .full_update_helper import apply_full_update


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

        messagebox.showerror("唏嘘南溪DLC一键解锁工具", message)
    except Exception:
        print(message, file=sys.stderr)


def _activate_confirmed_full_update_module(
    paths: RuntimePaths,
    store: StateStore,
    transaction_id: str,
) -> None:
    """Activate a full-update module even when the swap used an older helper."""
    transaction = FullUpdateManager(paths).load()
    if (
        transaction is None
        or transaction.transaction_id != transaction_id
        or transaction.stage != "swapped"
    ):
        return
    module_root = paths.versions_dir / transaction.version
    metadata = ModuleMetadata.from_dict(read_json(module_root / "module.json"))
    entrypoint = metadata.entrypoint.rsplit(":", 1)[0]
    if metadata.version != transaction.version or not (
        module_root / entrypoint
    ).is_file():
        raise ModuleLoadError(
            "full update target module metadata does not match the transaction"
        )
    store.activate(transaction.version)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--apply-full-update":
        if len(argv) != 4:
            return 2
        apply_full_update(Path(argv[1]), argv[2], int(argv[3]))
        return 0
    confirm_transaction = None
    if argv and argv[0] == "--confirm-full-update":
        if len(argv) != 2:
            return 2
        confirm_transaction = argv[1]
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
        full_update_manager = FullUpdateManager(paths)
        full_update_manager.recover_pending()
        if confirm_transaction:
            try:
                _activate_confirmed_full_update_module(
                    paths, store, confirm_transaction
                )
            except (OSError, ValueError, SignRiverError):
                full_update_manager.rollback(confirm_transaction)
                raise
        settings = UpdateSettings.load(
            paths.update_config_file,
            defaults_path=paths.update_defaults_config_file,
            user_path=paths.user_update_config_file,
        )
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
            if confirm_transaction:
                FullUpdateManager(paths).confirm(confirm_transaction)
        except ModuleLoadError:
            if confirm_transaction:
                FullUpdateManager(paths).rollback(confirm_transaction)
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
