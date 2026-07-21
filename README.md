# SignRiver DLC Hub

SignRiver DLC Hub 是一个面向多款游戏的桌面 DLC 管理器。目前项目首先实现了可独立演进的模块化更新框架。出厂卡带目前覆盖群星、文明 6、钢铁雄心 4、城市天际线与边缘世界；完整列表以 `config/cartridges/cartridges_index.json` 为准。

## 核心设计

发布包中的启动器 EXE（发行名为「唏嘘南溪DLC一键解锁工具.exe」）是稳定宿主；真正的界面和业务代码位于 `app/versions/<version>/`。常规更新会下载一个模块包，校验 SHA-256 后解压到新的版本目录，再通过原子写入 `app/state.json` 切换版本。旧版本会保留，以便新模块启动失败时自动回滚。

```text
唏嘘南溪DLC一键解锁工具/
├── 唏嘘南溪DLC一键解锁工具.exe
├── app/
│   ├── state.json
│   └── versions/
│       └── 0.1.0/
│           ├── module.json
│           └── app_entry.py
├── config/
│   ├── update.json
│   ├── announcement.json        # 出厂公告（可被远程 hub 覆盖）
│   └── cartridges/              # 出厂游戏主表与默认卡带
├── cache/
└── data/
```

更完整的协议和发布流程见 [docs/update-architecture.md](docs/update-architecture.md)。

## 客户端主要功能

游戏列表不再写死在客户端代码中。启动时先读取 `config/cartridges` 出厂主表（并可联网刷新 GitLink / GitHub 的 `hub` Release），加载默认游戏卡带；切换到其他游戏时再按需下载对应卡带。启动公告同样来自 `hub` Release 的 `announcement.json`（本地出厂文件为 `config/announcement.json`）；设置页可开关“下次公告更新前不再显示”，也可在 GitLink 与 GitHub 之间切换下载源，两边保持相同的 Release 标签与资源文件名。

DLC 库页面提供“一键解锁 / 一键修复 / 一键移除补丁 / 恢复游戏原版”等核心操作：

- **一键解锁**：先审计并按需下载 `steam_api64.dll`、`steam_api64_o.dll`、`<game>_appinfo.json`，事务化替换补丁并原子写入 `cream_api.ini`，再依次下载并安装勾选的 DLC。已健康的补丁会被跳过。
- **一键修复**：在弹窗确认后清空全部 DLC、下载缓存与补丁三件套，然后重新执行一键解锁，用于处理残缺文件或异常补丁。
- **一键移除补丁**：反向操作，删除补丁 DLL 与 `cream_api.ini`，并把 `steam_api64_o.dll` 还原为 `steam_api64.dll`。
- **恢复游戏原版**：先检查游戏进程、下载任务与原版 DLL 备份，再选择“仅撤销本程序安装”或“移除检测到的全部 DLC”；缓存默认保留，也可在确认时一并清理。

设置页的“超时控制”可启用“关闭超时检测”。默认保持关闭；仅在网络会长时间停顿、但之后能够自行恢复的挂机下载场景中建议开启。开启后若连接完全卡住，暂停或取消可能需要等待网络恢复后才会生效。

补丁安装、`cream_api.ini` 生成规则与四种审计状态见 [docs/publisher-guide.md#补丁数据与客户端流程](docs/publisher-guide.md)；总体架构与进度见 [docs/application-implementation-plan.md](docs/application-implementation-plan.md)。

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

`build_release.py` 生成首次发布用的完整包：外层优先产出中文名自解压 EXE（需本机安装带 `7z.sfx` 的 7-Zip），并同时生成中文名 ZIP；解压后的文件夹与启动 EXE 均为「唏嘘南溪DLC一键解锁工具」。`build_module.py` 生成后续小版本使用的模块更新包和清单片段。程序通过 `sys.executable` 定位安装目录，支持含中文的安装路径。
