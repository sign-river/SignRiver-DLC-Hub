# 当前任务交接

> 最后更新：2026-08-17（Asia/Shanghai）
> 分支：`main`
> 基线 HEAD（本轮提交前）：`f31b978f256d1daeedbbe53af2c184cf2c968d9c`
> 状态：本轮改动已完成并验证；按用户要求仅创建本地提交，不推送

## 当前目标与结论

- 已按 `C:\Users\32173\Downloads\PLAN.md` 完成尚未发布的 `0.2.0`“统一问题中心与补丁健壮性优化”；内部发布器未纳入问题中心改造。
- 任务开始时已读取根目录 `AGENTS.md` 及 `docs/agent/README.md`、`PROJECT_CONTEXT.md`、`DECISIONS.md`、`HANDOFF.md`，并核对分支、HEAD、工作区和测试。开始改动前交接与真实工作区无实质冲突，已有未提交改动均被保留。
- 共享层已增加结构化问题模型、异常分类、原子问题存储、30 天/100 条清理、重复事件合并和固定动作允许列表；客户端已增加问题中心、未解决徽标、详情/复制/诊断/重试/解决/删除/清空能力。
- 启动器的模块加载失败、更新下载/应用失败、自动回滚和致命错误已接入统一问题记录；启动器轻量错误窗口提供复制详情、打开日志目录和退出。
- 下载任务已持久化用途、失败阶段和错误码；网络、本地文件、完整性、补丁、更新和内部错误使用稳定分类，不再把本地文件故障统一显示为网络失败。
- 补丁二进制与元数据必须具有 SHA-256；下载提交、应用前、应用后均校验完整性。应用后文件缺失或变化时执行事务恢复/原版恢复并生成问题记录。
- 疑似安全软件拦截会停止当前补丁工作流的无效自动重试并收束同批补丁任务；程序不会关闭 Defender、添加排除项、恢复隔离文件或执行任意 PowerShell，只提供固定的 Windows 安全中心/官方复检动作。macOS 和 SteamOS 不显示 Windows 专属动作。
- 问题存储是非关键诊断副作用；写入失败不会遮蔽已经成功的主业务结果。
- `app/versions/0.1.0/` 已同步到 Git 忽略的 `app/versions/0.2.0/`，除 `module.json` 外内容一致；目标元数据为 `version=0.2.0`、`api_version=3`。
- `publisher-workspace/update-notes.json` 的 `0.2.0` 中文说明已补充问题中心、错误分类、安全软件拦截处理和补丁完整性校验，并以“建议尽快更新。”结尾。
- macOS `0.2.0` 发布验收已按用户决定去除游戏内运行验证；原生重建后的手动门槛为 DLC 下载与大小/SHA-256、补丁安装、目标文件权限/哈希和失败恢复，可选补充卸载/原版恢复，并明确不代表游戏内兼容性通过。

## 发布输入与本地产物

- 模块归档：`dist/modules/SignRiver-DLC-Hub-module-v0.2.0.zip`
  - 大小：`199,755` 字节
  - SHA-256：`28ef829933955893d4a4ad6667cc737fc1493c2bd8748993adc3ec98a3ed23dd`
  - `config/module-archives.json` 已同步，维护版本仍为 `0.1.6`、`0.1.7`、`0.2.0`。
- Windows launcher：`dist/bin/SignRiver-DLC-Hub.exe`
  - 大小：`16,927,805` 字节
  - SHA-256：`89ae7fc6a0979e2d889fef4e47a9ede70453a5e2978c7ae11f20d9add9a79271`
- Windows 全量更新包：`dist/updates/SignRiver-DLC-Hub-full-v0.2.0-windows-x64.zip`
  - 大小：`18,791,906` 字节
  - SHA-256：`16683e3e80cf75ff287b5194d3c32ddeeb0105e2c357169e10cf94b6a5f554bc`
- Windows 初次重建曾因构建环境中的可选 NumPy/MKL 被 `PyInstaller --collect-all PIL` 间接冻结，产生约 `173 MB` 启动器和约 `174 MB` 更新包。`tools/build_release.py` 与 `tools/build_native_release.py` 现统一传入 `--exclude-module numpy`，重建后体积恢复正常，并有构建命令回归测试。
- GitLink/GitHub 双源清单已于 `2026-08-17T11:25:27Z` 重新生成并核验；当前 `platform_packages` **仅含 `windows-x64`**，顶层兼容字段和平台字段均指向上述新 Windows 包，中文 notes 与本地 `update-notes.json` 完全一致。
- 现有 macOS 包（`21,596,182` 字节，SHA-256 `95c81026a782297e9dfe0e2f081ed83aed5dcc22dbe454bc5fdebaab4820fad3`）和 SteamOS 包（`35,508,372` 字节，SHA-256 `91bb1fd54d452b34bae521ccd6e1830317547a51d8c276cfc3da45d9bfef1c6e`）早于本轮问题中心代码，不能作为最终 `0.2.0` 候选，因此已从当前清单排除。

