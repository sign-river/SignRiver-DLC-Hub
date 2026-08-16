# Codex 上下文切换入口

本目录是 SignRiver DLC Hub 的项目长期记忆入口。它只保存继续工作所需的有效信息，不保存完整聊天记录、重复日志或账号凭据。

## 新任务读取顺序

开始新的 Codex 任务后，在修改文件前依次执行：

1. 阅读根目录 `AGENTS.md`，确认永久规则和发布禁区；
2. 阅读 `docs/agent/PROJECT_CONTEXT.md`，了解项目架构、目录和事实来源；
3. 阅读 `docs/agent/DECISIONS.md`，确认已经采用或放弃的技术路线；
4. 阅读 `docs/agent/HANDOFF.md`，获取当前目标、已完成内容、未解决事项和下一步；
5. 按任务需要阅读 `PLAN.md`、`docs/current-progress.md` 以及对应专题文档；
6. 用 Git 状态、代码和测试命令验证交接内容，发现冲突时以实际工作区为准。

推荐的新任务开场指令：

```text
先读取 AGENTS.md 和 docs/agent/ 下的 README、PROJECT_CONTEXT、DECISIONS、HANDOFF。
然后检查当前分支、HEAD、git status 和与本任务相关的测试状态。
在改动前先指出交接文档与真实工作区是否存在冲突；不要重置或覆盖已有未提交改动。
```

## 结束或切换任务前

1. 当前目标、修改范围、验证结果、阻塞点和下一步写入 `HANDOFF.md`；
2. 三个月后仍有价值的技术选择和失败经验写入 `DECISIONS.md`；
3. 只有稳定的架构、目录或命令变化才更新 `PROJECT_CONTEXT.md`；
4. 永久规则才写入 `AGENTS.md`，临时计划不得塞进根指令；
5. 测试结果必须记录执行日期、完整命令和结果，未运行就明确写“未运行”；
6. 不写密码、令牌、Cookie、Apple/Steam 账号、私有下载凭据或大段原始日志。

推荐的任务结束指令：

```text
准备切换任务。请先验证 Git 状态和相关测试，再更新 docs/agent/HANDOFF.md。
只保留当前有效结论、修改范围、失败路线、风险和下一步；长期决策同步到 DECISIONS.md。
不要提交、推送或覆盖用户已有改动，除非我明确要求。
```

## 文档职责

| 文件 | 生命周期 | 内容 |
| --- | --- | --- |
| `AGENTS.md` | 长期 | 每个任务都必须遵守的规则 |
| `PROJECT_CONTEXT.md` | 稳定 | 项目用途、架构、目录、常用验证方式 |
| `DECISIONS.md` | 累积 | 关键方案、原因、放弃路线和代价 |
| `HANDOFF.md` | 高频更新 | 当前工作区状态、进度、测试和下一步 |
| Git、代码、测试 | 实时 | 最终事实来源 |

`HANDOFF.md` 可以频繁覆盖；`DECISIONS.md` 应追加或修订；不要让同一份临时状态同时散落在多处。
