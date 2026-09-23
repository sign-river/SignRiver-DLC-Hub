# SignRiver DLC Hub 当前进度

更新时间：2026-09-23（Asia/Shanghai）

## 当前状态（2026-09-23）

- 当前线上正式版本：`1.0.0`（2026-09-22 发布）；启动器 `1.0.0`，Host API `3`，活动模块 `1.0.0`。
- 三端发行形式：Windows 便携 ZIP + 自解压 EXE、SteamOS 便携 `tar.gz`、macOS Intel ad-hoc 签名 `.app.zip`。
- 更新链路：`updates` Release 已上线三平台全量更新包与 GitLink/GitHub 双源清单；`modules` Release 的模块维护基线为 `0.1.7`、`0.2.0`、`1.0.0`。
- CI：`windows-latest` / `ubuntu-24.04` / `macos-15-intel` 三端 pytest 与 Ruff 全绿（2026-09-22 起，最新 run `35650193420`）。
- 已知差异：本地兜底卡带 10 条、云端主表 11 条，且部分卡带的平台可用性声明偏宽，见 `docs/known-issues.md` 的 `KI-011`。

### 1.0.0 发布产物（2026-09-23 本机实测复核）

| 产物 | 大小（字节） | SHA-256 |
| --- | --- | --- |
| `dist/modules/SignRiver-DLC-Hub-module-v1.0.0.zip` | 301,564 | `45decd9429424753110af8a40da1644729eb6b2953bfe12eb727c4f44a054b87` |
| `dist/updates/SignRiver-DLC-Hub-full-v1.0.0-windows-x64.zip` | 21,318,160 | `42bf2cce2f79ee340ed78980fde61a217dae6dc46be4e6c74e5c0690682a9fcd` |
| `dist/updates/SignRiver-DLC-Hub-full-v1.0.0-macos-x64.zip` | 23,785,464 | `e0fc722d25587e896905c3e326e3c7e6e05c485ebe5978e7f762becaf9a40001` |
| `dist/updates/SignRiver-DLC-Hub-full-v1.0.0-steamos-x64.zip` | 43,967,168 | `184532c02cf833ce5e94e2334626bf549858af18d982e0b20677673652aca935` |
| `dist/SignRiver-DLC-Hub-v1.0.0-macos-x64.app.zip` | 23,776,287 | `8b31ffe1c7e14e0996ff968e81ad2ff80cbeaf7a8ea35b9a4e570d431ac76ecd` |
| `dist/SignRiver-DLC-Hub-v1.0.0-steamos-x64.tar.gz` | 43,876,545 | `cf1a8a326f80bd21fd51c4402a6aba41567efe5f68c652de58a11e6ce41ab21c` |
| `dist/唏嘘南溪DLC一键解锁工具-v1.0.0-windows-x64.zip` | 21,333,799 | `e2c14b1125a30e538e6eaa16d4568fc98f2fcb359fefd11a2f4e1b17d924dd60` |
| `dist/唏嘘南溪DLC一键解锁工具-v1.0.0-windows-x64-自解压.exe` | 21,615,063 | `d8c715ab8893f19a358464a7cd4b210a60ef911a18749ef06464b8ce5ed1bc6d` |

自解压 EXE 与同内容别名大小一致；`config/module-archives.json` 的 `1.0.0` 记录与上表模块归档一致。

### 历史记录

下面从「2026-08-17 发布准备快照」开始的内容是 `0.2.0` 发布前的状态记录，保留用于追溯，**不再代表当前状态**。

## 2026-08-17 发布准备快照（历史，已被 1.0.0 发布取代）

