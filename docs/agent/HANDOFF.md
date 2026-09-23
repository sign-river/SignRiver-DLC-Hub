# 当前任务交接

## 文档审计与全量更新（2026-09-23）

- 目标：核对项目内全部文档的时效性，修正与现状不符的描述；同时给 README 增加 Star History 区块和平台/功能说明。
- 事实核对（改动前）：`app/state.json` 活动模块 = `1.0.0`；`LAUNCHER_VERSION = 1.0.0`、`HOST_API_VERSION = 3`；`config/module-archives.json` 模块基线 = `0.1.7` / `0.2.0` / `1.0.0`；本地兜底卡带 10 条、云端主表 11 条（对应 `KI-011`）；`config/guides` 共 16 条。
- 改动范围（**纯文档，未改任何代码、配置或产物**）：
  - `README.md`：重写为当前状态——新增平台与游戏支持矩阵、三端补丁资产差异表、报错指南/离线模式/更新机制说明，修正出厂卡带列表与发行包模块目录，构建示例版本号改为 `1.0.0`，并新增 Star History 区块与页脚。
  - `STATUS.md`：按 `1.0.0` / Host API `3` / 三端交付重写当前状态与验证段。
  - `docs/agent/PROJECT_CONTEXT.md`：更新线上版本、后续方向与 `PLAN.md` 的定位描述。
  - `docs/current-progress.md`：新增「当前状态（2026-09-23）」与 1.0.0 产物哈希表，历史段落标注为仅供追溯。
  - `PLAN.md`：标记 `0.2.0` 计划已完成，补齐最后两项验收结论。
  - `docs/agent/HANDOFF.md`：按 `DOCUMENT-MANAGEMENT.md` 阈值（原 567 行 / 117 KB）把 2026-09-21 及更早条目归档到 `archive/HANDOFF-2026-09-23-history.md`。
  - `docs/application-implementation-plan.md`、`docs/publisher-refactor-plan.md`、`docs/publisher-refactor-acceptance.md`：补充历史计划标注。
  - `.agents/skills/project-context-switch/SKILL.md`：`compileall` 示例不再写死 `0.2.0`。
- 验证：本地 `.venv\Scripts\python.exe -m pytest` = **961 passed**、0 失败、0 跳过（2026-09-23，pytest 9.1.1）；`ruff check src tests tools app/versions/0.1.0` 通过；`1.0.0` 的 8 个发布产物大小与 SHA-256 已在本机 `dist/` 重新实测并写入 `docs/current-progress.md`；本次未执行构建、打包或上传；文档提交 `f4526f9` 已经用户确认后推送，CI run `35840313641` 三端（Windows / Ubuntu / macOS）全绿。
- 版本对齐：本次只改文档，不涉及客户端代码，**不需要**同步活动模块或让用户重启客户端。
- 下一步：`KI-011`（兜底卡带平台可用性与云端不一致）仍待排期；README 如需英文版或补截图另行确认。
- 风险：`STATUS.md`、`PLAN.md`、`docs/current-progress.md` 都带有「当前状态」性质，后续版本发布后需要继续同步，避免再次过期。

## 修复 POSIX（macOS/SteamOS）测试失败并让 CI 转绿（2026-09-22）

- 现象：首次推送后 CI 只有 Windows 通过；macOS 与 Ubuntu 失败，且日志以 `NotImplementedError: cannot instantiate 'WindowsPath' on your system` 的 pytest INTERNALERROR 结束（失败详情被吞掉，只能看到 7% 处两个 `F`）。
- 复现环境：本机 conda 新建 Python 3.11（CI 版本）+ SteamOS 来宾（Linux，Py3.13）+ macOS 来宾（Darwin，Py3.12），把当前源码同步进去跑全量，逐项定位。
- 根因与修复（均在 Git 跟踪的 `tests/` 与基线 `app/versions/0.1.0/` 内）：
  1. `test_full_update.py::test_windows_full_update_rejects_excessive_staged_path` 在 POSIX 上把 `os.name` 改成 `"nt"` 后调用 `Path(...)`，触发 `WindowsPath` 无法实例化；失败又发生在 `os.name` 被改动的窗口内，使 pytest 生成失败报告时一起崩溃（INTERNALERROR 的元凶）。→ 该用例加 `skipif(os.name != "nt")`。
  2. `test_cartridge_default_fallback.py` 两个用例的伪造索引条目没有 `platform_resources`，而无该字段的条目按“仅 Windows 可用”处理，导致 macOS/SteamOS 上走不到预期分支。→ 显式声明三端可用（本机模拟三平台验证）。
  3. `test_graphics_compatibility.py::test_dxdiag_retries_after_timeout_and_clears_partial_output`、`test_security_software.py::test_discover_security_products_parses_unique_absolute_executables` 依赖 Windows 的 `Path`/可执行文件语义，POSIX 上必然失败。→ 各自加 `skipif(os.name != "nt")`。
  4. `test_diagnostics.py` 断言导出结果一定是 `<APP_ROOT>`；但当出厂目录位于用户主目录之下（macOS/SteamOS 的常见部署方式）时，问题记录创建阶段已把 home 前缀替换成 `<user-home>`，导出阶段再也认不出完整应用目录。→ 断言改为“以 `<APP_ROOT>` 或 `<user-home>` 开头且原始路径不出现”，保留隐私校验意图。
  5. 顺带改进 `DiagnosticExporter.sanitize()`：同时按“解析符号链接后的真实路径”和“调用方传入的显示路径”替换应用目录（macOS `/tmp → /private/tmp`、SteamOS `/home → /var/home`），避免只替换一种形态而漏掉。
