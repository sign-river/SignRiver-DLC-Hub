---
name: build-native-client-releases
description: 为 SignRiver DLC Hub 准备完整源码，并在 SteamOS x64 或 macOS Intel x64 虚拟机中原生构建、检查和启动验证客户端首次安装包与全量更新包。用户要求构建、重建、打包或验证 SteamOS/macOS 客户端发布产物时使用；不用于 Windows 发布器 EXE，也不自动上传、发布、提交或推送。
---

# 构建 SteamOS 与 macOS 原生客户端发布包

在 Windows 主工作区完成代码准备，把**完整的当前工作区源码**同步到目标虚拟机，然后在对应来宾系统内运行 `tools/build_native_release.py`。最终可执行文件必须原生构建，禁止在 Windows 上交叉生成 SteamOS/macOS 发布包。

## 先确定任务边界

- 明确目标平台：`steamos`、`macos` 或两者。
- 明确是临时启动验证还是正式版本构建。正式版本构建继续遵守根目录 `AGENTS.md` 的版本号、更新说明、模块归档和发布顺序。
- 构建和本机验证不代表获得上传或发布授权。除非用户明确要求，否则不得上传产物、更新线上清单、commit 或 push。
- 不执行 Steam 登录、游戏下载或真实 DLC 下载，除非用户另外明确要求。

## Windows 侧源码准备

1. 核对分支、HEAD、`git status --short` 和相关测试，保留全部用户未提交改动。
2. 从 `src/signriver_launcher/constants.py` 取得目标版本，并核对：
   - `app/state.json` 的 `active_version`；
   - `app/versions/<版本>/module.json` 的 `version` 与 `api_version`；
   - `publisher-workspace/update-notes.json` 中正式发布版本的中文说明。
3. 客户端业务代码以受 Git 跟踪的 `app/versions/0.1.0/` 为首改位置；构建前按项目规则同步到 `app/versions/<目标版本>/`。
4. 检查目标版本至少包含 `module.json`、`app_entry.py` 和完整的 `signriver_app/`。抽查一个深层运行文件并统计文件数，不能只验证目录存在。
5. **禁止单独使用 `git archive HEAD` 作为虚拟机源码。** 它不会包含被 `.gitignore` 忽略的目标版本目录，也不会包含未提交改动。同步方案必须同时保留当前工作区改动和完整的 `app/versions/<目标版本>/`。
6. 排除 `.git/`、虚拟环境、`build/`、`dist/`、缓存、凭据和本地发布器配置；不要把 SSH 私钥、令牌、Cookie 或账号数据打进源码归档。

## 平台路由

- 构建 SteamOS 时，先读取并执行 [references/steamos.md](references/steamos.md)。
- 构建 macOS 时，先读取并执行 [references/macos.md](references/macos.md)。
- 两个平台都构建时，可以并行完成来宾侧的依赖检查和构建，但每个平台独立保存命令、产物路径、SHA-256 和验证结果。

## 共同验收

每个平台至少验证以下内容：

1. 构建命令成功退出，产物名称含正确版本、平台与 `x64`。
2. 首次安装包和全量更新 ZIP 都存在且非空；压缩包完整性检查通过。
3. 解包后的原生二进制架构正确：SteamOS 为 x86-64 ELF，macOS 为 x86_64 Mach-O `.app`。
4. 发布包内 `app/state.json` 激活目标版本，且目标版本目录包含完整 `signriver_app/`，不是只有 `module.json`。
5. 启动程序并观察至少 8 秒；确认进程存活、没有新的崩溃报告，也没有自动回退到旧模块。
6. macOS 还要检查用户可写状态 `~/Library/Application Support/SignRiver DLC Hub/app/state.json`：如果旧失败曾把目标版本放进 `bad_versions`，只有在确认目标模块完整后才清除失败记录并重新激活目标版本。
7. 记录执行过和未执行的测试。未做真实游戏、下载或更新 E2E 时必须明确写“未执行”，不能用启动存活替代这些验收。

完成后向用户报告：同步来源、来宾构建目录、产物路径、版本与架构、SHA-256、启动验证、未执行项，以及是否发生任何上传、发布、commit 或 push。
