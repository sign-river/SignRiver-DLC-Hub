---
name: commit-current-changes
description: 为 SignRiver DLC Hub 进行一次本地 Git 提交。用户以自然语言要求“进行一次提交”“提交当前改动”“commit”“创建本地提交”时使用；检查改动范围、验证结果和提交信息后提交，但绝不自动推送。
---

# 进行一次本地提交

用户明确要求提交时，创建一个本地 Git commit；此技能**绝不执行 push**。用户说“提交并推送”时，改用 `commit-and-push`。

## 提交前检查

1. 读取 `AGENTS.md`，尤其是“提交后禁止自动推送”和发布资产顺序约束。
2. 运行并报告：
   ```powershell
   git status --short
   git diff --check
   git diff --stat
   ```
3. 识别本任务应提交的文件。若存在无法归属到当前任务、疑似凭据、构建缓存、发布产物或其他用户改动，停止并请用户指定范围；不要使用 `git add -A` 盲目暂存。
4. 执行与改动相关的最小验证；未执行或失败的验证必须在提交前向用户说明。不要为了让提交通过而重置、清理或覆盖改动。

## 创建提交

1. 仅暂存已确认属于当前任务的精确路径。
2. 再次执行：
   ```powershell
   git diff --cached --check
   git diff --cached --stat
   ```
3. 使用简洁、准确的提交信息；优先 Conventional Commit 风格，例如 `docs: 更新项目交接技能`。用户提供提交信息时原样采用。
4. 执行 `git commit -m "<message>"`。
5. 报告新 HEAD、工作区状态和相对上游差异。

## 禁止事项

- 不执行 `git push`、`git commit --amend`、强制推送、重写历史或 `git reset`，除非用户分别明确提出。
- 不提交 `publisher-workspace/` 中的本地配置、账号/令牌、缓存、测试临时目录或未获确认的构建产物。
- 即使提交完成，也提醒用户：按项目规则，发布资产上传并核验后再由用户决定是否推送。
