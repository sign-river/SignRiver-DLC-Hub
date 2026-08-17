# 当前任务交接

> 最后更新：2026-08-17（Asia/Shanghai）
> 分支：`main`
> HEAD：`0af58d799a67db947499d3289f9da82abdefddf3`（`0af58d7 docs: 添加上下文切换与交接技能`）
> 上游状态：未在本次交接中重新查询；不得据旧记录推断可推送状态
> 工作区：`docs/agent/DECISIONS.md`、`docs/agent/HANDOFF.md` 已修改；另有 4 个未跟踪项目技能目录（运行客户端、运行发布器、本地提交、提交并推送）。本次仅更新本交接文档，未重置、清理、提交或推送。

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
5. 新任务开始前先检查 `git status --short`；交接旧记录中“只存在本交接文档改动”的说法已失效，必须保留并核对 `DECISIONS.md`、`HANDOFF.md` 和 4 个未跟踪项目技能目录，不得重置或覆盖。

## 本次补充：上下文切换技能

- 已新增项目技能 `.agents/skills/project-context-switch/SKILL.md`，可使用 `/project-context-switch` 替代重复粘贴上下文切换核对提示。
- 技能会读取 `AGENTS.md` 和 `docs/agent/` 交接文档，核对分支、HEAD、Git 状态、上游差异与相关验证，并在任何改动前报告文档与真实工作区是否冲突。
- 本次只新增技能文件，并在 `DECISIONS.md`、`HANDOFF.md` 追加长期流程记录；未重置或覆盖既有未提交内容。
- 验证：`SKILL.md` 已检查 YAML front matter、文件引用和 Markdown 结构；未执行专门自动化测试（仅文档/技能改动）。

- 上下文工作流已拆分为两个项目技能：`project-context-switch`（进入新对话/新任务）和 `project-handoff`（结束任务/转出对话）；二者都支持自然语言触发，斜杠命令仅是可选简写。

## 本次补充：运行当前源码技能与验证异常

- 已新增 `.agents/skills/run-current-client/SKILL.md`：自然语言“运行/启动当前客户端程序”会以项目虚拟环境优先运行 `launcher.py`，不构建或启动旧的 `dist` 产物。
- 已新增 `.agents/skills/run-current-publisher/SKILL.md`：自然语言“运行/启动当前服务端程序”默认运行内部发布器 `publisher.py`；本项目没有独立 Web 服务端，若用户指其他服务必须先澄清。
- 2026-08-17 在 `main@0af58d7` 执行完整 `python -m pytest -q` 时，`tests/test_publisher_acceptance.py::test_patch_preparation_refuses_environment_changed_after_baseline` 因 Windows `PermissionError [WinError 5]`（临时 baseline 目录 `Path.replace`）失败；`python -m ruff check .` 与 `python -m compileall -q src app/versions/0.1.0 app/versions/0.2.0` 通过。此前“完整 pytest 通过”的记录与本次真实结果不一致，后续应先复现并定位该权限失败。

- 已新增 `commit-current-changes`（仅本地提交）和 `commit-and-push`（用户明确要求时提交并推送）两个项目技能；后者对发布链路改动会要求先确认线上资产已上传并核验。

## 本次补充：Git 提交技能

- 已新增 `.agents/skills/commit-current-changes/SKILL.md`：用户以自然语言“进行一次提交”“提交当前改动”等触发时，仅做精确暂存后的本地提交，绝不自动推送。
- 已新增 `.agents/skills/commit-and-push/SKILL.md`：仅在用户明确说“提交并推送”等时触发；发布链路改动必须先确认线上模块归档、更新包与清单均已上传并核验，才允许普通推送。
- 两个技能均禁止盲目暂存、强推、重写历史、重置或覆盖其他未提交改动；斜杠命令是可选简写，自然语言同样可触发。
- 验证：已检查两个 `SKILL.md` 的 YAML front matter、命名、描述、行数和 Markdown 结构；`python -m pytest -q tests/test_publisher_acceptance.py::test_patch_preparation_refuses_environment_changed_after_baseline` 本次复跑通过。完整 `python -m pytest -q` 的最近一次结果仍有一次 Windows `WinError 5` 失败记录，尚待稳定复现和定位。

## 本次补充：Skill 执行效率优化

- 已将 `run-current-client` 与 `run-current-publisher` 改为动作优先：对单纯“运行/启动”请求，读取 Skill 后首个工具调用直接启动 GUI 并返回 PID，不再预读项目文档、Git、入口文件或虚拟环境，也不等待、轮询或跑测试。
- 仅在直接启动失败，或用户明确要求诊断、构建、测试时，才做一次性诊断或进入扩展流程。
- 已审计其余 Skill：上下文切换、交接、提交与推送所列核对直接承担工作区一致性、精确暂存和发布资产保护职责，未将其删减为不安全的“无检查执行”。
- 验证：全部 6 个项目 Skill 的 YAML front matter、名称、描述与行数校验通过；`git diff --check` 通过。未启动额外 GUI 实例验证，以避免在用户当前已打开客户端时重复启动。
## 本次交接补充：项目技能与云端资源结论