- 版本对齐：第 5 条只落在 Git 跟踪基线 `app/versions/0.1.0/`（**仅基线实现**）；活动模块 `app/versions/1.0.0/` 与已发布包保持冻结不动（该改动只是脱敏 token 更精确，原始路径在任一形态下都不会泄漏，发布包将在下个版本带上）。
- 验证：本机 Windows 全量 `pytest` + `ruff` 通过；SteamOS 来宾全量通过（Linux）；macOS 来宾全量通过（Darwin）。
- 追加修复（同日，第二轮 CI）：三端仍有失败，全部是 **CI 环境问题**——`restore_module_archives.py` 那一步原先带 `if: runner.os == 'Windows'`，于是 macOS/Linux 上 `app/versions/` 里只有 Git 跟踪的 `0.1.0`，依赖 `0.2.0`/`1.0.0` 目录的用例（`test_platform_content`、`test_support_collection_ui`、`test_release_build`）必然 `FileNotFoundError` 或断言失败。已删除该条件，三个平台都恢复已发布模块（顺带在 macOS/Linux 上也校验了模块归档哈希）。
- 结论（2026-09-22）：CI run `35649501911`（head `582c14c`）三端全绿 —— `windows-latest` / `macos-15-intel` / `ubuntu-24.04` 均为 success。第三轮只改了 CI workflow 本身、未动产品代码，因此无需再来宾复跑；本轮任务闭环，远端 `origin/main` 即 `582c14c`。

## 修复 CI：卡带索引哈希按 LF 归一化（2026-09-22）

- 现象：推送后 CI 三端全红，pytest 仅 1 项失败——`tests/test_cartridge_catalog.py::test_bootstrap_index_and_documents_round_trip`（Windows/macOS 直接跑 pytest、Ubuntu 走 Xvfb 都红）；`restore_module_archives.py`（模块归档校验）与 ruff 均通过。
- 复现：本地用 conda 建 Python 3.11 环境（CI 用的是 3.11，本地默认 3.13）跑全量 → `1 failed, 957 passed, 3 skipped`，失败项与 CI 完全一致。
- 根因：`config/cartridges/*.json` 工作区文件是 CRLF，而 `cartridges_index.json` 里记录的 `sha256`/`size_bytes` 按 CRLF 内容计算；但 `.gitattributes` 声明 `config/cartridges/*.json text eol=lf`，CI 全新检出得到 LF 内容 → 哈希与大小都对不上。本地工作区是 CRLF，所以一直"通过"，掩盖了该问题。
- 修复：把那 5 份卡带规范化为 LF（内容未变，仓库里本就是 LF，`git diff` 为空），并按 LF 内容重算 `cartridges_index.json` 的 `sha256`/`size_bytes`（例：stellaris 2777→2695 / `ff9c6e05fc3bbda1…`）。工作区形态与 git 检出形态从此一致。
- 顺带清理：为复现而执行的 `pip install -e .` 改动了 `src/signriver_dlc_hub.egg-info/{PKG-INFO,SOURCES.txt}`，已还原为仓库版本（属本地安装产生的构建产物，与本次修复无关）。
- 验证：`pytest tests/test_cartridge_catalog.py tests/test_platform_content.py` 在 3.13 与 3.11 两个解释器下均通过；全量 `pytest`（3.13）通过。
- 影响说明：云端 `hub` release 仍是 CRLF 卡带 + 对应 CRLF 哈希（自洽，客户端校验与下载不受影响）；下次发布 hub 会按本地 LF 文件重新计算并上传，同样自洽。今日已构建的 1.0.0 包内是 CRLF 卡带 + 当时的索引，也自洽，无需重新打包。
- 结论：修复已推送并经 CI 证实（见上文 run `35649501911`，三端全绿）。

## 模块归档目录改为 modules Release 的唯一数据源（2026-09-22）

- 起因：推代码前预检发现 CI 必红——`tools/restore_module_archives.py` 会按 `config/module-archives.json` 逐个校验云端模块归档，而 0.1.7（线上 187,755 / `cf2d2a93…`，基线 233,255 / `6007a8ce…`）与 0.2.0（线上 191,187 / `896c2bbb…`，基线 289,622 / `e011d633…`）两份云端副本仍是旧构建；只有 1.0.0 匹配。历史提交一直没推送，所以这个偏差此前没被 CI 暴露。
- 用户要求的工作流：把需要上传的模块归档放进「模块归档目录」，点一次同步即可——于是改成**目录里放什么就同步什么**：
  - `ArtifactCollector.collect_program_module_artifacts()` 不再按目标版本过滤，收集目录里全部有效模块归档；与目标版本一致的那份 `required=True`，历史版本 `required=False`。
  - `ReleasePreflightService._check_program_module_archives()` 只要求「存在与目标版本一致的归档」，历史版本记入 `evidence.extra_versions`，提示会说明"其中历史版本 N 个会一并同步"。
  - `ReleasePreflightService._program_checks()` 的版本一致性检查只看 `required=True` 的产物，避免历史模块被判成版本不一致。
  - 上传阶段 `UploadProgramModulesStage` 本来就会把批次里全部 `module_archive` 传到 `modules` Release（双源同名替换），无需改动。
