# 当前任务交接

## 发布器原生平台补丁资源构建（2026-09-21）

- 根因：客户端已经按平台卡带字段读取原生库名，但发布器构建只复制 Windows 的 `unlocker.dll` / `original.dll` 及旧别名，不会处理 `patch_platforms` 声明的 macOS/SteamOS 原生文件。
- 修改：`src/signriver_publisher/workspace.py` 在 `published_platform_resources[platform].patch == true` 时，按 `patch_platforms` 中的 `unlocker_dll_name` / `runtime_original_library_name` 从 `patches/` 复制到发布输出目录，并纳入 `catalog.json`；缺文件时构建失败。未标记为已发布的平台不受影响。
- 测试：`tests/test_publisher_workspace.py` 新增原生库输出与缺文件阻止构建用例；全文件 87 项、`tests/test_dlc_catalog.py` 14 项、`tests/test_patch_platforms.py` 18 项通过；Ruff 与 `git diff --check` 通过。
- 真实工作区核对：macOS 有 `libsteam_api.dylib` 与 `libsteam_api_o.dylib`；SteamOS 当前只有 `libsteam_api_o.so`，缺少 `libsteam_api.so`。现有 SmokeAPI 候选文件为 `publisher-workspace/acceptance/steamos/SmokeAPI-v4.1.3/libsteam_api.so`（尚未复制到 Stellaris 的 `patches/`）。
- 本轮未执行：真实 Stellaris 重新构建、上传、双源回读、线上主表切换、push。

## macOS 原生库导出与 SteamOS VM 切换（2026-09-20）

- 从 macOS Sequoia VM 的 Stellaris 安装目录复制截图选中的 `libsteam_api.dylib` 到 Windows 临时导出目录 `.test-artifacts/libsteam_api.dylib`；文件大小 `5,195,264` 字节，SHA-256 为 `0FF4A7C9D44A600BF514D069982D884C0ADD67431BAE24341063C18CE310A11F`。
- macOS VM `D:\\vmware\\macos-vm\\macOS Sequoia.vmx` 已通过 VMware 正常挂起；未关机、未修改 VMX。
- 已启动 SteamOS VMware VM：`D:\\vmware\\steamos\\workstation\\SteamOS-VMware.vmx`。未执行 SteamOS 构建命令或资源上传。

## 原生平台补丁资源严格隔离（2026-09-20）

- 云端核对：GitLink/GitHub 的 `hub/cartridges_index.json` 当前所有卡带仅标记 `windows`；群星 `stellaris` Release 只有 `unlocker.dll`、`original.dll`、`steam_api64.dll`、`steam_api64_o.dll` 与 AppInfo，没有 `libsteam_api.so` 或 `libsteam_api.dylib`。当前不能宣称云端已有 SteamOS/macOS 补丁。
- 根因：客户端 `ReleaseCatalogService` 过去只按通用角色名解析补丁，macOS/SteamOS 也会接受 Windows DLL，并在后续哈希审计中被误判为健康。
- 修改：`app/versions/0.1.0/signriver_app/application/dlc_catalog.py` 对 Windows 保留旧别名；SteamOS/macOS 只接受卡带平台字段声明的原生库文件名。缺少原生资产时返回缺失补丁，阻止下载与“一键解锁成功”；同步到活动模块 `app/versions/0.2.0/`，未整目录覆盖。
- 测试：`tests/test_dlc_catalog.py` 新增 Windows DLL 不得冒充 macOS 补丁、原生文件名可正常解析的回归覆盖；`pytest -q tests/test_dlc_catalog.py tests/test_cartridge_catalog.py tests/test_platform_content.py` 全部通过；compileall 与 `git diff --check` 通过。
- 发布说明：当前发布器的 `patches/` 工作区和既有 Release 命名只产出 Windows 稳定资产；仅把 `.so`/`.dylib` 丢进目录不会自动生成原生 Release 资产，也不会更新 `published_platform_resources`。原生补丁需先按平台扩展发布器资源合同、生成平台原生资产并回读双源，再把对应平台标记为已发布。本轮未上传、未改云端。
- 当前 VM 已同步客户端模块源码；需重启 VM 中活动客户端后，macOS 无原生补丁时应显示资源缺失/禁用一键解锁，而不是成功。

## 发布器补丁列表显示文件大小（2026-09-20）

- 修改范围：`src/signriver_publisher/content_management_ui.py`、`tests/test_publisher_ui_threading.py`。
- 本地资源页的“补丁资源”列表现在在文件名与删除按钮之间显示每个补丁文件大小；使用 B/KB/MB/GB 格式，文件在刷新期间消失时显示“大小未知”。DLC 文件夹列表保持原布局。
- 已执行：`& .\\.venv\\Scripts\\python.exe -m pytest -q tests/test_publisher_ui_threading.py`（通过）；`& .\\.venv\\Scripts\\python.exe -m ruff check src/signriver_publisher/content_management_ui.py tests/test_publisher_ui_threading.py`（通过）；`& .\\.venv\\Scripts\\python.exe -m compileall -q src/signriver_publisher/content_management_ui.py tests/test_publisher_ui_threading.py`（通过）；`git diff --check`（通过）。
- 未执行：发布器 GUI 人工验收、构建发布器 EXE、资源发布和推送；当前源码发布器需重启后查看界面。

## macOS 平台主表兼容修复（2026-09-20）

- 根因：VM 用户目录的远端卡带主表只含 Windows `platform_resources`，启动时优先于包内兼容主表，导致 macOS 默认群星被误判为“暂无资源”。这不是 `.app` 缺少 `0.2.0` 模块。
- 修改：`app/versions/0.1.0/signriver_app/application/cartridge_catalog.py` 的主表选择会跳过不包含当前平台任何资源的候选，优先使用包内兼容主表；同步测试 `tests/test_cartridge_catalog.py`。活动版本目录中的同文件已定向同步，未整目录覆盖。
- 验证：定向卡带/平台测试 46 项通过；Ruff、compileall、`git diff --check` 通过；macOS 原生包重新构建成功，ZIP 完整性、x86_64 Mach-O、签名和包内 `0.2.0` 内容均通过。
- VM：`/Users/signriver/macos-build-20260919/dist/SignRiver-DLC-Hub.app` 已重新打开，客户端进程存活。旧 Windows-only 数据主表已可恢复地备份为 `~/Library/Application Support/SignRiver DLC Hub/data/cartridges/cartridges_index.windows-only-20260920.json`；未删除数据。
- 手动打开路径：Finder 使用 `Command + Shift + G`，输入 `/Users/signriver/macos-build-20260919/dist/SignRiver-DLC-Hub.app`。
- 本轮未执行真实 DLC 下载、补丁生命周期、Steam 登录、游戏内运行、上传、线上清单切换、commit 或 push。

