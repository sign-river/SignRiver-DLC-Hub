# SignRiver DLC Hub 项目背景

> 最后核对：2026-08-16（Asia/Shanghai）

## 项目目标

SignRiver DLC Hub 是一个面向多款 Steam 游戏的桌面 DLC 管理器。当前正式线上版本为 `0.1.7`，开发目标为 `0.2.0`：在保持 Windows x64 既有行为和升级链路的前提下，补齐 SteamOS x64 与 macOS Intel x64 的原生运行、补丁、更新和真实游戏验收。

## 核心架构

- `src/signriver_launcher/`：稳定启动器、版本选择、模块更新和全量更新宿主；
- `app/versions/0.1.0/`：唯一受 Git 跟踪的模块源码基线，客户端 UI 和主要业务逻辑从这里修改；
- `app/versions/<发布版本>/`：发布构建时同步得到的目标模块目录，不作为日常首改位置；
- `src/signriver_common/`：启动器、发布器和构建工具共享的数据模型与平台能力；
- `src/signriver_publisher/`：Windows 发布器、资源管理和多平台发布流程；
- `config/cartridges/`：游戏卡带索引与平台差异配置；
- `tools/`：模块、首次安装包、全量更新包、清单和原生平台构建工具；
- `tests/`：pytest 自动化测试；
- `docs/`：架构、发布、虚拟机和当前进度文档。

运行时采用“稳定启动器 + 可切换版本模块”结构。启动器读取 `app/state.json` 选择活动模块，新模块启动失败时可回退旧版本。

## 技术栈与运行环境

- Python `>=3.11`；
- GUI：CustomTkinter；
- 测试：pytest；
- 静态检查：Ruff；
- 冻结构建：PyInstaller；
- Windows 构建可使用 UPX；
- Windows、SteamOS 和 macOS 的原生冻结包必须在对应平台构建，不交叉生成最终平台二进制。

当前主要环境：

- Windows：主开发、发布器和 Windows 发行包构建；
- SteamOS 虚拟机：Linux 原生构建、更新 E2E、HOI4 + SmokeAPI 真实验收；
- VMware macOS Sequoia（Darwin 24）虚拟机：Intel dylib、`.app`、更新 E2E 和 HOI4 + icecream 验收。

虚拟机的完整复现和失败路线分别见：

- `docs/steamos-virtual-machine-setup.md`
- `docs/macos-virtual-machine-setup.md`

## 常用命令

安装开发依赖：

```powershell
python -m pip install -e ".[dev]"
```

运行测试与静态检查：

```powershell
python -m pytest
python -m ruff check .
python -m compileall -q src app\versions\0.1.0 tools tests
```

本地启动：

```powershell
python launcher.py
python publisher.py
```

典型 Windows 构建命令：

```powershell
python tools\build_module.py --all-versions app\versions
python tools\build_release.py --upx-dir C:\Users\32173\AppData\Local\tools\upx\upx-5.0.2-win64
python tools\build_publisher.py --upx-dir C:\Users\32173\AppData\Local\tools\upx\upx-5.0.2-win64
```

具体发布顺序、清单参数和版本同步要求以 `AGENTS.md` 与 `docs/program-update-release-guide.md` 为准。

## 状态文档分工

- `README.md`：面向开发者和使用者的总体说明；
- `STATUS.md`：已发布稳定基线的简要状态，不承担实时交接；
- `PLAN.md`：`0.2.0` 的范围、验收标准和路线图；
- `docs/current-progress.md`：版本产物、详细进展和已知边界；
- `docs/agent/HANDOFF.md`：最新任务交接，允许高频更新；
- `docs/agent/DECISIONS.md`：关键方案及失败经验。

当文档互相冲突时，使用以下优先级判断：

1. 当前代码、配置、Git 状态和可重复测试结果；
2. 最新核对过的 `HANDOFF.md`；
3. `docs/current-progress.md`；
4. `PLAN.md`；
5. `STATUS.md` 与 `README.md` 中的历史描述。

## 模块版本目录、module.json 与 API 版本（2026-09-21 补充）

### 三个概念

- **源码目录**：`app/versions/0.1.0/` 是仓库里**唯一被 Git 跟踪**的模块源码（`.gitignore` 中 `/app/versions/*` 全部忽略，仅放行 `0.1.0`）。目录名是历史遗留，**里面的代码始终是最新代码**；不要用目录名推断功能年代。
- **发行副本**：`app/versions/<版本>/`（如 `0.2.0`、`1.0.0`）都是从未跟踪目录复制出来的副本，仅用于构建与运行，不入库。它们与 `0.1.0` 的代码内容一致，差别只在 `module.json` 的 `version` 与 `api_version`。
- **活动模块**：`app/state.json` 的 `active_version` 决定客户端实际加载哪个版本目录；启动器要求 `state.active_version` == 目录名 == `module.json.version`，三者不一致会拒绝加载。

### `api_version` 的语义

- `module.json` 的 `api_version` 表示"该模块要求宿主（启动器）提供到第几代 API"，由 `src/signriver_launcher/constants.py` 的 `HOST_API_VERSION`（当前 3）定义上限。
- 校验规则（`src/signriver_launcher/models.py`）：`api_version > HOST_API_VERSION` 时拒绝加载并提示更新；**小于等于都允许**。因此 `api_version 1` 的老模块仍可运行，而声明 4 的模块会被当前启动器拒绝。
- 新建版本时 `api_version` 应采用当前 `HOST_API_VERSION`，不要沿用旧目录的值（例如 0.1.0 目录里的 `api_version` 仍是 1）。

### 日常开发与发版流程

1. **改代码只改 `app/versions/0.1.0/`**（唯一源码；需要当前客户端立刻生效时，再把同一改动"定向同步"到 `app/state.json` 指向的活动版本目录）。
2. **发版**：把 `0.1.0` 复制为 `app/versions/<新版本>/`，只修改 `module.json` 的 `version`（= 新版本号）与 `api_version`（= 当前 `HOST_API_VERSION`）。
3. 同步 `app/state.json` 的 `active_version`、`src/signriver_launcher/constants.py` 的 `LAUNCHER_VERSION`、`publisher-workspace/update-notes.json` 的版本说明，并重新构建模块归档后更新 `config/module-archives.json`。
4. **不要重新上传旧版本（如 0.2.0）的模块归档**：源码在该版本发布后仍有修复，本地重建产物与线上登记哈希不一致，重传会导致 CI 校验失败。

## 不可忽略的稳定约束

- 不得重置、清理或覆盖不属于当前任务的未提交改动；
- 模块业务代码先改 `app/versions/0.1.0/`；
- 构建新版本时同步更新 `publisher-workspace/update-notes.json`；
- 发布资产、清单、版本号和 SHA-256 必须一致；
- 默认禁止自动推送，只有用户明确要求时才能 `git push`；
- `publisher-workspace/`、本地发布器配置、令牌和测试基线不得提交；
- 真实平台验收结果不能用模拟目录或 Windows 侧推断替代。
