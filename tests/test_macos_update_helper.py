from pathlib import Path
from types import SimpleNamespace

from signriver_common.platforms import HostPlatform
from signriver_launcher.config import UpdateSettings
from signriver_launcher.models import ReleaseInfo
from signriver_launcher.paths import RuntimePaths
from signriver_launcher.state import StateStore
from signriver_launcher.updater import UpdateClient
import signriver_launcher.updater as updater_module


def test_frozen_macos_helper_receives_app_bundle_as_install_root(
    tmp_path: Path, monkeypatch
) -> None:
    bundle = tmp_path / "SignRiver-DLC-Hub.app"
    runtime = bundle / "Contents" / "Resources" / "runtime"
    runtime.mkdir(parents=True)
    paths = RuntimePaths(
        tmp_path / "state", bundle, HostPlatform.MACOS, tmp_path / "cache"
    )
    paths.ensure()
    store = StateStore(paths.state_file)
    store.bootstrap("0.1.7")
    client = UpdateClient(
        paths, UpdateSettings(), store, host_package_key="macos-x64"
    )

    staging = tmp_path / "staging"
    staged_launcher = (
        staging
        / bundle.name
        / "Contents"
        / "MacOS"
        / "SignRiver-DLC-Hub"
    )
    staged_launcher.parent.mkdir(parents=True)
    staged_launcher.write_bytes(b"new launcher")
    transaction = SimpleNamespace(
        staging_path=str(staging),
        transaction_id="transaction-id",
        bundle_path=bundle.name,
    )
    release = ReleaseInfo(
        "0.2.0", "full", "https://example.test/full.zip", "a" * 64, 1, "0.1.2"
    )
    calls = []
    monkeypatch.setattr(
        client, "prepare_full_update", lambda *_args, **_kwargs: transaction
    )
    monkeypatch.setattr(updater_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        updater_module.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    client.start_full_update(release)

    command = calls[0][0]
    assert command[5] == str(bundle)
    assert command[5] != str(runtime)
    assert command[6] == "macos"
    assert Path(command[0]).read_bytes() == b"new launcher"
