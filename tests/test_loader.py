import json

from signriver_launcher.api import HostContext
from signriver_launcher.config import UpdateSettings
from signriver_launcher.loader import ModuleLoader
from signriver_launcher.paths import RuntimePaths
from signriver_launcher.state import StateStore
from signriver_launcher.updater import UpdateClient


def test_loads_external_application_and_supports_lazy_import(tmp_path) -> None:
    version_root = tmp_path / "app" / "versions" / "0.1.0"
    version_root.mkdir(parents=True)
    (version_root / "module.json").write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "api_version": 1,
                "entrypoint": "entry.py:create_application",
            }
        ),
        encoding="utf-8",
    )
    (version_root / "helper.py").write_text("VALUE = 42\n", encoding="utf-8")
    (version_root / "entry.py").write_text(
        "from . import helper\n"
        "class App:\n"
        "    def run(self):\n"
        "        self.value = helper.VALUE\n"
        "def create_application(context):\n"
        "    return App()\n",
        encoding="utf-8",
    )
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    store = StateStore(paths.state_file)
    store.bootstrap("0.1.0")
    updater = UpdateClient(paths, UpdateSettings(), store)
    context = HostContext.create(
        "0.1.0", paths.root, paths.data_dir, paths.cache_dir, updater, __import__("logging").getLogger()
    )

    app = ModuleLoader(paths.versions_dir).create_application("0.1.0", context)
    app.run()
    assert app.value == 42