- `0.2.0`“统一问题中心与补丁健壮性优化”代码已完成；Windows frozen 更新失败回滚已用最终打包 EXE 完成真实 E2E。
- 当前只有 Windows 原生候选是基于本轮最终源码重建的：launcher 为 `16,927,805` 字节，SHA-256 `89ae7fc6a0979e2d889fef4e47a9ede70453a5e2978c7ae11f20d9add9a79271`；全量更新包为 `18,791,906` 字节，SHA-256 `16683e3e80cf75ff287b5194d3c32ddeeb0105e2c357169e10cf94b6a5f554bc`。
- `0.2.0` 模块归档为 `199,755` 字节，SHA-256 `28ef829933955893d4a4ad6667cc737fc1493c2bd8748993adc3ec98a3ed23dd`；`config/module-archives.json` 已同步。
- 旧 macOS/SteamOS `0.2.0` 包早于本轮问题中心代码，不能作为最终候选；当前双源清单只包含新 `windows-x64` 包，待两个原生平台从当前源码重建后再一次性生成三平台清单。
- 当前完整回归为 `583 passed`；Ruff、compileall 和 `git diff --check` 均通过。
- macOS 发布验收不再包含真实游戏内运行。原生重建后手动确认 DLC 文件下载、大小/SHA-256、补丁安装、目标文件权限/哈希和失败恢复；卸载/原版恢复为可选补充项。
- Steam/Paradox Launcher 或游戏本体能否进入画面不再阻塞 macOS `0.2.0` 发布，但这不代表游戏内兼容性通过，发布与交接必须明确标记“未纳入验收范围”。
- 尚未上传任何 `0.2.0` 资产，尚未替换线上正式清单，尚未 commit/push。下方旧候选包和历史验证数据仅供追溯，以本节和 `docs/agent/HANDOFF.md` 为准。


## 历史结论（0.2.0 发布前，2026-08-17）

> 以下结论记录于 2026-08-17（`0.2.0` 发布前），已被 `1.0.0` 发布取代，仅用于追溯。

- 当前线上正式版本：`0.1.7`
- 当前开发/待发布版本：`0.2.0`
- Host API：`3`
- 活动模块：`0.2.0`
- 当前更新类型：`full`
- Windows 客户端、启动器和全量更新候选已基于当前源码重建；发布器未纳入本轮问题中心改造。
- macOS Intel x64 与 SteamOS x64 必须从当前源码重新构建原生包；旧包及其历史验证结果不能代表本轮最终候选。
- 线上 GitLink/GitHub 清单仍保持 `0.1.7`，在三个 `0.2.0` 平台包全部上传并校验前不得替换。
- `0.1.7` 为强制更新，启动后会自动检查并静默重试，用户不必手工点击“检查更新”。
- `0.2.0` 模块维护基线为 `0.1.6`、`0.1.7`、`0.2.0`。
- SteamOS 历史候选曾通过冻结启动、全量更新回滚和 HOI4/SmokeAPI 真实验收；当前源码重建后仍需复核发布包。
- macOS 历史候选曾通过原生构建、签名和全量更新成功/失败回滚 E2E；当前源码重建后的发布门槛改为手动 DLC 下载、完整性、补丁安装与恢复验收，不再要求游戏内运行。

## 0.1.4—0.1.7 主要变化

### 0.1.4

- 修复远程 Stellaris 卡带的 DLC 包校验参数兼容问题。
- 默认卡带远程加载失败时回退到本地可用卡带，避免旧客户端离线启动失败。

### 0.1.5

- 接入强制更新流程，`mandatory` 更新不可跳过。
- 下载速度、缓存和文件大小统一按 KB/MB/GB 自适应显示。

### 0.1.6

- 新增 QQ 交流群入口和“导出支持列表”。
- 修复启动崩溃、主窗口不显示和空白闪烁问题。
- 任务成功/失败反馈改为更醒目的彩色横幅。
- 发布器增加滚动日志、更新上传暂停/继续、更新说明编辑和更可靠的临时文件清理。

### 0.1.7

- 启动后自动检查重要更新，并在失败时静默重试。
- 优化强制更新提示文案，减少用户对程序不可用的误解。
- 包含 `0.1.6` 的全部修复和界面优化。

## 核心能力状态

### 客户端

- 五款出厂游戏卡带：群星、文明 6、钢铁雄心 4、都市：天际线、边缘世界。
- Steam 安装发现、手动路径、安装实例持久化和路径健康检查。
- GitLink/GitHub 双源卡带、公告、DLC、补丁和程序更新。
- 单线程下载队列、任务恢复、暂停/取消、哈希校验、内容寻址缓存和坏包隔离。
- DLC 事务化安装、覆盖备份、失败回滚、安装回执、审计、保守修复和安全卸载。
- CreamAPI 补丁的一键安装、修复、移除和原版恢复。
- 日志筛选、缓存清理、网络测速和脱敏诊断包导出。