- 现场处理：把 `dist/modules/SignRiver-DLC-Hub-module-v0.1.7.zip`（233,255 / `6007a8ce…`）与 `-v0.2.0.zip`（289,622 / `e011d633…`）复制进 `publisher-workspace/output/modules/`（原有 v1.0.0），工作区探测产生的两个临时草稿批次已删除，用户此前完成的批次保留。
- 验证：新增 `tests/test_publisher_release_service.py::test_module_inbox_syncs_historical_archives_with_the_current_one`（三份归档被收集、只有目标版本 required、预检 PASS 且 `extra_versions=["0.2.0"]`、双源都上传两份历史归档）；发布器相关 3 个测试文件与全量 `pytest` 通过。
- 待办：用户在发布器点「验证并查看差异」→「发布文件」同步模块归档后，我方复验 `modules` Release 的 0.1.7/0.2.0 哈希，再执行 `git push origin main`（本地 410 个提交未推送）。

## 登记已知问题 KI-011（2026-09-22）

- 用户确认把「本地兜底卡带的平台可用性与云端不一致」放到**下个版本**处理，本次只登记不修代码：`docs/known-issues.md` 新增 `KI-011`（待排期 / P2），含两件事——① 本地 `config/cartridges/cartridge_{civilization_6,hearts_of_iron_4,rimworld,cities_skylines}.json` 保留了实际不存在的 `patch.platforms.steamos/macos`，导致本地 `cartridges_index.json` 把它们的平台支持标多了（云端与发布器工作区都只有 群星三端 / 都市天际线 win+macos / 其余仅 Windows）；② 本地缺云端已有的 `cartridge_cities_skylines_2.json`。
- 已确认的影响边界：离线态由 `_set_offline_state()` 禁用一键解锁并常驻“当前无网络连接…”提示，下载入口一并屏蔽，因此只影响离线时的展示，不会造成下载失败；在线读云端 `hub` 索引，发布 hub 又取自 `publisher-workspace/games/*/game.json` 的 `published_platform_resources`，链路本身不会把错误数据带上线。
- 改动范围：仅 `docs/known-issues.md` 与本文档；**未修改任何运行时代码、缓存或活动模块**。`git diff --check` 通过；仅文档改动，未运行 pytest。

## 发布落点与 1.0.0 线上状态（2026-09-22）

- **更新链路已上线（已核对双源）**：`signriver-dlc-assets` 的 `updates` release 中 windows `42bf2cce…` / 21,318,160、macos `e0fc722d…` / 23,785,464、steamos `184532c0…` / 43,967,168 与本地构建逐字节一致；`modules` release 的 `SignRiver-DLC-Hub-module-v1.0.0.zip` = `45decd94…` / 301,564，与 `config/module-archives.json` 一致。
- **尚未发布**：① `hub` release 的 `announcement.json` 仍是 `2026-08-23-notice`（旧公告），1.0.0 公告要经发布器「游戏支持数据」页「生成客户端 hub」→「发布 hub Release」才会同步（卡带同批）；② 首装包四份还没上传。
- **首装包落点（用户确认）**：本项目仓库自己的 Release——GitLink `signriver/signriver-dlc-hub`、GitHub `sign-river/SignRiver-DLC-Hub`（GitHub 侧若为草稿则匿名 API 看不到，之前排查时显示 0 releases 即由此）。四份为 `dist/唏嘘南溪DLC一键解锁工具-v1.0.0-windows-x64.zip`（`e2c14b11…`）、同版本自解压 EXE（`d8c715ab…`）、`dist/SignRiver-DLC-Hub-v1.0.0-macos-x64.app.zip`（`8b31ffe1…`）、`dist/SignRiver-DLC-Hub-v1.0.0-steamos-x64.tar.gz`（`cf1a8a32…`）。已写入 `docs/program-update-release-guide.md` 的「首次安装包（手动上传到本项目 Release）」一节。
- 待办顺序：上传首装包 → 发布 hub（公告+卡带）→ `git push origin main`。

## SteamOS 1.0.0 原生重建（2026-09-22，含移除补丁改造）

