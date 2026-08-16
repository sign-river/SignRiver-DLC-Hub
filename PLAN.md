# SignRiver DLC Hub 0.2.0 跨平台适配与验收计划

## 目标

在不改变 Windows x64 现有行为、安装数据和升级链路的前提下，将客户端扩展到 SteamOS x64 和 macOS Intel x64，并由 Windows 发布器统一管理三个平台的资源与更新包。

- 正式版本：`0.2.0`
- Host API：`3`
- Windows：便携 ZIP/SFX、CreamAPI、全量更新
- SteamOS：便携 `tar.gz`、平台全量更新 ZIP、SmokeAPI 64 位 proxy
- macOS Intel：ad-hoc 签名 `.app.zip`、平台全量更新 ZIP、icecream
- 首版不包含 Apple Silicon、universal2、AppImage、DMG、Developer ID 签名或 notarization

## 不可破坏的兼容边界

- Windows 继续使用程序目录中的 `app/`、`data/`、`cache/`。
- 保持旧版更新清单顶层 Windows `package_url`、`sha256`、`size` 字段。
- Windows `0.1.7` 必须能直接升级到 `0.2.0`。
- CreamAPI、中文路径、便携 SFX、强制更新和失败回滚必须无回归。
- 发布器仍只在 Windows 上运行。
- 发布包上传完成前不得推送源码；提交后仅在用户明确要求时推送。

## 实现范围

### 平台与运行时

- 统一识别 `windows / steamos / macos` 和 `x64`，业务代码不再散落使用 `os.name`。
- SteamOS 使用 XDG 数据和缓存目录。
- macOS 使用 `~/Library/Application Support/SignRiver DLC Hub` 和 `~/Library/Caches/SignRiver DLC Hub`。
- 安装资源与可写状态分离，首次启动复制初始资源到用户状态目录。
- 抽象目录打开、精确进程检测、重启、大小写敏感路径、权限、符号链接和路径逃逸检查。
- 发布清单记录并安全恢复 Unix 文件 mode。

### Steam 与游戏卡带

- 支持 Windows 注册表和默认路径、SteamOS 原生与 Flatpak Steam、macOS Steam 路径。
- 卡带按平台声明可执行文件、DLC 目录、补丁目录、资产、配置格式和支持状态。
- 修复平台字段序列化 round-trip。
- 五张现有卡带补齐平台布局；未确认的平台不得回退到 Windows `.exe`。
- HOI4 的 Linux/macOS 原生路径以虚拟机 Steam 安装结果为受测基线。

### 补丁资产

- SteamOS：原版 `libsteam_api.so` 保存为 `libsteam_api_o.so`，安装 SmokeAPI 为 `libsteam_api.so`，生成 v4 `SmokeAPI.config.json`。
- macOS：构建 Intel `libsteam_api.dylib`，原版保存为 `libsteam_api_o.dylib`，生成 `icecream.ini`，对 dylib 和 app 执行 ad-hoc 签名。
- 平台二进制不提交源码仓库；发布资源记录上游版本、提交、SHA-256 和许可证。
- 安装、审计、修复、移除和原版恢复共用事务引擎，并检查 ELF、Mach-O、权限和签名。

### 更新、构建和发布

- `update-manifest.json` 增加精确的 `platform_packages`；无匹配项时禁止下载其他系统包。
- `release-manifest.json` 保持 schema 1，增加可选平台、架构和文件 mode。
- PyInstaller 在对应原生系统构建，不交叉编译。
- SteamOS 产出首次安装 `tar.gz` 和自动更新 flat ZIP。
- macOS 产出 ad-hoc 签名 `.app.zip` 和包含完整 `.app` 的更新 ZIP。
- Windows 发布器校验并上传三平台安装包和更新包，全部成功后才替换双源清单。
- 维护 `publisher-workspace/update-notes.json` 的 `0.2.0` 中文说明。

## 验收标准

### 自动化

- Windows、Ubuntu 24.04、macOS Intel CI 运行 pytest、Ruff 和编译检查。
- Linux UI 测试使用 Xvfb。
- 覆盖平台识别、Steam 根目录、进程检测、路径大小写、权限、卡带 round-trip、平台资产、旧清单兼容和错平台拒绝。
- 三个平台分别完成冻结包启动冒烟和本地全量更新 E2E。

### Windows

- 现有测试无回归。
- `0.1.7 -> 0.2.0` 冻结版全量升级成功。
- CreamAPI、中文路径、SFX、强制更新和回滚正常。

### SteamOS 与 macOS

- 在虚拟机内原生构建并启动冻结包。
- 安装 HOI4，验证自动发现和手动路径。
- 完成补丁安装、日志、审计、修复、移除和原版恢复。
- 游戏内确认至少一个未购买 DLC 可用；仅模拟目录不算完成。
- 验证平台全量更新、自动重启、数据保留和失败回滚。

### 最终发布

- 核对所有安装包、更新包和双源清单的大小、SHA-256、平台与架构。
- 更新文档与中文发布说明。
- 整理并提交源码；资源包上传完成后再由用户或经用户明确授权推送。

## 人工暂停点

仅在以下情况请求用户介入：

- Apple、Steam 或其他测试账号凭据输入。
- Steam Guard、许可协议或需要用户确认的安全弹窗。
- HOI4 游戏内确认未购买 DLC 是否可用。
- 虚拟化平台要求物理 USB 设备或宿主机安全授权。
- 连续验证后确认属于不可控环境阻塞。

## 当前进度

- [x] Windows 工作区切换为 `0.2.0`，Host API 3。
- [x] 跨平台识别、运行目录、Steam 发现、卡带平台变体和序列化实现。
- [x] 平台更新包选择、错平台拒绝、文件 mode 和跨平台更新助手实现。
- [x] Windows 发布器三平台包选择、校验和统一清单生成实现。
- [x] SteamOS/macOS 原生构建器与三平台 CI 矩阵实现。
- [x] Windows pytest、Ruff、编译和冻结启动冒烟通过。
- [x] Windows `0.2.0` 模块、全量更新、便携 ZIP/SFX 和发布器完成本地构建。
- [x] Windows `0.1.7 -> 0.2.0` 冻结版强制全量升级、自动重启和数据保留通过。
- [x] SteamOS 虚拟机快照、SSH、Xorg、1440x900、自动启动和 ACPI 正常关机修复。
- [x] 将当前 `0.2.0` 源码同步到 SteamOS 并运行测试。
- [x] 在 SteamOS 原生构建安装包和更新包并运行冻结包。
- [x] SteamOS 冻结包本地全量更新 E2E：平台包选择、自动重启、数据保留、权限恢复、事务确认及故障回滚。
- [x] SteamOS HOI4 + SmokeAPI 真实验收及补丁修复/移除/原版恢复。
- [x] 完成 macOS VMware（实际镜像为 Sequoia/Darwin 24）初始设置；俄语界面已修复为简体中文，本地账户已创建并进入桌面。
- [ ] macOS Intel icecream、客户端、HOI4 和更新回滚验收。
- [ ] 三平台最终包与清单核验、文档、提交和发布顺序确认。
