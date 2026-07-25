# 执行状态

> 最后更新：2026-07-25

## 当前状态

已确认 `docs/in-place-full-update-plan.md` 是本次正式执行计划。计划中的实施事项已完成，最终完整测试、编译检查和 Windows 发行构建均已通过。

## 已完成事项

- 已检查根目录、`docs/`、`src/`、`tools/` 与测试目录，未发现 `PLAN.md` 或既有 `STATUS.md`。
- 已完整阅读原地全量更新设计草案、模块化更新架构与 README，确认现有全量更新仅打开下载链接，尚未实现原地替换。
- 已创建本状态文件，以记录本次无人值守执行的阻塞原因。
- 完成 `FullUpdateTransaction` 原子持久化、受管路径限制、同卷暂存、完整包安全解压、发行清单 SHA-256 校验、逐文件替换及反序回滚。
- 完成 `release-manifest.json` 构建；清单不包含 `data/`、`cache/`、`app/state.json` 或旧安装兼容配置 `config/update.json`。
- 完成全量更新助手流程：主程序准备包后复制当前启动器至暂存目录作为助手，退出后由助手替换受管文件并启动新发行启动器确认事务。
- 完成更新配置三层读取：用户覆盖 `data/config` 优先于旧安装配置，旧安装配置优先于发行默认值。
- 完成客户端全量更新界面流程；不再仅打开浏览器下载页面。
- 完成磁盘空间预检、单实例锁及启动时对需回滚事务的恢复检测。
- 完成发布指南与架构文档更新，并将计划中的九项实施步骤标为完成。

## 修改的文件

- `STATUS.md`：新增执行状态记录。
- `docs/in-place-full-update-plan.md`：作为正式执行计划，九项实施步骤均已更新为完成。
- `src/signriver_launcher/full_update.py`、`full_update_helper.py`：新增全量更新事务与助手。
- `src/signriver_launcher/{api,config,constants,errors,main,models,paths,updater}.py`：接入完整包准备、确认、配置和命令入口。
- `app/versions/0.1.0/app_entry.py`：全量更新改为准备助手并专用退出。
- `tools/build_release.py`、`config/defaults/update.json`、`docs/update-architecture.md`：发行清单和配置文档。
- `tests/test_full_update.py`、`tests/test_update_config.py`、`tests/test_release_build.py`：新增/扩展验证。

## 验证

- `Get-Content -Encoding utf8 PLAN.md`：失败，根目录不存在该文件。
- `rg --files -g "PLAN.md" -g "STATUS.md"`：未发现 `PLAN.md`；执行前没有 `STATUS.md`。
- `& .\\.venv\\Scripts\\python.exe -m pytest`：通过，`427 passed in 7.35s`。
- `git diff --check`：通过，未报告空白错误。
- 首个里程碑：`pytest tests/test_full_update.py tests/test_updater.py tests/test_release_build.py tests/test_state.py` 通过，`16 passed`；`compileall` 通过。
- 第二个里程碑：`pytest tests/test_full_update.py tests/test_updater.py tests/test_loader.py tests/test_release_build.py tests/test_ui_theme.py` 通过，`62 passed`；`compileall` 通过。
- 第三个里程碑：`pytest tests/test_update_config.py tests/test_full_update.py tests/test_updater.py tests/test_loader.py tests/test_release_build.py tests/test_product_packaging.py` 通过，`20 passed`；`compileall` 通过。
- 最终验证：`pytest` 通过，`436 passed in 7.91s`；`compileall -q src tests tools app/versions/0.1.0/app_entry.py` 通过；`git diff --check` 通过。
- 最终构建：`python tools/build_release.py` 通过，生成 ZIP、自解压 EXE 和发行目录。检查 ZIP 中的 `release-manifest.json`：87 个受管文件，`app/state.json` 与 `config/update.json` 均未列入。
- 代码检查：`python -m ruff check src tests tools` 无法执行，原因是当前开发环境未安装 `ruff`；已用 Python `compileall` 完成语法/字节码检查。

## 重要决定

- 将 `docs/in-place-full-update-plan.md` 视为正式计划，依据用户后续明确确认继续执行。
- 全量更新采用“暂存的启动器副本作为助手”而非额外长期安装 EXE，以避免 Windows 下运行中的启动器锁定自身导致无法替换。
- 构建清单仅描述受管运行时文件；未声明文件保持不变，防止覆盖用户数据或清除未知文件。
- 不修改生产配置、用户数据、缓存、密钥或远程仓库。

## 未解决问题与下一步

- 未解决问题：Ruff 未列入开发依赖，未执行静态风格检查。
- 明天需要确认：在真实 Windows 安装目录执行一次端到端全量更新演练，覆盖运行中 EXE 的临时助手替换、失败后旧启动器恢复和桌面快捷方式保持可用。自动化测试已覆盖文件事务，但不会锁定真实 EXE。
