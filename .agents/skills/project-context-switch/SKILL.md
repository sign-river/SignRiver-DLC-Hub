---
name: project-context-switch
description: 执行 SignRiver DLC Hub 的“进入新上下文”核对流程：读取项目规则和交接文档，检查 Git 工作区与相关验证状态，并在任何代码改动前报告交接与真实工作区的冲突。用户以自然语言表示开始新任务、切换上下文、恢复交接工作、先检查项目状态，或要求读取 AGENTS.md、agent 文档、分支、HEAD、Git 状态和测试状态时使用。
---

# SignRiver DLC Hub：进入新上下文

用户开始新任务、切换到本项目的新对话，或要求恢复既有交接工作时，执行以下流程。此技能用于**进入**上下文；任务完成后的交接整理使用 `project-handoff`。

不要求用户输入特定斜杠命令。以下自然语言都应触发本技能：

- “开始这个项目的新任务”
- “切换上下文，先检查一下项目状态”
- “继续上次的工作”
- “读取交接文档后再改”

`/project-context-switch` 只是可选的简写。

## 必须按顺序完成的核对

1. 读取以下文件：
   - `AGENTS.md`
   - `docs/agent/README.md`
   - `docs/agent/PROJECT_CONTEXT.md`
   - `docs/agent/DECISIONS.md`
   - `docs/agent/HANDOFF.md`
2. 读取完成后，检查并记录：
   - 当前分支：`git branch --show-current`
   - 当前 HEAD：`git rev-parse HEAD` 与最近一次提交摘要
   - 工作区：`git status --short`
   - 与上游差异（若存在 `origin/main`）：`git rev-list --left-right --count origin/main...HEAD`
   - 空白错误：`git diff --check`
3. 依据 `HANDOFF.md` 的当前目标和修改范围，执行相关验证：
   - 未指定专项任务时，默认执行：
     ```powershell
     python -m pytest -q
     python -m ruff check .
     python -m compileall -q src app/versions/0.1.0 app/versions/<active_version>
     ```
     `<active_version>` 取 `app/state.json` 的 `active_version`（当前为 `1.0.0`），不要写死具体版本号。
   - 若用户已明确后续任务，优先执行该任务直接涉及的测试；在开始修改前至少说明哪些测试已执行、哪些尚未执行。
4. 将文档记录与实际代码、Git 状态和可重复测试结果逐项比对。

## 改动前的强制报告

在修改任何文件之前，必须先向用户用中文报告：

- 已读取的交接文件；
- 分支、HEAD、相对上游状态；
- 全部未提交改动；
- 已执行测试及结果；
- **交接文档与真实工作区是否存在冲突**。

冲突判断优先级：

1. 当前代码、配置、Git 状态和可重复测试结果；
2. `docs/agent/HANDOFF.md`；
3. `docs/current-progress.md`；
4. `PLAN.md`；
5. `STATUS.md` 与 `README.md` 的历史描述。

如果发现冲突，明确列出冲突内容，并以实际工作区为准；不要通过重置、清理、检出或覆盖来“恢复干净状态”。

## 工作区保护

- 不得重置、清理、覆盖或丢弃用户已有未提交改动。
- 如果需要修改已存在未提交改动的文件，先向用户说明该文件已有改动；仅在后续任务确有必要时，以最小范围保留并叠加修改。
- 不自动执行 `git push`；只有用户明确要求“推送”或“提交并推送”时才可以推送。
- 需要构建或发布时，继续遵守 `AGENTS.md` 的版本、更新说明、归档、清单和发布顺序约束。
