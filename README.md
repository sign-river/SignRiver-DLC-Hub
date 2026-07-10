# SignRiver DLC Hub

SignRiver DLC Hub 是一个面向多款游戏的桌面 DLC 管理器。目前项目首先实现了可独立演进的模块化更新框架。

## 核心设计

发布包中的 `SignRiver-DLC-Hub.exe` 是稳定启动器；真正的界面和业务代码位于 `app/versions/<version>/`。常规更新会下载一个模块包，校验 SHA-256 后解压到新的版本目录，再通过原子写入 `app/state.json` 切换版本。旧版本会保留，以便新模块启动失败时自动回滚。

```text
SignRiver-DLC-Hub/
├── SignRiver-DLC-Hub.exe
├── app/
│   ├── state.json
│   └── versions/
│       └── 0.1.0/
│           ├── module.json
│           └── app_entry.py
├── config/
│   └── update.json
├── cache/
└── data/
```

更完整的协议和发布流程见 [docs/update-architecture.md](docs/update-architecture.md)。

## 本地开发

需要 Python 3.11 或更高版本。

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/python launcher.py
```

Linux/macOS 将 `.venv/Scripts/` 替换为 `.venv/bin/`。

## 测试

```bash
python -m pytest
```

## 构建

```bash
python tools/build_release.py
python tools/build_module.py app/versions/0.1.0
```

`build_release.py` 生成首次发布用的完整压缩包；`build_module.py` 生成后续小版本使用的模块更新包和清单片段。