### 启动器与更新

- 模块包安全解压、SHA-256 校验、原子激活和启动失败回滚。
- 完整包受管文件清单、同卷暂存、磁盘空间预检和反序回滚。
- Windows 临时更新助手可在主程序退出后替换运行中的启动器。
- 更新后确认、残留事务恢复、多版本回退链和无可用模块时的修复提示。
- `data/`、`cache/`、`app/state.json` 和用户下载源配置不由全量更新覆盖。

### 发布器

- DLC、补丁、AppInfo、公告和游戏卡带的工作区管理。
- GitLink/GitHub Release 创建、附件替换、冗余附件清理和双源镜像。
- 程序更新包自动识别版本与类型，校验文件名和包内元数据。
- 程序更新真实上传进度、暂停/继续、更新说明草稿和强制更新选项。
- 模块归档批量发布，以及双源更新清单的安全上传顺序。

## 历史线上发布产物（0.1.7，已被 1.0.0 取代）

### 全量更新包

`dist/updates/SignRiver-DLC-Hub-full-v0.1.7-windows-x64.zip`

- 大小：`18,962,658` 字节
- SHA-256：`8c843e7af2a339722d5397154d510509e8f31cbda4bd23ba7f47591ed3482b92`
- 更新类型：`full`
- 最低启动器版本：`0.1.2`
- 强制更新：是

对应清单：

- `dist/updates/gitlink/update-manifest.json`
- `dist/updates/github/update-manifest.json`

### 首次安装包

- `dist/唏嘘南溪DLC一键解锁工具-v0.1.7-windows-x64.zip`：`18,989,212` 字节
- `dist/唏嘘南溪DLC一键解锁工具-v0.1.7-windows-x64-自解压.exe`：`30,341,226` 字节

### 模块归档

`dist/modules/SignRiver-DLC-Hub-module-v0.1.7.zip`

- 大小：`187,755` 字节
- SHA-256：`cf2d2a93e67b790c852b79df35646fb2ee3499112be9c6627e35e1f9406b4844`

### 发布器

`dist/publisher/SignRiver-Publisher.exe`

- 大小：`15,300,633` 字节
- SHA-256：`53616697761fc05ad41e96c96730e1d542554788c46580ab140dddac6dcbfe0e`

## 历史本地候选产物（早于本轮问题中心改动，不得发布）

- Windows 全量更新 ZIP：`19,183,195` 字节，SHA-256 `1bb012cbea7e1363e99a7fab701ef1db2dc70e0b2d91d24c0793a14753270247`。
- Windows 首装 ZIP：`19,215,055` 字节，SHA-256 `1b89c9ece08a3d0145c2620cd7b1caec8fea579932a344fea2c9c5497c52ec81`。
- Windows 自解压包：`30,551,296` 字节，SHA-256 `eb2bd0bd2181282dbdd9de8e1d5dbdae884827345a0ea7c8a16931510d1eb327`。
- Windows 发布器：`15,309,181` 字节，SHA-256 `551e29cc7ac21fdeeb6ebbbb882d2d47b439f4729bb3030741aa5f3923fe2c2a`。
- 0.2.0 模块归档：`191,187` 字节，SHA-256 `896c2bbb2f8d2fc1f091a1065a0bfb75cc4d8dc2918004f2031055f63a493b34`。
- SteamOS 首装 tar.gz：`36,077,253` 字节，SHA-256 `e7a09f88b5f3811a0890d600392b541a69c4b4ead907a9440429162b80be4b68`。
- SteamOS 全量更新 ZIP：`36,271,872` 字节，SHA-256 `9f1ae851c382898ffc5dde9cce6c2ebeb54adfa1d36e24bb8a459d0af688675a`。
- macOS 首装 `.app.zip`：`21,587,550` 字节，SHA-256 `fcfdb50822f8b535dfe2100719f5c5a9b307d149d27617237db62d0fd93d6daf`。
- macOS 全量更新 ZIP：`21,593,680` 字节，SHA-256 `4eccd3641f219f75a2e9c760762178d773b00777bb4a23dab662f22183ce5982`。
- 本节包体均为历史候选，不代表当前源码。最终发布必须重新构建 macOS/SteamOS，并使用当前 Windows 包与两个新原生包统一生成双源清单。

