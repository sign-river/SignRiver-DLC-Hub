# SignRiver DLC Hub

**多游戏 DLC 一键解锁工具** —— 云端下载 · 原生补丁 · 操作可还原

[![GitHub release](https://img.shields.io/github/v/release/sign-river/SignRiver-DLC-Hub)](https://github.com/sign-river/SignRiver-DLC-Hub/releases)
[![Platform](https://img.shields.io/badge/%E5%B9%B3%E5%8F%B0-Windows%20%7C%20SteamOS%20%7C%20macOS-blue)](#支持平台与游戏)
[![QQ%E7%BE%A4](https://img.shields.io/badge/QQ%E7%BE%A4-1061299021-blue)](https://qm.qq.com/q/NQRer2RHmC)

> 开源免费 · 如付费获得请立即退款

## 支持平台与游戏

| 平台 | 发行形式 | 可写数据目录 |
| --- | --- | --- |
| Windows x64 | 便携 ZIP / 自解压 EXE | 程序目录下的 `app/`、`data/`、`cache/` |
| SteamOS x64 | 便携 `tar.gz` | `~/.local/share/signriver-dlc-hub` |
| macOS Intel x64 | ad-hoc 签名的 `.app.zip` | `~/Library/Application Support/SignRiver DLC Hub` |

- **三端通用**：群星 Stellaris
- **Windows + macOS**：都市天际线 Cities: Skylines
- **仅 Windows**：文明 6、钢铁雄心 4、边缘世界、十字军之王 3、维多利亚 3、工人与资源：苏维埃共和国、奇迹时代 4、都市天际线 2、文明 7

SteamOS 与 macOS 的测试环境由虚拟机搭建，目前提供群星与核心功能（解锁、补丁、报错指南等）；游戏列表由云端卡带主表驱动，实际可用范围以程序内显示为准，出厂兜底表见 `config/cartridges/cartridges_index.json`。

## 核心设计

Windows 发布包中的启动器 EXE（发行名为「唏嘘南溪DLC一键解锁工具.exe」）是稳定宿主；SteamOS 和 macOS 使用各自的原生冻结启动器。真正的界面和业务代码位于 `app/versions/<version>/`。常规更新会下载一个模块包，校验 SHA-256 后解压到新的版本目录，再通过原子写入 `app/state.json` 切换版本。

发行包只携带**当前活动模块 + 最近一个已发布模块**（当前为 `1.0.0` 与 `0.2.0`）：前者是实际运行的代码，后者仅供新模块启动失败时自动回退。

```text
唏嘘南溪DLC一键解锁工具/
├── 唏嘘南溪DLC一键解锁工具.exe
├── app/
│   ├── state.json               # active_version 决定加载哪个模块
│   └── versions/
│       ├── 1.0.0/               # 当前活动模块
│       └── 0.2.0/               # 启动失败时的回退模块
├── config/
│   ├── update.json
│   ├── announcement.json        # 出厂公告（可被远程 hub 覆盖）
│   ├── guides/                  # 报错指南与解决方案
│   └── cartridges/              # 出厂游戏主表与默认卡带
├── cache/
└── data/
```

`0.1.0` 只存在于源码仓库中，是唯一受 Git 跟踪的模块源码基线，不随发行包发布。更完整的协议和发布流程见 [docs/update-architecture.md](docs/update-architecture.md)。

## 客户端主要功能

游戏列表不再写死在客户端代码中。启动时先读取 `config/cartridges` 出厂主表（并可联网刷新 GitLink / GitHub 的 `hub` Release），加载默认游戏卡带；切换到其他游戏时再按需下载对应卡带。启动公告同样来自 `hub` Release 的 `announcement.json`（本地出厂文件为 `config/announcement.json`）。

### DLC 库

- **一键解锁**：先审计并按需下载补丁资产，事务化替换补丁后，再依次下载并安装勾选的 DLC。已健康的补丁会被跳过。
- **一键修复**：先准备并校验补丁与全部 DLC、完成磁盘空间预检，全部就绪后才原地修复补丁并逐项重装 DLC，最后复检；准备阶段失败不会先破坏现有游戏文件。
- **一键移除补丁**：删除补丁文件并把原版库还原回去。没有安装凭据时会先从云端下载原始库并校验，再执行还原。
- **移除本程序安装内容**：只撤销由本程序管理的 DLC 与补丁，恢复被覆盖的同名文件；游戏原有内容、其他来源内容和下载缓存均保留。
- **逐项管理 DLC**：针对单个 DLC 执行下载、取消、校验和卸载。

补丁按平台使用不同的代理库与运行时原生库：

| 平台 | 解锁库 | 备份的原生库 | 配置文件 |
| --- | --- | --- | --- |
| Windows x64 | CreamAPI `steam_api64.dll` | `steam_api64_o.dll` | `cream_api.ini` |
| SteamOS x64 | SmokeAPI `libsteam_api.so` | `libsteam_api_o.so` | `SmokeAPI.config.json` |
| macOS Intel x64 | 替换型 `libsteam_api.dylib` | `libsteam_api_o.dylib` | 不生成配置文件 |

补丁安装、配置文件生成规则与审计状态见 [docs/publisher-guide.md](docs/publisher-guide.md)，跨平台约定见 [docs/cross-platform-patch.md](docs/cross-platform-patch.md)。

### 报错指南

内置按现象归档的解决方案（随平台显示对应条目），并提供：

- **一键排错**：自动检查网络、文件、模块与运行环境，逐项给出结果和可跳转的解决方案或工具；只做检测，不修改游戏文件、设置或网络配置。
- **解决方案 / 问题记录 / 运行日志**：按现象查处理办法、查看已记录的异常、筛选与导出运行日志。
- **常用工具**：图形设备兼容性、杀毒软件检测、补丁工具、日志资料收集、P 社启动器修复等自助工具。
- **导出诊断**：把诊断信息整理成一份文件，便于反馈问题。

### 下载与设置

- **下载任务**：区分待下载、下载中、已完成与失败，支持清除记录、取消全部下载和刷新；主界面左下角常驻显示网络状态、实时速度与缓存占用。
- **下载与网络**：在 GitLink 与 GitHub 之间切换下载源（同时作用于 DLC、卡带、公告和程序更新）、网络测速、超时检测开关。
- **程序与存储**：检查更新、查看缓存占用分布并清理缓存。
- **常规设置**：公告提醒、启动失败时保留当前模块。
- **离线模式**：未联网时程序仍可启动，但会禁用一键解锁并常驻提示重新连接网络后重启。
- **更新机制**：启动时自动检测并静默重试；强制更新会锁住主界面，只保留“下载更新包”与退出入口，安装完成后自动重启。

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
python -m ruff check .
```

CI 在 Windows、Ubuntu 24.04 和 macOS Intel 三个平台运行同一套 pytest 与 Ruff；Linux 上的界面用例通过 Xvfb 执行。

## 构建

```bash
python tools/build_module.py --all-versions app/versions
python tools/build_release.py  # 需要 PATH 中有 UPX（或 --upx-dir 指定）
# 以下命令必须分别在对应的 x64 系统执行，不能交叉编译
python tools/build_native_release.py --platform steamos
python tools/build_native_release.py --platform macos
```

`build_release.py` 会同时生成首次安装包和根目录结构不同的专用全量更新包。首次安装 ZIP/SFX 不能上传为 `kind: full` 更新。为同一个更新包生成匹配的 GitLink/GitHub 清单：

```bash
python tools/prepare_update_release.py dist/updates/SignRiver-DLC-Hub-full-v1.0.0-windows-x64.zip --version 1.0.0 --kind full --min-launcher-version 0.1.2 --notes "<与 update-notes.json 一致>" --mandatory --platform-package windows-x64=dist/updates/SignRiver-DLC-Hub-full-v1.0.0-windows-x64.zip --platform-package steamos-x64=dist/updates/SignRiver-DLC-Hub-full-v1.0.0-steamos-x64.zip --platform-package macos-x64=dist/updates/SignRiver-DLC-Hub-full-v1.0.0-macos-x64.zip
```

把专用全量更新 ZIP 原样上传到两个平台的 `updates` Release；GitLink 上传 `dist/updates/gitlink/update-manifest.json`，GitHub 上传 `dist/updates/github/update-manifest.json`。详细的保留和删除规则见 [程序更新发布指南](docs/program-update-release-guide.md)。

`build_release.py` 生成首次发布用的完整包：外层优先产出中文名自解压 EXE（需本机安装带 `7z.sfx` 的 7-Zip），并同时生成中文名 ZIP；解压后的文件夹与启动 EXE 均为「唏嘘南溪DLC一键解锁工具」。`build_module.py` 生成后续不修改启动器的小版本模块更新包。程序通过 `sys.executable` 定位安装目录，支持含中文的安装路径。

## ⭐ Star History

如果这个项目对你有帮助，请点个 Star 支持一下！

[![Star History Chart](https://api.star-history.com/svg?repos=sign-river/SignRiver-DLC-Hub&type=Date)](https://star-history.com/#sign-river/SignRiver-DLC-Hub&Date)

---

<div align="center">

**Made with ❤️ by [唏嘘南溪](https://github.com/sign-river)**

该程序为免费开源项目 | 如付费获得请立即退款

</div>