## 发布器同名 DLC 导入覆盖（2026-09-20）

- 修改范围：`src/signriver_publisher/workspace.py`、`tests/test_publisher_workspace.py`。
- 修复同名 DLC 重复导入时递增生成新编号的问题：按安装目录名匹配已有托管目录，并通过暂存备份安全替换；单个 DLC、根目录批量导入、共享文件对和聚合叶目录导入均支持同名覆盖，覆盖失败会恢复旧目录。
- 已新增 `CityStations` 同名覆盖回归测试；替换已有 DLC 不会消耗新的自动编号。
- 已执行：`& .\\.venv\\Scripts\\python.exe -m pytest -q tests/test_publisher_workspace.py tests/test_publisher_ui_threading.py`（通过）；`& .\\.venv\\Scripts\\python.exe -m ruff check src/signriver_publisher/workspace.py tests/test_publisher_workspace.py tests/test_publisher_ui_threading.py`（通过）；`& .\\.venv\\Scripts\\python.exe -m compileall -q src/signriver_publisher tests/test_publisher_workspace.py tests/test_publisher_ui_threading.py`（通过）；`git diff --check`（通过）。
- 未执行：发布器 GUI 人工验收、构建发布器 EXE、资源发布和推送；当前源码发布器需重启后验证界面导入流程。

## macOS 原生构建收尾（2026-09-19）

- 活动客户端版本：`0.2.0`；实际活动模块为 `app/versions/0.2.0/`，本轮采用“正式原生构建”对齐方式，未修改版本号、`app/state.json` 或线上清单。
- Windows 侧工作区在开始和结束时均保持无受跟踪改动；分支 `main`，HEAD `d12a25a47afc2eee17fa4c5d6f2c2a8e07ef3e18`。交接文档此前记录的旧 HEAD 已过时，以 Git 实际状态为准。
- 已执行定向测试：`\.venv\Scripts\python.exe -m pytest -q tests/test_build_native_release.py tests/test_macos_update_helper.py tests/test_cross_platform_runtime.py`，13 项通过。
- 来宾：`D:\vmware\macos-vm\macOS Sequoia.vmx`，通过 VMware Tools 受控通道连接；来宾确认 `Darwin 24.6.0 x86_64`。因系统 Python 仅为 Xcode 占位程序，在 `/Users/signriver/py312` 放置临时 Intel Python 3.12.14，并安装 Command Line Tools for Xcode 16.4 以提供 `install_name_tool`；未修改 VMX、未升级 macOS。
- 构建目录：`/Users/signriver/macos-build-20260919`；命令：`python tools/build_native_release.py --platform macos`，构建状态码 0。
- 来宾产物：`dist/SignRiver-DLC-Hub.app`、`dist/SignRiver-DLC-Hub-v0.2.0-macos-x64.app.zip`、`dist/updates/SignRiver-DLC-Hub-full-v0.2.0-macos-x64.zip`。
- 首装 ZIP（修复后重建）：`24,578,931` bytes，SHA-256 `03C148B01722B00AD52D68D53790AA6EEC67A2B77802CE44982FFDEEEC847C05`；全量更新 ZIP：`24,593,063` bytes，SHA-256 `0E319EAE87EAE0AC77E2839EF9C223F5620B87E7A36C013E2D8DBBCB5AD67BF8`。Windows 侧临时副本位于 `.test-artifacts/fixed-app.zip` 与 `.test-artifacts/fixed-update.zip`。
- 验证通过：两个 ZIP 在来宾 `unzip -t`；主程序 `Mach-O 64-bit executable x86_64` 且 `lipo -info` 为 `x86_64`；`codesign --verify --deep --strict`；`.app` 内 `app/versions/0.2.0/signriver_app/` 80 个文件、`app/state.json.active_version` 为 `0.2.0` 且 `bad_versions` 为空。
- 启动验证：从隔离构建目录用 `open dist/SignRiver-DLC-Hub.app` 启动，观察至少 8 秒有进程记录；无新增 `~/Library/Logs/DiagnosticReports` 崩溃报告；随后仅结束隔离进程，未安装到 `~/Applications`。
- 未执行：真实 DLC 下载、补丁生命周期、Steam 登录、游戏内运行、远端上传、线上清单切换、commit、push；未修改或覆盖用户应用目录。


## 本次任务（Windows 客户端打包，2026-09-13）

- 活动客户端版本：`0.2.0`；按正式 Windows 流程重新构建模块归档和全量更新包。
- 修正 `config/module-archives.json` 中 `0.1.7`、`0.2.0` 归档的大小与 SHA-256，使其与本地新构建产物一致。
- 产物：`dist/updates/SignRiver-DLC-Hub-full-v0.2.0-windows-x64.zip`、`dist/<中文产品名>-v0.2.0-windows-x64.zip`、对应自解压 EXE，以及 `dist/modules/SignRiver-DLC-Hub-module-v0.2.0.zip`。
- 已验证：`build_module.py --all-versions`、`build_release.py --upx-dir ...`、`prepare_update_release.py` 均成功；Windows 全量 ZIP 与 GitLink/GitHub 清单大小和 SHA-256 一致；`git diff --check` 通过。
- Windows 全量 ZIP：`22092217` bytes，SHA-256 `ec410df53833f7b20a102ea3d3a4ff6e6d128bd885eb15f7c3bb16cfa2657dae`。
- 未执行：真实远端上传、发布器批次、GUI 人工验收和推送；用户如需发布，需先上传并完成双源回读核验。

