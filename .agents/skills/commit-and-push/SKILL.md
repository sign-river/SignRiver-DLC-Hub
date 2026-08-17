---
name: commit-and-push
description: 为 SignRiver DLC Hub 创建本地 Git 提交并推送到远程。仅在用户明确以自然语言要求“提交并推送”“commit and push”或“提交后推送”时使用；先核对改动、验证和发布资产风险，禁止强制推送或绕过检查。
---

# 提交并推送

仅当用户明确要求“提交并推送”时使用。它可以在本地改动为空时只推送当前分支；若有当前任务的未提交改动，则先创建本地提交。

## 推送前强制核对

1. 读取 `AGENTS.md`，并检查：
   ```powershell
   git branch --show-current
   git status --short
   git rev-list --left-right --count @{upstream}...HEAD
   ```
   如果当前分支没有上游，明确使用已确认的远程和分支，不得猜测。
2. 若有未提交改动，按 `commit-current-changes` 的流程检查、精确暂存和提交。
3. 检查待推送提交和当前改动是否涉及发布版本、模块归档、更新包、清单、`config/module-archives.json`、`app/versions/`、构建工具或版本号。
4. 若涉及上述发布链路，先向用户明确说明：CI 会在 push 后从线上恢复模块归档并校验 SHA-256；确认对应模块归档、更新包和清单已上传并核验后才能继续。未得到明确确认时，不推送。
5. 运行与改动相关的验证；不得隐瞒失败或未执行项。

## 推送

1. 只使用普通推送：
   ```powershell
   git push origin <当前分支>
   ```
2. 禁止使用 `--force`、`--force-with-lease`、`--no-verify`、重写历史或修改远程 URL，除非用户分别、明确要求。
3. 推送后重新检查 `git status --short` 和相对上游差异，报告远程结果。

## 失败处理

- 若 push 被拒绝或远程分支已有新提交，报告原始错误和当前分支差异；不要自动执行 rebase、merge、reset 或强推。
- 若发布资产尚未就绪，保持本地提交不变，告诉用户需要先完成上传和核验。
