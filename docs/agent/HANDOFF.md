# 当前任务交接

> 本文件只保留当前状态；历史流水见 [`archive/`](archive/)。长期约束见 [`DECISIONS.md`](DECISIONS.md)。

## 当前状态（2026-09-13）

- 分支：`main`
- HEAD：`377c9a4ae35ae410ed01cbd911bbd2079946e255`（本任务提交后以 Git 实际提交为准）
- 活动客户端版本：`0.2.0`，`app/state.json` 与活动模块一致。
- 工作区：开始时无未提交改动；本任务的 DLC 新鲜度提示改动已验证，待本地提交。

## 前次任务

- 修改范围：`app/versions/0.1.0/app_entry.py`、`tests/test_ui_theme.py`；定向同步运行时忽略目录 `app/versions/0.2.0/app_entry.py`。
- 修复切换下载源时始终加载索引默认游戏的问题。现在会捕获并刷新用户当前选中游戏的卡带，避免非默认游戏的完成回调被丢弃、页面永久停在“正在加载”。
- 已采用“定向同步到当前活动模块”：基线和 `0.2.0` 的同一代码块均已更新；用户重启客户端后生效，未构建或发布新版本。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests/test_ui_theme.py`（74 项通过）；`\.venv\Scripts\python.exe -m ruff check app/versions/0.1.0/app_entry.py tests/test_ui_theme.py` 通过；`\.venv\Scripts\python.exe -m compileall -q app/versions/0.1.0 app/versions/0.2.0` 通过；`git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

## 本次任务

- 修改范围：`src/signriver_publisher/{cream,steam,freshness,workspace}.py`、`app/versions/0.1.0/signriver_app/domain/cartridges.py`、`tests/test_dlc_freshness.py`、`tests/test_publisher_workspace.py`、`docs/publisher-guide.md`；定向同步运行时忽略目录 `app/versions/0.2.0/signriver_app/domain/cartridges.py`。
- 发布器会保存 Steam DLC 接口提供的最新正式上线时间并导出到卡带 freshness；客户端保留原“资源提交于…”提示，只有该日期严格更晚时才追加“资源可能未跟上新版本，请提醒 UP 更新资源”。旧卡带和 Steam 未提供日期时保持原提示。
- 活动客户端版本为 `0.2.0`；已定向同步同一解析与提示逻辑，用户重启客户端后可读取带新字段的云端卡带；未构建或发布新模块。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests/test_dlc_freshness.py tests/test_publisher_workspace.py -k "freshness or steam_store_client"`（6 项通过）；`\.venv\Scripts\python.exe -m ruff check src/signriver_publisher/cream.py src/signriver_publisher/steam.py src/signriver_publisher/freshness.py src/signriver_publisher/workspace.py app/versions/0.1.0/signriver_app/domain/cartridges.py tests/test_dlc_freshness.py tests/test_publisher_workspace.py` 通过；`\.venv\Scripts\python.exe -m compileall -q src/signriver_publisher app/versions/0.1.0/signriver_app/domain app/versions/0.2.0/signriver_app/domain` 通过；`git diff --check` 通过。
- 未执行：客户端/发布器 GUI 人工验收、完整测试、构建、云端卡带发布和推送。此前运行的 `tests/test_dlc_freshness.py tests/test_publisher_workspace.py` 全量组合有一项与本次无关的既有失败：构建完成清单中的 JSON list 与 `profile.to_dict()` 的 tuple 比较不同。

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