> 本文件只保留当前状态；历史流水见 [`archive/`](archive/)。长期约束见 [`DECISIONS.md`](DECISIONS.md)。

## 当前状态（2026-09-13）

- 分支：`main`
- HEAD：`aac4d6ab8ce77487c6c4ea575319d60d1a1e3760`（本任务提交后以 Git 实际提交为准）
- 活动客户端版本：`0.2.0`，`app/state.json` 与活动模块一致。
- 工作区：本次开始时干净；全量测试问题修复已验证，按项目约定随本次交接提交。

## 最新任务（全量测试修复）

- 修改范围：`src/signriver_publisher/models.py`、`tests/test_client_problem_center.py`。
- `PublisherCartridge.to_dict()` 现在将新增的 `patch_interference_files` 元组显式序列化为 JSON 列表，补齐发布工作区完成清单的稳定序列化契约。
- 同步更新三项已经落后于现有产品行为的客户端测试：补丁应用结果夹具包含干扰文件清理字段；一键解锁成功文案使用当前简化提示；从问题记录打开解决方案时验证来源和返回上下文。
- 已执行：4 个原失败测试定向运行通过；`\.venv\Scripts\python.exe -m pytest -q` 全量 886 项通过；`\.venv\Scripts\python.exe -m ruff check .` 通过；`\.venv\Scripts\python.exe -m compileall -q src app/versions/0.1.0 app/versions/0.2.0` 通过；`git diff --check` 通过。
- 未执行：GUI 人工验收、构建、发布和推送；本任务只修复自动化回归与序列化遗漏。

## 最新任务（界面调整）

- 修改范围：`src/signriver_publisher/ui.py`、`src/signriver_publisher/cartridge_management_ui.py`、`tests/test_publisher_ui_threading.py`、`docs/publisher-guide.md`。
- “DLC 时效检查”已移到发布器左侧独立工作区；结果不再使用弹窗，而是在页面内的可滚动四列表持久展示游戏、资源提交时间、Steam 最新 DLC 上线时间和状态。卡带与公告页已移除该检查按钮与临时状态区域。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests/test_dlc_freshness.py tests/test_publisher_ui_threading.py -k "freshness or cartridge_management or task_oriented_workspace"`（8 项通过）；`\.venv\Scripts\python.exe -m ruff check src/signriver_publisher/ui.py src/signriver_publisher/cartridge_management_ui.py tests/test_publisher_ui_threading.py` 通过；`\.venv\Scripts\python.exe -m compileall -q src/signriver_publisher tests/test_publisher_ui_threading.py` 通过；`git diff --check` 通过。
- 未执行：发布器 GUI 人工验收、完整测试、构建发布器 EXE、资源发布和推送。

## 最新任务

- 修改范围：`src/signriver_publisher/{freshness,workspace,cartridge_management_ui}.py`、`src/signriver_publisher/__init__.py`、`tests/test_dlc_freshness.py`、`tests/test_publisher_ui_threading.py`、`docs/publisher-guide.md`。
- 发布器“游戏支持数据 → 卡带与公告 → 卡带与公告”新增“检查全部 DLC 时效”。任务在后台逐个请求 Steam DLC 上线时间，与当前本地/发布输出的资源提交时间比较；不会写入 AppInfo、改动资源或触发发布。结果会逐项显示“资源过时”“未过时”或“无法判断”。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests/test_dlc_freshness.py tests/test_publisher_ui_threading.py -k "freshness or cartridge_management"`（7 项通过）；`\.venv\Scripts\python.exe -m ruff check src/signriver_publisher/freshness.py src/signriver_publisher/workspace.py src/signriver_publisher/cartridge_management_ui.py src/signriver_publisher/__init__.py tests/test_dlc_freshness.py tests/test_publisher_ui_threading.py` 通过；`\.venv\Scripts\python.exe -m compileall -q src/signriver_publisher tests/test_dlc_freshness.py tests/test_publisher_ui_threading.py` 通过；`git diff --check` 通过。
- 未执行：发布器 GUI 人工验收、完整测试、构建发布器 EXE、资源发布和推送。

## 前次任务

- 修改范围：`app/versions/0.1.0/app_entry.py`、`tests/test_ui_theme.py`；定向同步运行时忽略目录 `app/versions/0.2.0/app_entry.py`。
- 修复切换下载源时始终加载索引默认游戏的问题。现在会捕获并刷新用户当前选中游戏的卡带，避免非默认游戏的完成回调被丢弃、页面永久停在“正在加载”。
- 已采用“定向同步到当前活动模块”：基线和 `0.2.0` 的同一代码块均已更新；用户重启客户端后生效，未构建或发布新版本。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests/test_ui_theme.py`（74 项通过）；`\.venv\Scripts\python.exe -m ruff check app/versions/0.1.0/app_entry.py tests/test_ui_theme.py` 通过；`\.venv\Scripts\python.exe -m compileall -q app/versions/0.1.0 app/versions/0.2.0` 通过；`git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

## 本次任务

- 修改范围：`config/guides/guide_graphics_device_compatibility.json`、`tests/test_platform_content.py`；运行时配置目录直接生效，不修改客户端模块。
- 已删除图形设备指南中的“打开日志资料收集”操作入口；保留图形设备工具入口及联系开发者入口。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests\test_platform_content.py -k graphics`（1 项通过）；`\.venv\Scripts\python.exe -m ruff check tests\test_platform_content.py` 通过；`\.venv\Scripts\python.exe -m compileall -q tests\test_platform_content.py` 通过；`git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

- 修改范围：`config/guides/guide_graphics_device_compatibility.json`、`tests/test_platform_content.py`；运行时配置目录直接生效，不修改客户端模块。
- 已删除图形设备指南中“它仅适用于 Windows，不代表所有启动失败都由图形配置引起”的补充句，以及“修复失败或仍无法启动”标题与其说明段；操作入口与联系开发者入口保留。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests\test_platform_content.py -k graphics`（1 项通过）；`\.venv\Scripts\python.exe -m ruff check tests\test_platform_content.py` 通过；`\.venv\Scripts\python.exe -m compileall -q tests\test_platform_content.py` 通过；`git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

