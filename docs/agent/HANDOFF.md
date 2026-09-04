# 当前任务交接

> 本文件只保留当前状态；历史流水见 [`archive/`](archive/)。长期约束见 [`DECISIONS.md`](DECISIONS.md)。

## 当前状态（2026-09-05）

- 分支：`main`
- HEAD：任务完成后以 Git 实际提交为准（本任务为游戏内容发布顺序修复）
- 活动客户端版本：`0.2.0`，`app/state.json` 与活动模块一致。
- 工作区：本任务改动已验证，待本地提交；无其他未提交改动。

## 本次任务

- 修改范围：`src/signriver_publisher/content_release_pipeline.py`、`tests/test_publisher_content_pipelines.py`。
- 游戏内容发布改为按源站完成附件上传、远端清理和 `catalog.json` 切换，再处理下一个源站；不再把所有源站的附件上传与主表切换拆成两个全局阶段。
- 阶段检查点保存已完成主表切换的源站；恢复时跳过已完成源站的重复切换，并新增第二源失败时第一源保持完整闭环的回归测试。
- 活动客户端版本保持 `0.2.0`；本任务仅涉及 Windows 发布器，不修改客户端模块，无需同步活动模块；重新启动发布器后生效。
- 已执行：发布器相关定向测试 56 项通过；`python -m ruff check src/signriver_publisher/content_release_pipeline.py tests/test_publisher_content_pipelines.py` 通过；`python -m compileall -q src/signriver_publisher` 通过；`git diff --check` 通过。
- 发布器全部专项测试中有 1 项既有失败：`tests/test_publisher_workspace.py::test_successful_build_writes_verified_completion_manifest`，为 `[]` 与 `()` 类型差异，与本任务无关。
- 未执行：发布器 GUI 人工验收、发布器 EXE 构建、真实双源发布和推送。

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
