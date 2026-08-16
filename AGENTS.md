# 全局约定

- 所有对用户的回复一律使用中文（代码、命令、报错原文、专有名词除外）。

# 上下文切换约定（所有 AI 必须遵守）

- 新任务开始并准备修改文件前，依次阅读：`docs/agent/README.md`、`docs/agent/PROJECT_CONTEXT.md`、`docs/agent/DECISIONS.md`、`docs/agent/HANDOFF.md`。
- 读取交接后必须核对当前分支、HEAD、`git status --short` 和相关测试；交接与真实工作区冲突时，以代码、Git 和可重复测试结果为准。
- 禁止为了“恢复干净状态”而重置、清理或覆盖用户已有未提交改动。
- 任务结束或准备切换时，更新 `docs/agent/HANDOFF.md` 中的目标、改动范围、验证结果、风险和下一步；长期有效的方案与失败经验同步到 `docs/agent/DECISIONS.md`。
- `HANDOFF.md` 不得保存密码、令牌、Cookie、Apple/Steam 账号、私有下载凭据或大段原始日志；未执行的测试必须明确标为未执行。
- 临时任务、一次性报错和短期下一步不得写入 `AGENTS.md`；只有长期规则才能进入本文件。

# Git 提交 / 推送约定（所有 AI 必须遵守）

- **每次代码提交（commit）后，禁止自动推送（push）到 GitHub。**
- 推送由用户负责：用户会在上传对应发布包（模块归档、更新包、清单等）之后手动执行 `git push origin main`。
- 原因：CI 会在 push 后立即运行 `restore_module_archives.py`，从线上 GitLink 恢复模块并校验 sha256；如果代码/归档已提交但线上包还没上传，CI 必然报错。
- 例外：只有用户明确说"推送"或"提交并推送"时，才执行 `git push`。

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
- 发布器界面代码在 `src/signriver_publisher/`；改完用 `tools/build_publisher.py --upx-dir ...` 重新构建 `dist/publisher/SignRiver-Publisher.exe`。
- 客户端 UI 代码在 `app/versions/0.1.0/app_entry.py`；改动后同步到目标版本目录再构建。
- 发布器暂停按钮 / 更新说明对话框等上传流程如有改动，必须跑 `tests/test_publisher_ui_threading.py`。
- 发布新版本时，若旧版本（如 0.1.6）已发布，必须用更高的新版本号（如 0.1.7）承载后续修复，否则旧版本用户检测不到更新。