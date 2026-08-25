# 全局约定

- 所有对用户的回复一律使用中文（代码、命令、报错原文、专有名词除外）。

# 上下文切换约定（所有 AI 必须遵守）

- 新任务开始并准备修改文件前，依次阅读：`docs/agent/README.md`、`docs/agent/PROJECT_CONTEXT.md`、`docs/agent/DECISIONS.md`、`docs/agent/HANDOFF.md`。
- 读取交接后必须核对当前分支、HEAD、`git status --short` 和相关测试；交接与真实工作区冲突时，以代码、Git 和可重复测试结果为准。
- 禁止为了“恢复干净状态”而重置、清理或覆盖用户已有未提交改动。
- 任务结束或准备切换时，更新 `docs/agent/HANDOFF.md` 中的目标、改动范围、验证结果、风险和下一步；长期有效的方案与失败经验同步到 `docs/agent/DECISIONS.md`。
- `HANDOFF.md` 不得保存密码、令牌、Cookie、Apple/Steam 账号、私有下载凭据或大段原始日志；未执行的测试必须明确标为未执行。
- 临时任务、一次性报错和短期下一步不得写入 `AGENTS.md`；只有长期规则才能进入本文件。

# 任务规模与验证效率约定（所有 AI 必须遵守）

- 开始执行前应按影响范围和风险判断任务规模。对于文案、样式、局部布局、单文件小修复等范围明确的简单任务，优先走最短闭环交付；不得为了形式上的流程完整而扩大排查、人工操作、测试、构建或发布范围。
- 验证默认采用最小必要集：语法或静态检查（适用时）+ 直接受影响的定向测试 + 用户明确要求或风险确实需要的验证。不得默认运行无关的全量测试、完整构建、发布流程、跨平台验收或长时间 GUI 操作。
- 只有公共基础设施、跨模块行为、发布或更新链路、安全、数据迁移、并发等高风险改动，或定向验证无法覆盖关键风险时，才扩大验证范围；扩大前应明确说明原因。
- 用户只要求立即查看局部界面效果时，优先启动对应源码并检查受影响页面；不要顺带执行上传、发布、打包等无关操作。
- 交付时应简洁说明已执行的定向验证与未执行项；不得把“流程完整”作为拖慢简单任务的理由，也不得以效率为由省略必要验证。

# 客户端运行版本对齐（所有 AI 必须遵守）

- `app/versions/0.1.0/` 是 Git 跟踪的客户端源码基线，不等于当前实际运行的模块。任何客户端功能、界面或报错修复开始前，必须读取 `app/state.json` 的 `active_version`，并确认对应的 `app/versions/<active_version>/module.json` 是否存在；不得把 `0.1.0`、`0.2.0` 或任何具体版本号写死在流程、脚本或结论中。
- 修改基线后、向用户声称“当前客户端已看到/已可用”之前，必须明确选择并记录以下之一：**仅基线实现**（当前运行模块尚未包含，不能声称 GUI 已生效）、**定向同步到当前活动模块**（只前移本任务相关文件/代码块，绝不整目录覆盖活动版本的独立改动）、或**按正式发布流程构建并切换目标版本**。
- 只要任务涉及当前客户端界面、行为验证或要求用户立即查看结果，必须用 `active_version` 动态定位实际模块，并针对该模块做至少一次可重复验证（例如模块导入、离线功能加载、针对性测试或源码启动）。仅验证 `0.1.0` 不足以证明当前客户端已生效。
- 提交前与交接时必须在 `HANDOFF.md` 写明：实际活动版本、采用的对齐方式、验证对象，以及是否需要用户重启客户端。活动模块目录可能被 Git 忽略；不得因此遗漏运行时同步，也不得把本地同步误报为已经发布。
- 若活动模块与基线存在正常的版本差异，优先按功能范围做人工前移或通过发布流程生成新版本；禁止为“保持一致”而盲目复制整个基线目录、覆盖未知变更，或擅自修改 `app/state.json`。

# Git 提交 / 推送约定（所有 AI 必须遵守）

- **每次任务完成并通过相关验证后，默认创建一次本地 Git commit。** 提交前必须确认提交范围只包含本任务改动；发现其他未提交改动时，不得使用 `git add -A`，应精确暂存本任务文件。
- **每次代码提交（commit）后，禁止自动推送（push）到 GitHub。**
- 推送由用户负责：用户会在上传对应发布包（模块归档、更新包、清单等）之后手动执行 `git push origin main`。
- 原因：CI 会在 push 后立即运行 `restore_module_archives.py`，从线上 GitLink 恢复模块并校验 sha256；如果代码/归档已提交但线上包还没上传，CI 必然报错。
- 只有用户明确说"推送"或"提交并推送"时，才执行 `git push`；“提交并推送”仍必须先完成本地 commit，再执行 push。
- 若验证失败、提交范围无法安全区分，或用户明确要求暂不提交，则应说明原因并保留未提交状态。

# 构建 / 发布流程约定（所有 AI 必须遵守）

## 更新说明（重要）

- 每次构建新版本（例如 0.1.7）并准备发布时，**必须同步完善** `publisher-workspace/update-notes.json` 中该版本的更新说明：
  - 键为版本号（如 `"0.1.7"`），值为面向普通用户的**中文说明**，列出本次改动要点（修复、新增、优化），结尾加"建议尽快更新。"。
  - 该文件是发布器「程序更新发布」对话框的默认文案来源，用户只负责修改/确认，不应从零手写。
  - `publisher-workspace/` 被 Git 忽略，文件仅存于本地工作区，但每次构建都必须维护它。

## 标准构建步骤

1. 改代码先改 `app/versions/0.1.0/`（唯一被 Git 跟踪的模块源码），再同步到目标版本目录（如 `app/versions/0.1.7/`）。
2. 更新 `publisher-workspace/update-notes.json` 中该版本说明。
3. `tools/build_module.py --all-versions app\versions`（构建模块归档，清理 `dist/modules` 中的 `0.1.0` 产物）。
4. `tools/build_release.py --upx-dir C:\Users\32173\AppData\Local\tools\upx\upx-5.0.2-win64`（全量更新包）。
5. `tools/prepare_update_release.py dist\updates\SignRiver-DLC-Hub-full-v<版本>-windows-x64.zip --version <版本> --kind full --min-launcher-version 0.1.2 --notes "<更新说明>" --mandatory`（双源清单，notes 与 update-notes.json 保持一致；PowerShell 传中文参数会乱码，用 Python subprocess 调用）。
6. 同步 `config/module-archives.json` 的 `sha256` / `size`（模块维护基线：最近 3 个版本）。

## 其他注意

- 版本切换需同步：`src/signriver_launcher/constants.py` 的 `LAUNCHER_VERSION`、`app/state.json` 的 `active_version`（并清空 `bad_versions`）。
- 发布器界面代码在 `src/signriver_publisher/`；日常开发验证默认使用 `\.venv\Scripts\python.exe publisher.py` 直接运行源码，不必重新构建 EXE。仅在用户明确要求“构建发布器”、需要交付 EXE 或准备正式发布时，才用 `tools/build_publisher.py --upx-dir ...` 重新构建 `dist/publisher/SignRiver-Publisher.exe`。
- 客户端 UI 代码在 `app/versions/0.1.0/app_entry.py`；改动后同步到目标版本目录再构建。
- 发布器暂停按钮 / 更新说明对话框等上传流程如有改动，必须跑 `tests/test_publisher_ui_threading.py`。
- 发布新版本时，若旧版本（如 0.1.6）已发布，必须用更高的新版本号（如 0.1.7）承载后续修复，否则旧版本用户检测不到更新。