- 通道：SSH `deck@192.168.233.130`（密钥 `.test-artifacts/steamos_codex_ed25519`，辅助脚本 `.test-artifacts/steamos_guest.py`，`get` 参数顺序为「本地 远端」）。来宾 Linux 6.16.12 x86_64（SteamOS holo）、Python 3.13.5（`~/signriver-steamos-build/.venv-steamos`）、PyInstaller 6.22.3。
- 源码同步：`.test-artifacts/signriver-native-source-20260922.tar.gz`（5,557,348 字节 / 811 文件）传入 `~/signriver-steamos-build` 解包覆盖，`.venv-steamos`、`build/`、`dist/` 不受影响；预检 `signriver_app` 81 文件与三个新代码标记齐全（tar 的 “time stamp in the future” 是宿主机/来宾时钟差，属正常告警）。
- 来宾测试：`test_build_native_release.py`、`test_cross_platform_runtime.py`、`test_patch_engine.py`、`test_platform_content.py`、`test_release_build.py` 通过（4 项跳过）。**顺带修**：SFX 用例原先只在“既无 7-Zip 又无 Bandizip”时跳过，而 SteamOS 有 `7z` 却没有 `7z.sfx`，导致误报失败；新增 `tests/test_release_build.py::_sfx_backend_available()`（7-Zip 需带 `7z.sfx`、Bandizip 需带 `bdzsfx.x86.sfx`）后正确跳过。
- 构建与产物：`.venv-steamos/bin/python tools/build_native_release.py --platform steamos` 成功；`dist/SignRiver-DLC-Hub-v1.0.0-steamos-x64.tar.gz` = 43,876,545 / `cf1a8a326f80bd21fd51c4402a6aba41567efe5f68c652de58a11e6ce41ab21c`；`dist/updates/SignRiver-DLC-Hub-full-v1.0.0-steamos-x64.zip` = 43,967,168 / `184532c02cf833ce5e94e2334626bf549858af18d982e0b20677673652aca935`（主机副本 `.test-artifacts/steamos-dist/`，哈希与来宾一致）。
- 产物核对：`tar -tzf` 顶层为 `SignRiver-DLC-Hub-steamos-x64/`（263 条）、`unzip -t` 通过；主程序 ELF 64-bit x86-64、权限 755；runtime `app/versions` 只有 `0.2.0` + `1.0.0`；`signriver_app` 81 文件、`config/guides` 19 项；包内 `app_entry.py` 与来宾源码 sha256 相同（`dc57a354…`）。
- 数据目录同步（与 macOS 同样的坑）：`~/.local/share/signriver-dlc-hub/app/versions/1.0.0` 原是旧代码（`6914415c…`、新标记计数 0），已备份为 `1.0.0.bak-20260922-preremoval` 并同步新模块（`dc57a354…`、旧文案计数 0）。**注意**：`pkill -f` 会匹配到自己 SSH 命令行导致会话被杀，改用 `pkill -x SignRiver-DLC-H`（按 comm 匹配）。
- 启动验证：`DISPLAY=:0 XAUTHORITY=/home/deck/.Xauthority` 下 `timeout 15 …/SignRiver-DLC-Hub` 退出码 124（15 秒内一直存活）；launcher log 出现 `Starting application module 1.0.0`；桌面会话以 `setsid nohup … &` 启动后 12 秒进程仍在（PID 12089/12090）供用户直接查看。
- 清单与收件：双源清单三段全部刷新——windows `42bf2cce…` / 21,318,160、macos `e0fc722d…` / 23,785,464、steamos `184532c0…` / 43,967,168，并同步到 `publisher-workspace/output/updates/`；`output/updates` 三端包与 `output/modules` 模块归档均为最新。
- 未执行：未上传、未发布、未切换线上清单、未 push。

## macOS 1.0.0 原生重建（2026-09-22，含移除补丁改造）

- 通道：**VMware Tools（`vmrun -T ws -gu signriver -gp …`）**——来宾未开 SSH/SMB/VNC；`runProgramInGuest` 不回传 stdout，统一用「脚本写日志 → `copyFileFromGuestToHost` 取回」。来宾 `Darwin 24.6.0 x86_64`、Python `/Users/signriver/py312/python/bin/python3.12`（3.12.14）、PyInstaller 6.22.3，构建目录 `/Users/signriver/macos-build-20260919`。
- 源码同步：主机归档 `.test-artifacts/signriver-macos-source-202609220241.tar.gz`（5,556,164 字节 / 811 文件，排除 `.git`、虚拟环境、`build/`、`dist/`、`.test-artifacts/`、`publisher-workspace/`、缓存与凭据）传入来宾解包覆盖；预检 `app/state.json`、`app/versions/1.0.0/{module.json,app_entry.py}` 与 `signriver_app`（81 文件）齐全，新代码标记 `patch_row_status`、`_receipt_backed_removal_ready`、`published_original` 均在。
- 来宾测试：`tests/test_build_native_release.py`、`test_macos_update_helper.py`、`test_cross_platform_runtime.py`、`test_patch_engine.py`、`test_platform_content.py`、`test_release_build.py` 共 119 项通过、4 项跳过（依赖 7-Zip/Bandizip）；来宾未装 ruff。
- 构建与产物：`python tools/build_native_release.py --platform macos` 状态码 0；`dist/SignRiver-DLC-Hub-v1.0.0-macos-x64.app.zip` = 23,776,287 / `8b31ffe1c7e14e0996ff968e81ad2ff80cbeaf7a8ea35b9a4e570d431ac76ecd`；`dist/updates/SignRiver-DLC-Hub-full-v1.0.0-macos-x64.zip` = 23,785,464 / `e0fc722d25587e896905c3e326e3c7e6e05c485ebe5978e7f762becaf9a40001`（主机副本在 `.test-artifacts/macos-dist/`，哈希与来宾一致）。
- 产物核对：两个 ZIP `unzip -t` 通过；主程序 Mach-O 64-bit x86_64；runtime 内 `app/versions` 只有 `0.2.0` + `1.0.0`（体积裁剪在 macOS 同样生效）；`signriver_app` 81 文件、`config/guides` 19 项；`codesign --verify --deep --strict` 通过；包内 `app_entry.py` 与来宾源码 sha256 相同（`dc57a354…`）。启动验证：直接运行 `dist/SignRiver-DLC-Hub.app`，12 秒后进程存活（PID 6200/6202），`~/Library/Logs/DiagnosticReports` 无新增崩溃。
- **重要坑（用户发现，已修）**：VM 里补丁工具仍显示旧文案「补丁缺失：尚未下载」。根因是 macOS 客户端优先加载**用户数据目录** `~/Library/Application Support/SignRiver DLC Hub/app/versions/1.0.0/`，那份还是 09-21 的旧代码；`.app` 里的新模块不会覆盖它（`_seed_packaged_runtime` 只在目标不存在时复制）。已把数据目录模块备份为 `1.0.0.bak-20260922-preremoval`，再同步新模块（`app_entry.py` 哈希 `dc57a354…`、`补丁缺失` 计数为 0）并重启客户端。**以后在 macOS 验证新代码必须同步数据目录模块副本，否则看到的仍是旧行为。**
- 清单与收件：双源清单 macOS 段更新为 `e0fc722d…` / 23,785,464（Windows 段保持冻结值 `42bf2cce…`，SteamOS 段仍是旧包 `85f6f0cc…`），并同步到 `publisher-workspace/output/updates/`；`output/updates` 的 macOS 包与 `output/modules` 的模块归档已自动同步。
- 未执行：未上传、未发布、未切换线上清单、未 push；SteamOS 仍未重建。

