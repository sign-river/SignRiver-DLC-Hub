# 当前任务交接

> 最后更新：2026-08-17（Asia/Shanghai）
> 分支：`main`
> HEAD：`930b435fc46cbf74f6f84cb63603113730231a64`
> 上游状态：相对 `origin/main` 领先 1 个提交；未推送
> 工作区：更新本交接前为干净状态；本次只修改 `docs/agent/HANDOFF.md`，未提交

## 当前有效结论

- `0.2.0` 的统一问题中心、稳定错误分类、下载状态持久化、补丁 SHA-256 强制校验、应用前后复验、异常恢复及疑似安全软件拦截处理已完成，并包含在本地提交 `930b435`（`feat: 完成 0.2.0 问题中心与补丁健壮性优化`）中。
- 启动器的模块加载、更新下载/应用、自动回滚和致命错误已接入共享问题记录；问题动作只使用代码内允许列表，问题存储失败不得遮蔽主业务成功结果。
- `app/versions/0.1.0/` 已同步到 Git 忽略的 `app/versions/0.2.0/`，目标模块元数据为 `version=0.2.0`、`api_version=3`；`publisher-workspace/update-notes.json` 已包含对应中文更新说明。
- 当前只有 Windows 包是基于本轮代码重建的候选；旧 macOS/SteamOS 包早于本轮代码，已从当前平台清单排除，不能作为最终 `0.2.0` 候选。
- macOS `0.2.0` 不再以游戏内运行作为发布门槛。原生重建后只手动验收 DLC 下载及大小/SHA-256、补丁安装、目标文件权限/哈希、失败恢复，并可选确认卸载/原版恢复；必须明确标注“游戏内兼容性未纳入验收范围”。
- 当前线上正式版本仍为 `0.1.7`；`0.2.0` 已本地提交，但尚未上传发布资产或推送代码，不能宣称三平台发布就绪。

## 修改范围

本地提交 `930b435` 包含 39 个受控文件，主要范围如下：

- 客户端问题中心与下载/补丁健壮性：`app/versions/0.1.0/app_entry.py` 及 `app/versions/0.1.0/signriver_app/` 下相关 domain、application、downloads、persistence、diagnostics 文件。
- 共享问题模型：`src/signriver_common/problems.py`、`src/signriver_common/__init__.py`。
- 启动器问题记录与更新/回滚：`src/signriver_launcher/problem_reporting.py`、`api.py`、`full_update_helper.py`、`main.py`、`updater.py`。
- 构建可重复性：`tools/build_release.py`、`tools/build_native_release.py`，显式排除未使用的 NumPy。
- 回归测试：问题模型、客户端问题中心、启动器问题记录、API，以及下载、持久化、诊断、更新、UI、构建和发布源测试。
- 发布元数据与说明：`config/module-archives.json`、`docs/current-progress.md`、`docs/macos-virtual-machine-setup.md` 和 agent 文档。
- Git 忽略但后续发布必须保留并复核：`app/versions/0.2.0/`、`publisher-workspace/update-notes.json`、`dist/`。

## 最新验证

2026-08-17 在 `main@930b435` 上重新执行：

- `python -m pytest -q`：完整测试套件通过。
- `python -m ruff check .`：通过。
- `python -m compileall -q src app/versions/0.1.0 app/versions/0.2.0`：通过。
- `git diff --check`：通过。
- 验证前 `git status --short` 为空；`main` 相对 `origin/main` 为 `ahead 1`。

## 已知失败路线与安全边界

- 不得从问题记录执行命令、脚本或任意 URL；只解析固定动作 ID。
- 不得关闭或暂停 Defender、自动添加排除目录、自动恢复隔离文件；只能引导用户核对来源与哈希后在系统界面手动处理。
- 疑似安全软件拦截后不得复用 `.part` 文件或无限重试；用户确认处理后必须从头下载并重新校验。
- Windows frozen 进程不能直接覆盖正在运行的 EXE；延迟 helper 或超过 onefile 父进程生命周期的子进程必须设置 `PYINSTALLER_RESET_ENVIRONMENT=1`。
- 构建机可选依赖会改变 PyInstaller 分析；项目未引入 NumPy 前必须保留 `--exclude-module numpy` 及其回归测试，不能靠临时卸载依赖控制包体积。
- 三平台清单不能分三次写入同一输出位置；三个原生包齐备后必须在一次 `prepare_update_release.py` 调用中同时传入三个 `--platform-package`。
- PowerShell 直接传中文 notes 可能乱码；继续由 Python 以 UTF-8 读取 JSON，并用 `subprocess.run([...])` 传参。
- Git 忽略的历史版本目录可能污染原生候选包；只可在一次性复制工作区中清理并重建受控版本集合，不得清理主工作区或用户安装目录。

## 风险

1. macOS Intel x64 与 SteamOS x64 尚未从 `930b435` 对应源码重新构建和验收；现存旧包不可复用。
2. 当前双源清单只包含 `windows-x64`，三平台清单、首装包和线上资产仍不完整。
3. 在模块归档和各平台发布包上传并核验前推送，会触发 CI 从 GitLink 恢复归档，可能因线上资产缺失或 SHA-256 不匹配失败。
4. macOS 的退化验收只能证明下载、校验和补丁文件流程，不能证明 Steam/Paradox Launcher 或游戏本体的运行兼容性。

## 下一步

1. 在 macOS Intel x64 与 SteamOS x64 原生主机上，从当前提交对应源码重新构建 `0.2.0` 全量更新包和必要首装包。
2. 按平台执行下载、大小/SHA-256、补丁安装、目标文件权限/哈希和失败恢复验收；macOS 按退化范围记录结果，不做游戏内兼容性声明。
3. 三个平台的新包齐备后，一次性生成双源清单，并核对 URL、size、SHA-256、平台集合和中文 notes。
4. 按“先上传并核验模块归档与所有发布包，最后上传清单”的顺序准备发布；资产就绪后再由用户决定何时执行 `git push origin main`。
5. 新任务开始前先检查 `git status --short`；当前应只看到本交接文档的未提交修改，不得重置或覆盖。

## 本次补充：上下文切换技能

- 已新增项目技能 `.agents/skills/project-context-switch/SKILL.md`，可使用 `/project-context-switch` 替代重复粘贴上下文切换核对提示。
- 技能会读取 `AGENTS.md` 和 `docs/agent/` 交接文档，核对分支、HEAD、Git 状态、上游差异与相关验证，并在任何改动前报告文档与真实工作区是否冲突。
- 本次只新增技能文件，并在 `DECISIONS.md`、`HANDOFF.md` 追加长期流程记录；未重置或覆盖既有未提交内容。
- 验证：`SKILL.md` 已检查 YAML front matter、文件引用和 Markdown 结构；未执行专门自动化测试（仅文档/技能改动）。

- 上下文工作流已拆分为两个项目技能：`project-context-switch`（进入新对话/新任务）和 `project-handoff`（结束任务/转出对话）；二者都支持自然语言触发，斜杠命令仅是可选简写。