## 历史跨平台验证结果（当前源码重建后仍需复核）

- 0.2.0 Windows 最新工作区完整测试：`python -m pytest` 为 `533 passed in 11.36s`；Ruff、compileall 与 `git diff --check` 通过（2026-08-16）。
- Windows `0.1.7 -> 0.2.0` 冻结版强制全量升级已通过本地 HTTP E2E：自动重启、事务确认、用户数据保留和新 EXE 哈希均验证成功。
- 0.2.0 SteamOS 虚拟机：最新源码完整 pytest 通过（其中 1 项按平台跳过），Ruff、compileall、原生 tar.gz/更新 ZIP 构建和冻结启动冒烟通过。
- SteamOS 冻结包本地全量更新 E2E 已通过：精确选中 `steamos-x64` 包，自动替换并重启至 0.2.0，事务进入 `confirmed`，用户数据标记保留且启动器权限恢复为 `0755`；注入损坏模块后的冻结版故障测试也能回到 0.1.0，事务进入 `rolled_back`。
- SteamOS VirtualBox 通过安装保留原内核的 Arch LTS 测试内核、切换 `VMSVGA` 并启用 3D 后，HOI4 原版可进入主菜单；原 SteamOS 内核仍保留在 GRUB 高级启动项中，且已创建变更前快照。
- SmokeAPI v4.1.3 proxy 模式真实运行通过：补丁库 SHA-256 为 `dcb21dc733d38c51b5d673c581edd31f995bbdbaff5582540ece7981eb94b6d2`，游戏日志记录多个 DLC 查询为 `Unlocked: true`。
- 使用客户端 DLC 事务引擎安装此前不存在的 `Peace For Our Time` 后，HOI4 游戏日志从 4 个 Active DLC 增加到 5 个，并明确记录 `Active DLC: Peace For Our Time`；游戏主菜单截图、SmokeAPI 日志与系统日志均已留存并校验哈希。
- SteamOS 补丁/DLC 生命周期已闭环：安装审计 `healthy`、人为损坏识别为 `modified`、修复回到 `healthy`、安全卸载成功；移除 SmokeAPI 后原版 `libsteam_api.so` 恢复为 SHA-256 `528430be2727b3d5e04e7401f1fca662726d705fcc952f6c6b16c6b5c942b481`，原版游戏再次启动成功。
- 最新 SteamOS 首装包：`36,077,253` 字节，SHA-256 `e7a09f88b5f3811a0890d600392b541a69c4b4ead907a9440429162b80be4b68`；全量更新 ZIP：`36,271,872` 字节，SHA-256 `9f1ae851c382898ffc5dde9cce6c2ebeb54adfa1d36e24bb8a459d0af688675a`。
- macOS 最新源码完整测试为 `528 passed, 1 skipped`，Ruff 与 compileall 通过；最终 `.app` 为 Mach-O x86_64，`codesign --verify --deep --strict` 通过。
- macOS `0.1.7 -> 0.2.0` 冻结版全量更新 E2E 已通过：下载/哈希/平台/架构/清单校验、整个 `.app` 原子交换、自动重启、事务 `confirmed`、用户数据与 `0755` 权限保留、确认后备份清理均验证成功。
- macOS 在旧 bundle 已移到 backup 后注入第二次 `os.replace` 失败，事务进入 `rolled_back`；原 `.app`、签名和用户数据恢复，candidate/backup/failed 临时路径无残留。
- `0.1.7` 全量包的本地大小和 SHA-256 与 GitLink/GitHub 清单一致。
- 两份清单使用相同版本、更新说明、强制更新标志和哈希，但分别指向各自平台。
- `config/module-archives.json` 记录的 `0.1.7` 模块大小和 SHA-256 与本地归档一致。
- 既有真实安装目录 E2E 已覆盖双源升级、下载源保留、更新助手替换、模块损坏回退链和修复提示。

## 已知边界

### 旧启动器无法自我修复

`0.1.0` 旧启动器会复制自己的旧 EXE 作为更新助手，因此不能只依靠远端全量 ZIP 修复其 Windows 句柄错误。`0.1.0` 用户需要先手工安装不低于 `0.1.2` 的版本；从 `0.1.2` 起，后续全量自动更新使用更新包中的新版助手。