## Windows 1.0.0 正式发布（冻结，2026-09-22）

- 用户确认：当前 Windows 构建即为 1.0.0 正式发布版本，冻结不再改动；后续 Windows 修复必须用更高版本号（例如 1.0.1）承载，否则已发布用户检测不到更新。
- 最终产物（大小 / SHA-256）：模块 `dist/modules/SignRiver-DLC-Hub-module-v1.0.0.zip` = 301,564 / `45decd9429424753110af8a40da1644729eb6b2953bfe12eb727c4f44a054b87`；全量更新 `dist/updates/SignRiver-DLC-Hub-full-v1.0.0-windows-x64.zip` = 21,318,160 / `42bf2cce2f79ee340ed78980fde61a217dae6dc46be4e6c74e5c0690682a9fcd`；首装 ZIP `dist/唏嘘南溪DLC一键解锁工具-v1.0.0-windows-x64.zip` = 21,333,799 / `e2c14b1125a30e538e6eaa16d4568fc98f2fcb359fefd11a2f4e1b17d924dd60`；自解压 EXE（含同内容别名）= 21,615,063 / `d8c715ab8893f19a358464a7cd4b210a60ef911a18749ef06464b8ce5ed1bc6d`。
- 冻结核对（同日全绿）：工作区 `app/versions/1.0.0/app_entry.py` 与发布目录逐字节一致，且都含最新移除补丁改造（`published_original`、`_receipt_backed_removal_ready`）；模块归档与全量包内是同一份代码；全量包模块目录仅 `0.2.0` + `1.0.0`；`config/module-archives.json` 的 1.0.0 记录 = `45decd94…` / 301,564；双源清单 Windows 段 = `42bf2cce…` / 21,318,160（`mandatory: true`、`min_launcher_version: 0.1.2`）；发布器收件目录 `output/updates` 与 `output/modules` 已同步为上述新包；Git 工作区干净（HEAD `91cb093`）。
- 上传顺序（务必遵守）：① 先把模块归档 `SignRiver-DLC-Hub-module-v1.0.0.zip` 传到 GitLink/GitHub（CI 的 `restore_module_archives.py` 会按 `config/module-archives.json` 的 sha256 校验）；② 再传全量更新包、首装 ZIP 与自解压 EXE；③ 替换两份 `update-manifest.json`；④ 最后才 `git push origin main`。
- 随版发布内容：本次更新说明（`publisher-workspace/update-notes.json` 的 1.0.0）与云端启动公告（`publisher-workspace/announcement.json`，「1.0.0 正式版已发布」）随 hub Release 一并发布。
- 仍然待办：macOS / SteamOS 包内客户端仍是旧逻辑（缺补丁工具行状态修复、缺“移除补丁改用云端原始库”、仍带 7 个历史模块目录），清单里这两段仍指向 09-21 的旧包；需在各自虚拟机重建后更新对应哈希。

## 1.0.0 云端启动公告文案（2026-09-22）

- 需求：为 1.0.0 写一条云端启动公告（更新方式 / 使用方法 / 报错处理路径 / 求助渠道），用户提供要点，我方优化表述。
- 落地位置：写进发布器草稿与启用态——`publisher-workspace/announcement-draft.json`（`enabled: true`）与 `publisher-workspace/announcement.json`（会被复制进下一次生成的 hub Release，即云端 `announcement.json`）。`publisher-workspace/` 不入库，故本条只记录在交接里；发布器「管理启动公告」打开即是新内容，保存/发布 hub 后生效。
- 内容要点（标题「1.0.0 正式版已发布」，id `2026-09-22-v1-0-0-release`，日期 2026-09-22）：更新方式＝设置 →「检查更新」；使用方法＝「DLC 库」页选游戏 →「一键解锁」；报错先点「一键修复」→ 不行的去「报错指南」先点「一键排错」再点「解决方案」卡片按现象对照处理 →「报错指南 → 常用工具」里的日志资料收集/补丁工具/杀毒软件检测等可自助排查 → 仍无法解决带截图 +「运行日志」复制的日志到 QQ 群 1061299021。**用词必须逐个点名报错指南里的卡片**（一键排错 / 解决方案 / 问题记录 / 运行日志 / 常用工具）：用户两次指出“解决方案”是界面里的卡片名，不能只写“里面列出了解决方案”这类自造描述。
- 校验：发布器 `PublisherWorkspace.load_announcement_draft()` 读取并通过 `AnnouncementDraft.validate()`；客户端 `Announcement.from_dict()` 解析通过（正文 359 字，公告对话框 560×420 可滚动）；`announcement_status()` 返回「已启用：1.0.0 正式版已发布」。公告 id 与旧版不同，已选择「不再提示」的客户端会重新显示。
- 未执行：没有发布 hub Release（需要发布器凭据与用户确认），客户端内置兜底公告 `config/announcement.json`（云端读取失败时显示）保持原样不动。

## Windows 1.0.0 打包（2026-09-22 02:2x，含移除补丁改用云端原始库）