- 修改范围：`config/guides/guide_graphics_device_compatibility.json`、图形设备指南资源、`tests/test_platform_content.py`；运行时配置目录直接生效，不修改客户端模块。
- 图形设备指南已删除旧的“无法创建图形设备”长截图，改为两步说明与新配图：先在工具中打开 DirectX 诊断工具、于“显示”页确认 DirectDraw/Direct3D 加速状态；若显示“未启用”或“已禁用”，关闭诊断工具后点击“修复图形设备配置”。保留修复前备份、用户确认、管理员权限及修复后重启说明。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests\test_platform_content.py -k graphics`（1 项通过）；`\.venv\Scripts\python.exe -m ruff check tests\test_platform_content.py` 通过；`\.venv\Scripts\python.exe -m compileall -q tests\test_platform_content.py` 通过；已视觉核对两张新资源；`git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

- 修改范围：`app/versions/0.1.0/app_entry.py`、两份 P 社启动器指南、`docs/tool-item-ui-spec.md`、`tests/test_ui_theme.py`；定向同步运行时忽略目录 `app/versions/0.2.0/app_entry.py`。
- 统一用户可见名称为“P 社启动器修复”：工具卡片、详情标题和按钮均使用相同表述；指南和工具规范已同步。原内部标识 `paradox-launcher-warning` 保持不变，既有指南跳转兼容。
- 活动客户端版本为 `0.2.0`；已定向同步同一代码块，用户重启客户端后生效，未构建或发布新模块。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests\test_ui_theme.py tests\test_platform_content.py -k paradox_launcher`（2 项通过）；`\.venv\Scripts\python.exe -m ruff check app\versions\0.1.0\app_entry.py tests\test_ui_theme.py` 通过；`\.venv\Scripts\python.exe -m compileall -q app\versions\0.1.0\app_entry.py app\versions\0.2.0\app_entry.py` 通过；旧表述检索无结果；`git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

- 修改范围：`app/versions/0.1.0/app_entry.py`、`tests/test_ui_theme.py`；定向同步运行时忽略目录 `app/versions/0.2.0/app_entry.py`。
- 修复 P 社启动器安装程序下载完成后的 UI 状态：此前“打开安装程序”按钮未保留引用，下载回调只更新卸载按钮，导致已下载时仍禁用；现在回调会将该按钮设为可用。
- 活动客户端版本为 `0.2.0`；已定向同步同一代码块，用户重启客户端后生效，未构建或发布新模块。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests\test_ui_theme.py -k paradox_launcher`（1 项通过）；`\.venv\Scripts\python.exe -m ruff check app\versions\0.1.0\app_entry.py tests\test_ui_theme.py` 通过；`\.venv\Scripts\python.exe -m compileall -q app\versions\0.1.0\app_entry.py app\versions\0.2.0\app_entry.py` 通过；`git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

- 修改范围：`app/versions/0.1.0/app_entry.py`、`tests/test_ui_theme.py`；定向同步运行时忽略目录 `app/versions/0.2.0/app_entry.py`。
- 修复 P 社启动器安装工具：官网按钮改为 `https://www.paradoxinteractive.com/our-games/launcher`；下载安装程序改为官方 `v2/paradox-launcher-installer-windows` 端点，移除旧 `/installer/Paradox%20Launcher.exe` 的 404 地址。用户提供的 `_gl` / `_ga` 统计参数未固化，避免会话参数过期；无参数端点可稳定重定向到当前安装程序。
- 活动客户端版本为 `0.2.0`；已定向同步同一代码块，用户重启客户端后生效，未构建或发布新模块。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests\test_ui_theme.py -k paradox_launcher`（1 项通过）；`\.venv\Scripts\python.exe -m ruff check app\versions\0.1.0\app_entry.py tests\test_ui_theme.py` 通过；`\.venv\Scripts\python.exe -m compileall -q app\versions\0.1.0\app_entry.py app\versions\0.2.0\app_entry.py` 通过；`curl.exe -I -L --max-time 30 -A "SignRiver-DLC-Hub" "https://launcher.paradoxinteractive.com/v2/paradox-launcher-installer-windows"` 返回 302 后 200；`git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

