# 当前任务交接

> 本文件只保留当前状态；历史流水见 [`archive/`](archive/)。长期约束见 [`DECISIONS.md`](DECISIONS.md)。

## 当前状态（2026-09-04）

- 分支：`main`
- HEAD：任务完成后以 Git 实际提交为准（本任务为发布器上传队列进度显示优化）
- 活动客户端版本：`0.2.0`，`app/state.json` 与活动模块一致。
- 工作区：本任务改动已验证，待本地提交；无其他未提交改动。

## 本次任务

- 修改范围：`src/signriver_publisher/upload_queue.py`、`src/signriver_publisher/upload_queue_ui.py`、`tests/test_publisher_upload_queue.py`。
- 上传队列进度条现在只表示当前文件的 `sent / total`；队列行文案显示本地文件数量/本地总大小、当前处理文件序号、来源、文件名和当前文件大小进度，不再把双端累计字节作为单条进度。
- 活动客户端版本保持 `0.2.0`；本任务仅涉及 Windows 发布器，不修改客户端模块，因此无需同步活动模块；重新启动发布器后生效。
- 已执行：`python -m pytest -q tests/test_publisher_upload_queue.py tests/test_publisher_ui_threading.py`（通过）；`python -m ruff check src/signriver_publisher/upload_queue.py src/signriver_publisher/upload_queue_ui.py tests/test_publisher_upload_queue.py`（通过）；`python -m compileall -q src/signriver_publisher`（通过）；`git diff --check`（通过）。
- 未执行：发布器 GUI 人工验收、构建 EXE、真实上传和推送。

## 最近结论

- 已确认 `0.1.5 → 0.2.0` 报错的主要发布风险是同版本存在多套包，且 GitHub、GitLink、本地清单的大小/SHA-256 不一致。
- `0.2.0` 使用 Host API 3；最低启动器版本必须以真实冻结包 E2E 验证结果为准，不能只依据清单可解析来声明兼容。
- 详细事故记录已归档至 [`HANDOFF-2026-09-04-history.md`](archive/HANDOFF-2026-09-04-history.md)。

## 当前风险与下一步

- 后续发布必须执行单一构建产物、双源回读校验，以及仍受支持旧启动器到新版本的更新矩阵测试。
- 线上发布前需确认远端清单和附件完全匹配；不得使用 `dist`、`publisher-workspace/output` 或历史包中的旧清单。
- 未完成：真实远端包完整下载复核、下一版本发布门禁自动化；均不得写成已验证。

## 最近验证

- `python -m pytest -q tests/test_full_update.py tests/test_updater.py tests/test_loader.py tests/test_state.py tests/test_versioning.py tests/test_release_build.py tests/test_build_module.py tests/test_restore_module_archives.py`：通过。
- `python -m compileall -q src app/versions/0.1.0 app/versions/0.2.0 tools`：通过。
- `git diff --check`：通过。
- 未执行 GUI、真实上传、推送或完整远端包下载。