- 触发：`remove()`/客户端移除流程改为“先取云端原始库再还原”，模块代码随之变化，重新构建 Windows 侧全部产物。
- 命令：`tools/build_module.py --all-versions app\versions` → `tools/build_release.py --upx-dir …` → `tools/prepare_update_release.py`（三方 `--platform-package`）。构建脚本已自动同步发布器收件目录。
- 产物（大小 / SHA-256）：模块 `dist/modules/SignRiver-DLC-Hub-module-v1.0.0.zip` = 301,564 / `45decd9429424753110af8a40da1644729eb6b2953bfe12eb727c4f44a054b87`（`config/module-archives.json` 已更新）；全量更新 `dist/updates/SignRiver-DLC-Hub-full-v1.0.0-windows-x64.zip` = 21,318,160 / `42bf2cce2f79ee340ed78980fde61a217dae6dc46be4e6c74e5c0690682a9fcd`；首装 ZIP `dist/唏嘘南溪DLC一键解锁工具-v1.0.0-windows-x64.zip` = 21,333,799 / `e2c14b1125a30e538e6eaa16d4568fc98f2fcb359fefd11a2f4e1b17d924dd60`；自解压 EXE（含同内容别名）= 21,615,063 / `d8c715ab8893f19a358464a7cd4b210a60ef911a18749ef06464b8ce5ed1bc6d`。
- 结构核对：全量包模块目录仍只有 `0.2.0` 与 `1.0.0`，包内 1.0.0 `app_entry.py` 含 `published_original`；SFX payload 顶层只有发布目录名、对话框为中文；三个 ZIP `testzip()` 通过。清单 Windows 段 `42bf2cce…`，macOS/SteamOS 段仍是旧包哈希。
- 顺带修复：`sync_publisher_inbox()` 的过期守卫原先把 `__pycache__/*.pyc` 也算作源码，刚打包完就报“模块归档比源码旧”而跳过同步；现改为只统计真正进归档的文件，并补 `tests/test_release_build.py::test_sync_publisher_inbox_ignores_runtime_pycache`。
- 待办：上传模块归档、全量包、首装包与两份清单；macOS/SteamOS 需在各自虚拟机重建；本次未推送 Git。

## 移除补丁改用云端原始库（2026-09-22）

- 用户提案并采纳：移除补丁不该因为“凭据缺失”就卡住——云端本来就有原始库，直接下载 + 校验 + 覆盖主库更符合直觉；只有拿不到或校验不过才报错。
- 引擎：`PatchEngine.remove()/restore_original()` 新增可选参数 `published_original` / `published_original_sha256`。凭据不可用时，只要调用方给出（客户端已按卡带元数据校验过的）原始库，就执行 `_restore_with_published_original()`：校验文件存在/二进制格式/可选 SHA-256 → 把原版库写回主库槽位 → 删除 `_o` 与配置文件槽位 → 删除旧凭据；全程走事务备份，任一步失败整体回滚且不动游戏目录。没有该参数时行为不变（仍抛 `PatchProvenanceUnknownError`）。
- 客户端：`_remove_patch` 拆成 `_begin_patch_removal()` + `_run_patch_removal()`。没有凭据时先看缓存里有没有云端原始库（`_patch_ready_paths(roles=("original_dll",))`），没有就用 `_start_patch_downloads(action="remove", roles=("original_dll",))` 走既有下载/校验流水线，下载完成后由 `_apply_patch_after_download()` 转交移除流程；`_patch_original_asset_sha256()` 把卡带登记的 SHA-256 再传给引擎做二次确认。有完整凭据时 `_receipt_backed_removal_ready()` 直接走原路径，**离线也能移除**，不强制下载。
- 失败提示：下载失败/资产缺失时仍走 `_on_patch_remove_failed()`；凭据缺失且云端不可用时才是提示级的「无法确认当前补丁的来源」（上一节文案保留）。
- 版本对齐：`app/versions/0.1.0/` 改动已定向同步到 `app/versions/1.0.0/`（`app_entry.py`、`signriver_app/infrastructure/patching/engine.py`），同步前确认两边差异仅为本次改动。
- 验证：`tests/test_patch_engine.py` 新增三例（凭据缺失时用云端原始库还原成功、SHA-256 不符时不动文件、原始库缺失时报错且不动文件）；`tests/test_ui_theme.py` 新增/更新断言（下载-再-移除的接线、凭据存在时不强制下载）；`tests/test_client_problem_center.py` 的裸对象用例补上 `patch_after_download_action` 属性；`ruff` 与全量 `pytest` 通过。

## 补丁来源未知的提示改为“可操作提示”（2026-09-22）