## 验证结果

- `python -m pytest -q`：当前收集 `583` 个测试，完整执行通过。
- `python -m ruff check .`：通过。
- `python -m compileall -q src app/versions/0.1.0 app/versions/0.2.0`：通过。
- `git diff --check`：通过；仅显示 `docs/macos-virtual-machine-setup.md` 和 `src/signriver_common/__init__.py` 的既有 LF/CRLF 提示，无差异错误。
- 发布专项：模块 ZIP 元数据、`config/module-archives.json` 的大小/哈希、两个清单的 notes/平台集合/大小/SHA-256，以及 `0.1.0` 到 `0.2.0` 的源码同步均已用断言脚本复核通过。

## 修改范围

当前工作区中的所有修改均未提交，必须整体保留，不得为了恢复干净状态执行 `reset`、`clean`、`checkout` 或覆盖：

- 客户端问题中心与下载/补丁健壮性：`app/versions/0.1.0/app_entry.py` 及 `app/versions/0.1.0/signriver_app/` 下相关 domain、application、downloads、persistence、diagnostics 文件。
- 共享问题模型：`src/signriver_common/problems.py`（新文件）、`src/signriver_common/__init__.py`。
- 启动器问题记录与更新/回滚：`src/signriver_launcher/problem_reporting.py`（新文件）、`api.py`、`full_update_helper.py`、`main.py`、`updater.py`。
- 构建可重复性：`tools/build_release.py`、`tools/build_native_release.py`。
- 测试：`tests/test_problems.py`、`test_launcher_problem_reporting.py`、`test_client_problem_center.py`、`test_api.py`（新文件）以及下载、持久化、诊断、更新、UI、构建等既有测试扩展。
- 发布元数据与文档：`config/module-archives.json`、`docs/agent/DECISIONS.md`、`docs/agent/HANDOFF.md`，以及工作区中原有的 `docs/current-progress.md`、`docs/macos-virtual-machine-setup.md` 修改。
- Git 忽略但必须保留的发布输入/产物：`app/versions/0.2.0/`、`publisher-workspace/update-notes.json`、`dist/`。

## 已知失败路线与安全边界

- 不得让问题记录携带或执行命令、脚本、任意 URL；动作只能通过代码内允许列表解析。
- 不得关闭或暂停 Defender，不得自动添加排除目录，不得自动恢复被隔离文件；只能引导用户核对来源与哈希后在系统界面手动处理。
- 疑似安全软件拦截后不得继续复用 `.part` 文件或无限重试；用户确认处理后必须从头重新下载并验证。
- Windows frozen 进程不能直接原地覆盖当前运行中的 EXE；延迟 helper 及超过 onefile 父进程生命周期的子进程必须设置 `PYINSTALLER_RESET_ENVIRONMENT=1`。
- 三平台清单不能分三次写入同一输出位置；原生包全部重建后，必须一次调用同时传入三个 `--platform-package`。
- PowerShell 直接传中文更新说明可能乱码；继续使用 Python 以 UTF-8 读取 JSON，并通过 `subprocess.run([...])` 传参。
- 构建机的可选依赖会影响 PyInstaller 分析；项目未使用 NumPy 时必须保留显式排除及其回归测试。

## 风险与下一步

1. 当前只完成了 Windows 原生发布候选。必须在 macOS Intel x64 和 SteamOS x64 原生主机上从当前源码重新构建并验证全量更新包；完成前不得宣称 `0.2.0` 三平台发布就绪。
2. 三个平台的新包齐备后，用一次 `prepare_update_release.py` 调用同时传入三个 `--platform-package`，再核对两个清单的 URL、size、SHA-256 和中文 notes。
3. 正式发布顺序仍为：先上传并核验模块归档、三个全量更新包及首装包，最后上传双源清单。线上资产未就绪前禁止 push，否则 CI 会立即从 GitLink 恢复归档并因哈希/资产缺失失败。
4. 当前线上正式版本仍为 `0.1.7`；`0.2.0` 只是本地候选，尚未上传、commit 或 push。
5. macOS `0.2.0` 已正式移除游戏内运行验收门槛：原生包从当前源码重建后，手动确认 DLC 下载及大小/SHA-256、补丁安装、目标文件权限/哈希、失败恢复，并可选确认卸载/原版恢复。Steam/Paradox Launcher 或游戏本体能否进入画面不再阻塞发布，但必须明确标记“游戏内兼容性未纳入验收范围”，不得宣称已通过。
