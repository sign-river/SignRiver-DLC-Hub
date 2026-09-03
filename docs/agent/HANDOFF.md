# 当前任务交接

> 本文件只保留当前状态；历史流水见 [`archive/`](archive/)。长期约束见 [`DECISIONS.md`](DECISIONS.md)。

## 当前状态（2026-09-04）

- 分支：`main`
- HEAD：`5ac7cfd`（记录全量更新发布一致性门禁）
- 活动客户端版本：`0.2.0`，`app/state.json` 与活动模块一致。
- 工作区：整理前无未提交改动；本次文档压缩会产生新的文档改动。

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