- 用户反馈：一键移除补丁时弹出的「补丁安装凭据缺失或损坏，无法证明主库和原生库来源」读起来像文件损坏，实际只是程序无法确认当前目录里补丁的来源；解决办法也很简单。
- 文案：`engine._uncredentialed_removal_reason()` 换成——「无法确认当前补丁的来源：这份补丁不是本程序安装的（缺少安装凭据），程序无法判断哪个文件才是游戏原版，所以这一次没有改动任何文件。」并给出两条出路：① 用「一键解锁工具」重新安装一次（会先清空当前补丁再写入，完成后凭据就会生成，之后即可正常移除）；② 或用游戏平台（Steam）验证游戏文件完整性还原原版库，再删除目录里剩余的 `<runtime>` 与 `<ini>`（按平台取真实文件名）。
- 呈现：新增 `PatchProvenanceUnknownError`（`PatchError` 子类）与 `PatchRestoreReadiness.provenance_unknown`；`remove()` 只在“来源未知”这一种拒绝上抛该子类，客户端 `_on_patch_remove_failed()` 对它的处理从「补丁移除失败」红色错误框改为提示级——标题「未能自动移除补丁」、`showwarning`、通知「未改动任何文件」；其它失败仍是错误级。
- 校验前提：`engine.apply()` 确实会把发布侧原版写回 `<runtime>`、重写解锁库与配置并写入新凭据（`_write_installation_record` + `audit_recorded`），所以提示里的第一条出路成立。
- 版本对齐：改动落在 `app/versions/0.1.0/`（基线），已定向同步到活动模块 `app/versions/1.0.0/` 的三个文件（`app_entry.py`、`signriver_app/infrastructure/patching/{engine,__init__}.py`），同步前已确认两边除本次改动外逐行一致；重启客户端即生效，发布包需要下次构建才会带上。
- 验证：`tests/test_patch_engine.py` 改为断言新文案（含「一键解锁工具」「验证游戏文件完整性」两条出路）与 `PatchProvenanceUnknownError` 类型；`tests/test_ui_theme.py` 新增一条界面级断言（提示级呈现 + 其它失败仍报错）；`ruff` 与全量 `pytest` 通过。

## 自解压包对话框汉化（2026-09-22）