- 修改范围：`app/versions/0.1.0/app_entry.py`、新增 `app/versions/0.1.0/signriver_app/infrastructure/paradox_launcher.py`、`tests/test_paradox_launcher_discovery.py`、`tests/test_ui_theme.py`；定向同步运行时忽略目录 `app/versions/0.2.0/app_entry.py` 和同名基础设施模块。
- 修复 P 社启动器警告清除工具：不再按目录名字符串排序，而是按全部数字版本段比较；并且仅接受同时包含 `Paradox Launcher.exe`、`resources/app.asar` 与目标 `steam_api64.dll` 的完整安装目录。`.cpatch` 单独存在的残缺版本目录会被忽略。
- P 社启动器修复的原始 DLL 备份名已统一为 `steam_api64_o.dll`，与普通游戏补丁链路一致；此前仅这条专用路径错误使用 `steam_api64.original.dll`。
- 活动客户端版本为 `0.2.0`；已定向同步同一逻辑，用户重启客户端后会优先处理完整的 `launcher-v2.2026.11.1`，而不是错误选中 `launcher-v2.2026.8.1`；未构建或发布新模块。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests/test_paradox_launcher_discovery.py tests/test_ui_theme.py -k "paradox_launcher"`（3 项通过）；`\.venv\Scripts\python.exe -m ruff check app/versions/0.1.0/app_entry.py app/versions/0.1.0/signriver_app/infrastructure/paradox_launcher.py tests/test_paradox_launcher_discovery.py` 通过；`\.venv\Scripts\python.exe -m compileall -q app/versions/0.1.0/app_entry.py app/versions/0.1.0/signriver_app/infrastructure/paradox_launcher.py app/versions/0.2.0/app_entry.py app/versions/0.2.0/signriver_app/infrastructure/paradox_launcher.py` 通过；`git diff --check` 通过。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests/test_paradox_launcher_discovery.py tests/test_ui_theme.py -k "paradox_launcher"`（3 项通过）；`\.venv\Scripts\python.exe -m pytest -q tests/test_ui_theme.py -k paradox_launcher`（1 项通过）；`\.venv\Scripts\python.exe -m ruff check app/versions/0.1.0/app_entry.py app/versions/0.1.0/signriver_app/infrastructure/paradox_launcher.py tests/test_paradox_launcher_discovery.py` 与 `\.venv\Scripts\python.exe -m ruff check app/versions/0.1.0/app_entry.py tests/test_ui_theme.py` 均通过；两轮 `compileall` 与 `git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

## 最近结论

- 已确认 `0.1.5 → 0.2.0` 报错的主要发布风险是同版本存在多套包，且 GitHub、GitLink、本地清单的大小/SHA-256 不一致。
- `0.2.0` 使用 Host API 3；最低启动器版本必须以真实冻结包 E2E 验证结果为准，不能只依据清单可解析来声明兼容。
- 详细事故记录已归档至 [`HANDOFF-2026-09-04-history.md`](archive/HANDOFF-2026-09-04-history.md)。

## 当前风险与下一步

- 本次修复降低跨源失败造成的半套发布窗口，但同一源站的远端附件替换仍依赖 provider 的幂等恢复；未实现远端附件内容备份/事务回滚。
- 后续发布必须执行单一构建产物、双源回读校验，以及仍受支持旧启动器到新版本的更新矩阵测试。
- 线上发布前需确认远端清单和附件完全匹配；不得使用 `dist`、`publisher-workspace/output` 或历史包中的旧清单。
- 未完成：真实远端包完整下载复核、下一版本发布门禁自动化；均不得写成已验证。

## 最近验证

- `python -m pytest -q tests/test_full_update.py tests/test_updater.py tests/test_loader.py tests/test_state.py tests/test_versioning.py tests/test_release_build.py tests/test_build_module.py tests/test_restore_module_archives.py`：通过。
- `python -m compileall -q src app/versions/0.1.0 app/versions/0.2.0 tools`：通过。
- `git diff --check`：通过。
- 未执行 GUI、真实上传、推送或完整远端包下载。
## 最新任务（SteamOS 原生构建）

- 已将当前工作区源码（含未提交的跨平台补丁选择与索引过滤修复）及活动模块 `0.2.0` 同步到 SteamOS VMware 虚拟机，在 `Linux x86_64` / Python 3.13.5 环境内建立隔离构建环境并运行 `python tools/build_native_release.py --platform steamos`。
- 已生成并复制回工作区：`[SignRiver-DLC-Hub-v0.2.0-steamos-x64.tar.gz](../../.test-artifacts/steamos-dist/SignRiver-DLC-Hub-v0.2.0-steamos-x64.tar.gz)`（44,531,151 字节，SHA-256 `db26e35a01ca6358f9960de27e1ab56f2763d5c570ac187684f1a1da343fe352`）和 `[SignRiver-DLC-Hub-full-v0.2.0-steamos-x64.zip](../../.test-artifacts/steamos-dist/SignRiver-DLC-Hub-full-v0.2.0-steamos-x64.zip)`（44,749,426 字节，SHA-256 `14c410fa557cf0704f0e1104c7c052ab7006ab26d8e0d20d58b9305dd1286ec1`）。
- 已验证：tar.gz 可解包；ZIP `testzip` 通过；两个包均含 `app/state.json` 与完整 `app/versions/0.2.0/`；活动版本为 `0.2.0`；主程序为 ELF 64-bit x86-64（机器类型 62）。已在虚拟机中直接启动主程序观察 8 秒，进程保持运行至超时退出（退出码 124），未报告启动崩溃。
- 已执行定向测试：`tests/test_build_native_release.py`、`tests/test_cross_platform_runtime.py`、`tests/test_patch_platforms.py`、`tests/test_dlc_catalog.py`、`tests/test_cartridge_catalog.py`、`tests/test_platform_content.py`，全部通过。未执行真实 DLC 下载、补丁生命周期、Steam 登录、远端上传、线上清单切换、commit 或 push。
- 当前活动模块对齐方式：本次使用源码归档中的完整 `app/versions/0.2.0/` 进行正式 SteamOS 构建；未修改 `app/state.json`，用户运行该包前无需额外同步。SteamOS VM 保持运行，macOS VM 已挂起。
## 最新任务（SteamOS/macOS 平台专属指南与组件适配）

- 修改范围：`config/guides/{guides_index,guide_network_basics,guide_game_directory_missing,guide_disk_space,guide_patch_state,guide_update_module_basics}.json`、`docs/tool-item-ui-spec.md`、`app/versions/0.1.0/{app_entry.py,signriver_app/application/guides.py,signriver_app/infrastructure/diagnostics/support_bundle.py}`，以及对应 `0.2.0` 活动模块同步文件和定向测试。
- 指南目录新增平台文案能力：索引支持 `title_by_platform`/`summary_by_platform`，正文支持 `platform_text` 与块级 `platforms` 过滤。SteamOS/macOS 的补丁指南明确只接受原生 `.so`/`.dylib`，不再显示 `unlock.dll`、Windows Defender 或 Windows 专属替代方案；游戏目录、网络、磁盘空间和更新指南同步说明 Steam 库、兼容层、`.app` 和原生包差异。
- 补丁工具组件按当前平台显示“SteamOS 原生补丁”/“macOS 原生补丁”，下载提示使用真实补丁文件数量；日志资料收集组件按平台显示系统信息类型。资料收集器现在在 SteamOS 收集 `uname` 与 `/etc/os-release`，在 macOS 收集精简 `system_profiler` 信息，并为 Paradox 日志增加 macOS `Library/Application Support` 与 SteamOS `~/.local/share` 路径。
- 当前活动版本：`0.2.0`；采用“基线实现 + 定向同步到当前活动模块”，未修改 `app/state.json`。用户重启活动客户端后生效；本轮未重新构建或发布原生包。
- 已执行：`pytest -q tests/test_platform_content.py tests/test_support_bundle.py tests/test_support_collection_ui.py tests/test_ui_theme.py tests/test_diagnostics.py tests/test_dlc_catalog.py tests/test_cartridge_catalog.py tests/test_cross_platform_runtime.py`（全部通过）；Ruff、compileall、`git diff --check` 均通过。未执行 GUI 人工验收、云端资源上传、线上清单切换、commit 或 push。
## SteamOS 干净基线快照（2026-09-21）

- 已创建关机状态快照 `20260921-可用基线`（无内存文件，确认是 poweroff 后拍摄）。当前快照链：`steamos-installed-plasma-x11` → `下载stellaris` → `20260921-可用基线`。
- 制作过程：停掉 Steam 与客户端程序 → 写入游戏库登记（`~/.local/share/Steam/{steamapps,config}/libraryfolders.vdf`）→ `systemctl poweroff` → `vmrun snapshot`。首次拍摄误在关机过程中进行（带了 8 GB 内存文件），已删除并重拍；期间遇到残留 `.vmx.lck`（持有者 PID 已不存在），将其改名释放后快照成功。
- 基线内容：Stellaris 28 GB（`~/Games/SteamLibrary/steamapps/common/Stellaris`，3 个 appmanifest，`StateFlags=4`）；客户端发布包已部署（`~/signriver-steamos-build`）且 `~/.local/share/signriver-dlc-hub` 数据目录正常；`~/register-steam-library.sh` 与 `~/Games/SteamLibrary/libraryfolders.vdf.backup` 用于重新登记游戏库。
- 已知情况：该基线的 Steam 客户端仍处于"已下载但未落地"的历史状态（`package/*.installed` 缺失）。首次启动 Steam 时它会自动补装客户端（约 496 MB，2–3 分钟）；**补装会重建 `~/.local/share/Steam`，但不会再删除游戏**（游戏已在 Steam 根目录之外）。补装并登录后若库里未显示 Stellaris，执行 `~/register-steam-library.sh` 再重启 Steam，或在 设置 → 存储空间 → 添加驱动器 中选择 `/home/deck/Games/SteamLibrary`（不会重新下载）。
- 经验：SteamOS 正常启动参数带 `-skipinitialbootstrap`；在客户端有未应用更新时用该参数启动会导致"下载→不安装→下次再下载"的循环，此时用 `steam.sh -steamdeck`（不带该参数）可让更新真正落地。

## 游戏库迁移与三项恢复（SteamOS，2026-09-21）

- 二次事故：用户尝试打开 Steam 时，Steam 再次自我重装客户端并清空 `~/.local/share/Steam`，游戏库第二次被删（已由快照恢复）。定位到快照 `下载stellaris` 是在 **Steam 客户端更新途中**拍的（`package/` 只有 `beta`，没有 `*.installed`），因此该快照下每次启动 Steam 都会触发一次完整客户端重装。
- 已完成迁移（游戏库移出 Steam 根目录）：`~/.local/share/Steam/steamapps/{common,downloading,appmanifest_*.acf}` → `~/Games/SteamLibrary/steamapps/`；并在 `steamapps/libraryfolders.vdf` 与 `config/libraryfolders.vdf` 两个位置登记第二个库（`/home/deck/Games/SteamLibrary`）。之后 Steam 再重装客户端只会重建客户端，不会再删除游戏。
- 当前状态：Stellaris 28 GB 位于 `/home/deck/Games/SteamLibrary/steamapps/common/Stellaris`（`appmanifest_281990.acf` 状态 `StateFlags=4`）；Steam 客户端已更新完成并显示登录窗口（客户端重装导致登录状态丢失，需重新登录一次）；`dolphin` 已打开该目录；我们的客户端已重新部署并运行（`signriver-check.service` active，模块 `0.2.0`）。
- 注意事项：不要在 Steam 运行时改动来宾系统时钟（历史事故触发条件之一）；本 VM 的快照仍保留一份未完成客户端安装的状态，若回退到该快照会再次触发客户端重装（对已迁移的游戏库无害）。

## 事故与恢复（SteamOS 快照回退，2026-09-21）

- 事故：本机对 SteamOS VM 执行时钟校正（`systemctl restart systemd-timesyncd`）时时钟一次性前跳 18 小时 33 分；11 秒后 Steam 启动脚本判定客户端异常，执行 `rm -rf ~/.local/share/Steam` 自我重装，而 SteamOS 默认游戏库 `steamapps/` 位于该目录内，导致约 29 GB 游戏数据（含 Stellaris）被删除。证据：`journalctl -b -1` 中 `14:14:58 Initial clock synchronization` 紧随 `14:15:09 steam[...]: rm: cannot remove '/home/deck/.local/share/Steam': Directory not empty` 与 `app-steam@*.service ... status=1/FAILURE`。用户重启发生在 14:24，晚于删除，不是原因。
- 恢复：将 VM 回退到快照 `下载stellaris`（磁盘 `steamos-target-128gb-000001.vmdk`，31.4 GB），Steam 客户端与 Stellaris（32 GB 库）恢复；回退同时丢弃了当天的虚拟机部署，已按下方重新完成。
- 教训：**不要在任何 Steam 客户端可能运行/被启动的时刻改动来宾系统时钟**；正确做法是确保 Steam 完全停止后再校正时间，并把游戏库放在 `~/.local/share/Steam` 之外，避免客户端自我重装时连带删除游戏。
- 我方引入的第二个缺陷：源码归档排除规则曾按“路径任意一层名为 cache 即排除”，误删模块内的 `signriver_app/infrastructure/cache` 包，导致 SteamOS 部署后 `ModuleNotFoundError: _signriver_app_0_2_0.signriver_app.infrastructure.cache`。已改为仅排除仓库顶层运行目录（`data`、`cache`、`build`、`dist` 等），并核对模块文件数与仓库一致（80/80）。

## 最新任务（SteamOS 快照回退后重新交付，2026-09-21）

- 重新生成 5,215,935 字节源码归档并覆盖解压到 `~/signriver-steamos-build`，重建 `.venv-steamos`（Python 3.13.5 + PyInstaller 6.22.3），执行 `tools/build_native_release.py --platform steamos`（rc=0）。
- 包内校验：ELF 64-bit x86-64、755、`app/versions/0.2.0/signriver_app` 80 文件、`config/guides` 19 项 / 16 条索引（含 `patch_assets_missing`、`steamos-app-permission`、`steamos-proton-native`）；`tar -tzf` 与 ZIP 校验通过（500 项，testzip 为空）。
- 部署：清掉用坏包播种的 `~/.local/share/signriver-dlc-hub/app/versions/0.2.0` 后重新播种（83 文件），客户端经 `systemd-run --user` 启动并保持运行，日志 `Starting application module 0.2.0` 无错误。
- 端到端：包内模块 + 包内配置解析到 `dist/.../config/guides`，SteamOS 侧 8 条指南全部加载成功。
- 新产物（已回传 `.test-artifacts/steamos-dist/`，与来宾 `sha256sum` 一致）：`SignRiver-DLC-Hub-v0.2.0-steamos-x64.tar.gz` 44,547,181 字节 SHA-256 `A494C9679B71F0FEEFC3C66C781DE4588EDDB109FE27DFCC957481EC51DEB2B7`；`SignRiver-DLC-Hub-full-v0.2.0-steamos-x64.zip` 44,763,958 字节 SHA-256 `3B77CEC4F11B97111D5C2B22CE9BC562C9D5F2820F132C75A4C68019CFAFA4D5`。
- 时钟：已在 Steam 停止状态下重新校正为 `Asia/Shanghai` 并启用 NTP，与宿主机一致。
- 未完成/待办：游戏库仍在 `~/.local/share/Steam` 内，存在再次被客户端自我重装删除的风险，建议迁移到独立库目录（待用户确认后执行）。未执行上传、清单切换、发布器批次、Steam 登录、真实 DLC 下载、push。

## 最新任务（SteamOS 原生重建与部署，2026-09-21）

- 在 SteamOS VM（`deck@192.168.233.130`）完成与 macOS 等价的交付：备份 → 源码同步 → 原生重建 → 覆盖部署 → 数据目录模块重新播种 → 启动验证 → 产物回传。
- 备份（回滚用）：`~/.local/share/signriver-dlc-hub/app/versions/0.2.0.bak-20260921`、`~/.local/share/signriver-dlc-hub/app/state.json.bak-20260921`、`~/signriver-steamos-build/dist/SignRiver-DLC-Hub-steamos-x64.bak-20260921`，以及旧 `*.tar.gz.bak-20260921`、`*.zip.bak-20260921`。
- 源码归档：5,202,470 字节 / 722 文件，排除 `.git`、`.venv`、`build`、`dist`、`data`、`cache`、`.test-artifacts`、`publisher-workspace`、缓存与凭据，但保留被 Git 忽略的 `app/versions/0.2.0`；SFTP 上传后覆盖解压到 `~/signriver-steamos-build`，`.venv-steamos`、`build`、`dist` 均保留。
- 构建：`.venv-steamos/bin/python tools/build_native_release.py --platform steamos`（rc=0）。包内校验：ELF 64-bit x86-64、权限 755、`app/versions/0.2.0/signriver_app` 80 个文件、`config/guides` 19 项 / 16 条索引（含 `patch_assets_missing`、`steamos-app-permission`、`steamos-proton-native`）；`tar -tzf` 与 ZIP 完整性通过（512 项，testzip 为空）。
- 部署：删除数据目录旧模块以触发 `paths.ensure()` 重新播种；播种后模块含新代码标记（`resolve_bootstrap_dir`=2、`platform_text`=1），共 83 个文件；数据目录 `state.json` 保持 `active_version=0.2.0`、`bad_versions` 为空。
- 启动验证：`DISPLAY=:0` 启动后进程存活（PID 17899/17901），日志出现 `Starting application module 0.2.0`，无模块加载或指南加载错误；窗口保持打开供用户查看。
- 端到端证明：用包内模块加载包内配置运行 `resolve_bootstrap_dir` + `GuideCatalogService(platform="steamos")`，解析到包内 `config/guides`，SteamOS 侧 8 条指南全部加载且正文为 SteamOS 专属文案。
- 新产物（已回传 `.test-artifacts/steamos-dist/`，与来宾 `sha256sum` 完全一致）：`SignRiver-DLC-Hub-v0.2.0-steamos-x64.tar.gz` 44,547,367 字节 SHA-256 `6BEF73F1BA663D706210D6D4AB0CDD9A7910A135E65F0254C40A8FE96E466A64`；`SignRiver-DLC-Hub-full-v0.2.0-steamos-x64.zip` 44,763,988 字节 SHA-256 `CEB0E75AB1FF82B39E39D637CBED69999A49382ED101355611864DA7CAC14E96`。
- 本轮未改任何仓库代码（未发现 SteamOS 专属缺陷）。SteamOS VM 时钟已于 2026-09-21 校正：该机未装 open-vm-tools，虚拟机挂起/恢复后 `systemd-timesyncd` 未重新同步，导致时钟落后宿主机 18 小时 33 分；执行 `sudo systemctl restart systemd-timesyncd` 后立即通过 NTP 校正，并把时区统一为 `Asia/Shanghai`、回写 RTC，现与宿主机一致（差异 ≤1 秒）。若再次挂起后出现时间偏差，同样用该命令修复。
- 未执行：上传发布包、线上清单切换、发布器批次、Steam 登录、真实 DLC 下载、补丁生命周期、push。

## 最新任务（清理日志收集的用户可见“跳过/忽略”措辞，2026-09-21）

- 背景：日志资料收集完成弹窗原样显示内部候选路径统计（“已整理 4 个文件；跳过 27 项；失败 0 项”），用户无法得知含义且容易误解为异常。内部 `skipped`/`skipped_dumps` 字段保留，仅调整用户可见文案。
- 修改：`SupportCollectionResult.summary` 改为“已整理 N 个文件。”；收集工具默认提示去掉“未找到的文件会安全跳过”；崩溃转储提示改为“另有 N 个崩溃转储（.dmp）体积较大，未一并打包”；一键排错中不可捕获输出的工具改为“未运行（…）”；一键解锁进度文案改为“已有 N 项无需重新下载”。基线与活动模块 `0.2.0` 同步。
- 契约：`docs/tool-item-ui-spec.md` 明确“跳过/忽略”计数不得出现在用户可见文案，只用于内部与诊断明细。
- 测试：`tests/test_support_bundle.py` 新增 summary 不含跳过/忽略/失败的用例，`tests/test_support_collection_ui.py` 新增客户端措辞回归用例；全量 `pytest -q`、Ruff、compileall、`git diff --check` 通过。
- macOS VM：模块文件已同步到用户目录模块副本、`.app` 内置运行时和隔离源码目录，重新临时签名并验证通过，应用已重启（22:47 启动）供用户查看。
- 未执行：完整 macOS/SteamOS 原生重新构建、真实 DLC 下载、补丁生命周期、上传、线上清单切换、push。

## 最新任务（修复 SteamOS/macOS 指南列表为空，2026-09-21）

- 根因：客户端固定从 `paths.root/config/guides` 读取指南，但启动器 `_seed_packaged_runtime()` 从不把 `config/guides` 复制到可写根目录；Windows 上 `root` 即安装目录所以正常，macOS/SteamOS 上 `root` 是用户数据目录，导致「解决方案」列表整页为空且不报错。macOS 日志中留有 2026-09-19 的“未找到对应教程”记录作为旁证。
- 修改：`signriver_app/application/guides.py` 新增 `resolve_bootstrap_dir()`，按候选目录中是否真实存在 `guides_index.json` 选择指南根；`app_entry.py` 新增 `_guide_bootstrap_candidates()`，候选顺序为 `paths.install/config/guides`、`paths.install/Contents/Resources/runtime/config/guides`、`paths.root/config/guides`。基线与活动模块 `0.2.0` 同步实现。
- 测试：`tests/test_platform_content.py` 新增 `resolve_bootstrap_dir` 选择规则用例与客户端装配断言；全量 `pytest -q`、Ruff、compileall、`git diff --check` 通过。
- macOS VM：模块三件（`app_entry.py`、`application/guides.py`、`application/__init__.py`）已同步到用户目录模块副本、`.app` 内置运行时模块和隔离源码目录，并重新临时签名且通过 `codesign --verify --deep --strict`；`open` 启动后进程存活，新进程日志无指南加载错误。用户在虚拟机上直接查看「解决方案」列表即可确认。
- 未执行：完整 macOS/SteamOS 原生重新构建、真实 DLC 下载、补丁生命周期、上传、线上清单切换、push。

## 最新任务（补丁资源缺失与原生平台专项解决方案，2026-09-21）

- 根因一：客户端多处引用指南 id `patch_assets_missing`（主界面“补丁资源缺失，暂无法一键解锁”提示的跳转目标），但 `guides_index.json` 中从未存在该指南，点击后只会提示“未找到对应教程”。现已新增 `config/guides/guide_patch_assets_missing.json` 与索引项（`platforms: ["all"]`），并用 `platform_text` 分别说明 Windows 资源、SteamOS 原生 `.so`、macOS 原生 `.dylib`，明确禁止把 Windows `.dll` 改名混用。
- 根因二：macOS 客户端从 `~/Library/Application Support/SignRiver DLC Hub/app/versions/0.2.0/` 加载模块，而此前只更新了 `.app/Contents/Resources/runtime/`，用户目录模块副本仍是旧代码，因此日志收集卡片继续显示“Windows DxDiag.txt”，且旧 `guides.py` 不认识 `platform_text`，平台化指南正文被整体丢弃。现已把最新模块文件同步到用户目录模块副本。
- 新增平台专项指南：`macos-app-blocked`（Gatekeeper 拦截与“已损坏”）、`macos-game-not-unlocked`（补丁后仍未解锁）、`steamos-app-permission`（可执行权限与桌面模式）、`steamos-proton-native`（通过 Proton 运行时原生补丁不生效）。
- 契约同步：`docs/tool-item-ui-spec.md` 增加“补丁资源缺失与原生平台专项指南”一节，并明确任何 `_open_solution_article(<id>)` 引用都必须同时提供同 id 的索引项和详情文件。
- 验证：`tests/test_platform_content.py` 新增“客户端引用的指南 id 必须存在”和平台专项指南覆盖用例，全量 `pytest -q` 通过；Ruff、`git diff --check` 通过。
- macOS VM：新指南已同步到 `/Users/signriver/macos-build-20260919/config/guides`、`.app/Contents/Resources/runtime/config/guides`，并重新临时签名且通过 `codesign --verify --deep --strict`；用户目录模块副本已更新（`app_entry.py`/`guides.py` 新代码标记已核对）。需完全退出后重新打开客户端才会生效。
- 未执行：完整 macOS/SteamOS 原生重新构建、真实 DLC 下载、补丁生命周期、上传、线上清单切换、push。

## 最新操作（macOS VM 同步最新活动模块，2026-09-21）

- macOS VM `D:\\vmware\\macos-vm\\macOS Sequoia.vmx` 已通过 VMware Tools 受控通道同步当前活动模块 `0.2.0` 的最新 `app_entry.py`、指南/诊断/卡带目录/DLC 目录模块，以及 `config/guides/` 平台指南文件。
- 同步目标包括隔离源码目录 `/Users/signriver/macos-build-20260919/` 和现有测试包 `/Users/signriver/macos-build-20260919/dist/SignRiver-DLC-Hub.app/Contents/Resources/runtime/`；未覆盖用户 `~/Applications` 安装目录或用户数据目录。
- 修改 `.app` 内运行时后已在来宾内使用临时签名重新签署，并通过 `codesign --verify --deep --strict`；未启动客户端，等待用户在 Finder 手动双击查看。
- 手动打开路径：`/Users/signriver/macos-build-20260919/dist/SignRiver-DLC-Hub.app`。本次未重新执行完整 macOS 原生构建、未上传、未切换线上清单、未 commit 或 push。