- 未提交的项目技能共 4 个目录：`.agents/skills/run-current-client/`、`.agents/skills/run-current-publisher/`、`.agents/skills/commit-current-changes/`、`.agents/skills/commit-and-push/`；此前已提交的上下文技能由 `0af58d7` 引入。运行类技能已明确采用“动作优先”：对仅要求启动的消息，读取 Skill 后首个工具调用直接 `Start-Process`，不做无关预检。
- 本轮仅核对并说明云端资源架构，未改动业务代码、发布配置或云端资产：客户端使用 GitLink/GitHub 双源镜像的 Release 静态资产；更新清单按 `windows-x64`、`steamos-x64`、`macos-x64` 选择各自原生更新包。通用、已获授权的数据资源可跨平台复用；依赖系统加载机制的原生组件必须按平台区分。
- 涉及第三方付费 DLC、授权绕过或 DRM 规避的资源，不得在后续工作中设计、整理或下发其具体二进制排列；如需演进资源架构，仅限合法自有/获授权内容，并以静态目录、大小和 SHA-256 校验管理。

## 本次验证

- `git diff --check`：通过（仅出现 LF→CRLF 工作区警告）。
- 本次未运行 pytest、Ruff、构建或 GUI；不得将本轮视为业务功能已验证。
- 完整 pytest 的最近已知结果仍存在一次 Windows `PermissionError [WinError 5]` 间歇失败；目标用例曾单独复跑通过，尚未定位根因。

## 下个上下文的优先事项

1. 先使用 `project-context-switch` 核对交接与实际 Git 状态；重点确认 4 个未跟踪 Skill 目录和两个 agent 文档改动仍存在。
2. 若用户要求提交 Skill 改动，只精确暂存这 6 个项目 Skill 与必要 agent 文档，先审阅 diff；除非用户明确要求，不得推送。
3. 若继续三平台发布工作，仍按本文件前述的原生构建、资产上传、清单核验和后续推送顺序执行。
4. 如处理测试稳定性，优先复现并定位 `tests/test_publisher_acceptance.py::test_patch_preparation_refuses_environment_changed_after_baseline` 的 Windows 文件替换权限异常。

## 本次交接补充：三平台原生库生命周期重构

- 已将客户端和发布器补丁合同从三资产改为“代理库 + AppInfo”两资产；旧 Release 的原生库资产保持可读但被新客户端忽略，卡带字段迁移为 `runtime_original_library_name` 并兼容旧字段别名。
- 已新增持久原生库保险库、PE/ELF/Mach-O x86_64 校验、安装身份与跨进程锁、schema 2 安装凭据、schema 1 迁移、事务化应用/恢复/`repair_patch()` 和持久修复日志。
- 一键修复已改为先完成资源与原生库预检，再原地修复补丁并逐项事务重装 DLC；不再调用 `reset()`，不再预先批量删除 DLC。修复中断后由用户再次点击一键修复，从安全预检阶段幂等重放。
- 已新增 `docs/original-library-lifecycle.md`，并同步更新 `docs/publisher-guide.md` 与 `docs/cross-platform-patch.md`；发布器验收界面不再使用“原版备份 DLL”发布资产术语。

### 本次验证

- `python -m compileall -q app/versions/0.1.0 src/signriver_publisher`：通过。
- `python -m pytest -q tests/test_patch_engine.py tests/test_patch_platforms.py tests/test_repair_journal.py --tb=short`：48 passed。
- 客户端目录、卡带、问题中心、原版恢复和主题相关定向测试：全部通过。
- 发布器工作区、验收和 UI 线程相关定向测试：全部通过；旧术语收尾后再次运行 `tests/test_publisher_acceptance.py tests/test_publisher_ui_threading.py`，全部通过。
- `git diff --check`：通过，仅有现有换行符转换警告。

### 未执行与后续

- 未运行完整 pytest，未构建客户端、发布器、模块归档或更新包，未修改版本号，未提交，未推送。
- 尚未在合法的 Windows x64、SteamOS x64、macOS Intel x64 游戏安装中执行真实启停、应用、修复和恢复验收；发布前必须按 `docs/original-library-lifecycle.md` 的平台清单完成。
- 真实平台验收必须重点确认：任何失败路径不删除唯一可信原生库；Windows 文件占用时阻断；SteamOS 权限位和符号链接处理正确；macOS 不修改或重签用户原生库。