- 追加修复（同日）：汉化后手工重建自解压包时把**相对路径** `dist/<发布目录>` 传给了 `bz.exe`，Bandizip 据此把 `dist\` 也存进了 payload，用户解压后在目标目录里凭空多出一层 `dist`。`_build_bandizip_sfx()` 现在固定 `cwd=release.parent` 并只传 `release.name`（输出路径先 `resolve()`），与 7-Zip 兜底路径写法一致；重新生成后 payload 顶层只有 `唏嘘南溪DLC一键解锁工具`，实测解压结果为单一文件夹（21,611,055 / `25eaade15958fccfce5db6cb88f237102c5ced441ad988fb74e19637ac373437`）。回归见 `tests/test_release_build.py::test_bandizip_sfx_payload_ignores_relative_parent_directory`。
- 现象：Bandizip 自解压包的对话框（Target Path / Browse / Start / Overwrite…）是英文。排查结论：`bdzsfx.x86.sfx` stub 自身不含任何文案——`bz.exe` 打包时把界面文案作为 UTF-8 文本块**追加在 SFX 文件末尾**（BOM + `[LANG]`，键名与 `Bandizip/langs/SimpChinese.lang` 里的 `STATIC_TARGET_PATH` / `BTN_EXTRACT` 等一致），内容取决于打包机上 Bandizip 的界面语言，默认英文（`bz.exe` 无 `-lang` 开关，改注册表 `HKCU\Software\Bandizip\language` 也无效）。
- 实现：`tools/build_release.py` 新增 `localize_bandizip_sfx_language()`（用内置中文文案替换末尾 `[LANG]` 块，只改追加数据、不动 EXE 与 ZIP 负载），`_build_bandizip_sfx()` 成功后自动调用；找不到该块时保持原样，所以退化到 7-Zip SFX / Python 外壳时不受影响（Python 外壳版本来就是中文）。
- 重新生成：`dist/唏嘘南溪DLC一键解锁工具-v1.0.0-windows-x64-自解压.exe` = 21,611,055 / `25eaade15958fccfce5db6cb88f237102c5ced441ad988fb74e19637ac373437`（别名文件同内容）。首装 ZIP 未变（`adf7890d…`），全量更新包与双源清单都不受影响；`7z l -slt` 复核 payload 267 条、顶层只有发布目录名。
- 验证：新增两条回归（`[LANG]` 块被替换成中文且不动 EXE 前缀、缺少该块时文件保持原样）；`ruff` 与全量 `pytest` 通过。
- 未完成：需要用户双击该自解压包确认对话框真的显示中文（我无法截取桌面验证渲染结果）。

## 构建后自动同步发布器收件目录（2026-09-22）

- 需求：用户发现发布器收件目录 `publisher-workspace/output/updates` 里的 1.0.0 包还是 09-21 21:42 的旧构建，要求把新包搬过去，并且以后每次打包后都自动搬。
- 实现：`tools/build_release.py` 新增 `sync_publisher_inbox()`（把 `dist/updates/SignRiver-DLC-Hub-full-v<版本>-<平台>-x64.zip` 复制到 `publisher-workspace/output/updates`，把 `dist/modules/SignRiver-DLC-Hub-module-v<版本>.zip` 复制到 `publisher-workspace/output/modules`）与 `_latest_source_mtime()` 守卫——模块归档比模块源码旧时跳过并提示先跑 `build_module.py`；没有发布器工作区时静默跳过。`build_release.py` 主流程末尾与 `build_native_release.py` 构建结束都会调用它（来宾机没有 `publisher-workspace`，自动跳过）。
- 本轮已同步：`output/updates/SignRiver-DLC-Hub-full-v1.0.0-windows-x64.zip` = 21,313,696 / `4b7b2846…`；`output/modules/SignRiver-DLC-Hub-module-v1.0.0.zip` = 298,223 / `12b68e83…`。**收件目录里的 macos（09-21 19:49）与 steamos（09-21 20:02）仍是旧包**，要等各自虚拟机重建后才会更新。
- 验证：`tests/test_release_build.py` 新增三条（新鲜产物同步、模块归档过期时跳过并提示、无发布器工作区时不动文件）；`ruff` 通过；全量 `pytest` 通过。
- 文档：`AGENTS.md` 标准构建步骤新增第 7 条，`docs/program-update-release-guide.md` 同步说明自动收件行为。

## 发布器「发布包与归档」增加打开目录按钮（2026-09-22）

- 需求：发布器「发布包与归档 → 发布包与归档模块提交」的两个路径框（三端包收件目录、模块归档目录）原本只有「选择目录」，用户要求在右侧补一个「打开目录」。
- 实现：`src/signriver_publisher/release_center.py` 的两行改为透明 Frame 里并排放「选择目录 / 打开目录」，新增 `_open_directory_entry()`——路径不存在时用提示框说明（不调用系统打开命令），系统调用失败时给错误提示而不是抛异常；打开用 `signriver_common.platforms.open_directory()`（Windows `os.startfile`，macOS `open`，Linux `xdg-open`）。
- 验证：`tests/test_publisher_ui_threading.py` 新增三条（两个按钮与两处连接的源码断言、已存在目录会调用打开、缺失目录与调用失败分别走提示）；`ruff` 通过；该文件 76 项与全量 `pytest` 均通过。
- 未执行：未重新构建发布器 EXE（`tools/build_publisher.py`），日常用 `publisher.py` 跑源码即可看到新按钮。

## 发行包模块目录裁剪（2026-09-22，方案 A）

- 背景：用户发现安装目录 `app/versions/` 里躺着 7 个模块共 6.63 MB，而整个程序才二十几 MB。运行哪个模块只由 `app/state.json` 的 `active_version` 决定，0.1.0（Git 源码基线）与 0.1.4–0.1.7 对用户没有意义。
- 实现：`tools/build_release.py` 新增 `packaged_module_versions()`（当前活动版本 + `config/module-archives.json` 中最近的较低已发布版本）、`_app_tree_ignore()` 与 `copy_app_tree()`；`tools/build_native_release.py::_copy_runtime()` 改为复用 `copy_app_tree()`，Windows 与 SteamOS/macOS 策略一致。回退机制与 `prevent_module_fallback` 保持不变（用户明确选择保留一个回退目标）。
- 数字：安装目录模块占用 6.63 MB → 2.33 MB；ZIP 内模块部分 1.52 MiB → 0.53 MiB，整包约 21.42 MiB → 20.43 MiB。已安装用户不受影响：全量更新只覆盖清单内文件、从不删除目录，旧模块目录仍在本地。
- 验证：新增 `tests/test_release_build.py` 三条用例（版本集合合法性、ignore 行为、真实复制结果只含所选版本）；`ruff check` 通过；`pytest tests/test_release_build.py tests/test_build_native_release.py tests/test_cross_platform_runtime.py` 22 项通过。
- 打包：2026-09-22 01:22 已完成 Windows 侧重建（见下一条），发布目录 `app/versions` 只含 `0.2.0` 与 `1.0.0`；macOS/SteamOS 待重建。

## Windows 1.0.0 打包（2026-09-22 01:22，体积裁剪 + 补丁工具修复）

- 触发：`packaged_module_versions()` 裁剪后的首次构建，同时带上 21:58/22:22 的补丁工具行状态修复与文案收敛（只改代码，未动版本号与线上清单）。
- 命令：`tools/build_module.py --all-versions app\versions` → `tools/build_release.py --upx-dir C:\Users\32173\AppData\Local\tools\upx\upx-5.0.2-win64` → `tools/prepare_update_release.py`（Python 传中文 notes，`--platform-package` 依次带 windows/macos/steamos）。
- 产物（大小 / SHA-256，此版为当前值）：模块 `dist/modules/SignRiver-DLC-Hub-module-v1.0.0.zip` = 298,223 / `12b68e83fa2041999d7ed4c649fcd84e54c6ab63e51737d9df641f5db6136ab6`（与上一版逐字节相同，`config/module-archives.json` 无需改动）；全量更新 `dist/updates/SignRiver-DLC-Hub-full-v1.0.0-windows-x64.zip` = 21,313,696 / `4b7b2846b784f2e4a92e5dda4ed60d7670a8c776deeabd7936e604169bf9871f`；首装 ZIP `dist/唏嘘南溪DLC一键解锁工具-v1.0.0-windows-x64.zip` = 21,329,335 / `adf7890d4926b383953881d9edd424ffd18e8b568ebb4a7f6a6ab03103413598`；自解压 EXE（含同内容别名）`dist/唏嘘南溪DLC一键解锁工具-v1.0.0-windows-x64-自解压.exe` = 21,611,044 / `df2b5c4b39ee9a20b902fff6b521cad4c493496c4a702b5a448c3b68fe62a1b0`。
- 结构核对：发布目录 `app/versions` 只含 `0.2.0` 与 `1.0.0`；全量包 220 个条目（上一版 596 条）、`release-manifest.json` 219 条；包内 1.0.0 模块含 `patch_row_status` 且不含「建议一键修复」；三个 ZIP 的 `zipfile.testzip()` 均为 None。
- 清单：`dist/updates/{gitlink,github}/update-manifest.json` 已重新生成并同步到 `publisher-workspace/output/updates/`（Windows 段 `4b7b2846…` / 21,313,696，macOS/SteamOS 段仍是旧包哈希）。
- 待办：① 上传模块归档、全量包、首装包与两份清单；② macOS/SteamOS 需在各自虚拟机用 `build_native_release.py` 重建（它们的包内客户端仍是旧逻辑，也还是 7 版本布局）；③ 本次仅本地提交，未推送。


> 2026-09-21 及更早的交接条目已归档到 [`archive/HANDOFF-2026-09-23-history.md`](archive/HANDOFF-2026-09-23-history.md)。
