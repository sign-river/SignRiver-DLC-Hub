# 当前任务交接

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
