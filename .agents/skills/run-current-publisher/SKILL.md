---
name: run-current-publisher
description: 运行 SignRiver DLC Hub 当前源码中的发布器（用户常称服务端程序）。用户以自然语言要求运行、启动、打开当前服务端、启动发布器或检查发布器界面时使用；默认立即用项目虚拟环境执行 publisher.py，不构建发布器 EXE，也不启动 dist 中的旧产物。
---

# 运行当前服务端／发布器程序

本项目没有独立 Web 服务端；用户所说的“服务端程序”默认指内部发布器。用户未要求诊断、构建或测试时，运行当前源码入口 `publisher.py`，使 GUI 以可见窗口启动。

## 默认快速路径

**读取本 Skill 后，第一条工具调用必须直接启动发布器。**不要先读取项目文档、检查 Git、检查入口文件/虚拟环境、创建计划、等待窗口显示，或运行测试。

在项目根目录一次执行并立即返回 PID：

```powershell
$process = Start-Process -FilePath ./.venv/Scripts/python.exe -ArgumentList 'publisher.py' -WorkingDirectory (Get-Location).Path -PassThru; "发布器已启动，PID：$($process.Id)"
```

- 不使用 `Start-Sleep`、轮询或启动后健康检查；用户只要求“运行”时，成功创建进程即完成。
- 直接报告“已启动”和 PID，不追加不相关的状态、测试或构建说明。

## 仅在快速路径失败时

若上面的命令因虚拟环境不存在或进程启动失败而报错，才用**一次**诊断命令确认 `.venv/Scripts/python.exe` 与 `python` 是否可用，然后以可用解释器重试一次。若仍失败，报告原始错误；不要无限重试或修改项目文件。

## 约束

- 此技能运行的是当前源码，**不要**自动构建 `dist/publisher/SignRiver-Publisher.exe` 或任何发布资产。
- 不要自动上传资源、生成清单、发布更新或执行 Git 推送。
- 若用户实际想启动独立网络服务，先说明本项目当前入口是发布器 GUI，并请其指定目标服务或脚本。
- 用户明确要求诊断“为什么启动失败”时，才读取可用日志或错误输出。