### macOS 游戏内运行不纳入当前发布验收

受控模块源码已加入 SteamOS SmokeAPI 和 macOS icecream 的补丁数据模型、配置解析与单元测试。SteamOS 历史候选已完成真实 HOI4、未购买 DLC、补丁日志、审计、修复、移除和原版恢复验收。macOS 历史候选已完成 Intel icecream 构建、原生 `.app`/更新包构建以及全量更新成功与注入失败回滚 E2E；这些包均早于本轮问题中心代码，需要从当前源码重建。重建后的 macOS 验收只要求手动确认 DLC 下载与大小/SHA-256、补丁安装、目标文件权限/哈希、失败恢复，并可选确认卸载/原版恢复。Steam 登录、HOI4 许可以及进入游戏画面不再是 `0.2.0` 发布阻断项，也不得据此宣称游戏内兼容性已通过。

macOS 虚拟机已创建 `pre-tahoe-apfs-install`、`pre-account-setup` 和 `pre-account-setup-zh` 恢复快照。该虚拟机虽然命名为 Tahoe，但实际恢复镜像与安装器为 macOS Sequoia（Darwin 24）；107.16 GB 目标盘已格式化为 GUID/APFS 并完成系统安装。恢复环境不识别 `e1000e`/`e1000`，切换为 `vmxnet3` 后识别为 `en0`、取得 NAT 地址并能访问 Apple CDN。安装下载经 Clash Verge 规则模式时停滞，临时切到直连后完成安装，随后已恢复规则模式。VMware 控制台的 SendInput 无法进入来宾系统，因此安装与首次设置阶段使用仅监听 `127.0.0.1:5901` 的临时 VNC 控制通道。

icecream 上游固定为 [`krnya/icecream`](https://github.com/krnya/icecream) 提交 `0c8f74628d00b944ebbb750bf84c34a91475419d`（MIT），源码归档大小为 `9,523` 字节，SHA-256 为 `49aca4f18cb5a2aedc18d577936d9342a3ff1d937eb2e16b157793c4c85c4b80`；macOS 原生构建的 x86_64 `libsteam_api.dylib` 为 `612,912` 字节，SHA-256 为 `68a32d893a00df57010396e439116f33193f44de0d0a817361b4bf1550936daa`。

SteamOS OOBE 镜像的 `/usr/bin/steam-jupiter` 会清空 Steam 配置，测试环境必须继续使用 `/usr/lib/steam/steam`。VirtualBox 的 VMSVGA 需要标准内核中的 `vmwgfx`，本虚拟机已保留快照并安装了与原内核并存的 LTS 测试内核；这属于测试基础设施调整，不进入客户端发行包。

## 上传与保留规则

应发布：

- 普通 Release：`0.1.7` 首次安装 ZIP 和自解压 EXE。
- `updates` Release：`0.1.7` 全量更新 ZIP，以及对应平台的唯一 `update-manifest.json`。
- `modules` Release：模块维护基线中列出的三个模块归档。

必须保留：

- 当前清单及其引用的全量更新包。
- 最近三个可用模块归档：`0.1.5`、`0.1.6`、`0.1.7`。
- 回滚测试未完成时的 `.update-backup/`。

禁止提交或上传：

- `dist/publisher/publisher.local.json`
- `config/publisher.local.json`
- `publisher-workspace/`
- 本地更新测试基线
- 任何 GitLink/GitHub 私有令牌

## 后续方向

1. 在 macOS Intel x64 和 SteamOS x64 原生环境中，从当前源码重新构建 `0.2.0` 首装包与全量更新包。
2. macOS 手动验收 DLC 下载、文件大小/SHA-256、补丁安装、目标文件权限/哈希与失败恢复；条件允许时再确认安全卸载/原版恢复。游戏内运行不纳入本次验收。
3. 复核 SteamOS 当前源码候选的冻结启动、更新与补丁关键流程，不复用旧包作为最终候选。
4. 三平台新包齐备后一次性生成双源清单，核对 URL、大小、SHA-256、中文 notes，再按“模块/平台包在前、清单在后”的顺序上传发布资产。
5. 发布资产上传并验证完成后再提交；默认由用户推送，除非用户明确要求“提交并推送”。
