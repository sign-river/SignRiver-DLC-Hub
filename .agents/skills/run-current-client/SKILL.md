---
name: run-current-client
description: 运行 SignRiver DLC Hub 当前源码中的客户端程序。用户以自然语言要求运行、启动、打开当前客户端、启动 DLC 管理器或检查客户端界面时使用；默认立即用项目虚拟环境执行 launcher.py，不构建发布包，也不启动 dist 中的旧 EXE。
---

# 运行当前客户端程序

当用户要求运行当前客户端而未要求诊断、构建或测试时，运行工作区源码入口 `launcher.py`，使 GUI 以可见窗口启动。

## 默认快速路径

**读取本 Skill 后，第一条工具调用必须直接启动客户端。**不要先读取项目文档、检查 Git、检查入口文件/虚拟环境、创建计划、等待窗口显示，或运行测试。

在项目根目录一次执行并立即返回 PID：

```powershell
$process = Start-Process -FilePath ./.venv/Scripts/python.exe -ArgumentList 'launcher.py' -WorkingDirectory (Get-Location).Path -PassThru; "客户端已启动，PID：$($process.Id)"
```

- 不使用 `Start-Sleep`、轮询或启动后健康检查；用户只要求“运行”时，成功创建进程即完成。
- 直接报告“已启动”和 PID，不追加不相关的状态、测试或构建说明。

## 仅在快速路径失败时

若上面的命令因虚拟环境不存在或进程启动失败而报错，才用**一次**诊断命令确认 `.venv/Scripts/python.exe` 与 `python` 是否可用，然后以可用解释器重试一次。若仍失败，报告原始错误；不要无限重试或修改项目文件。

## 约束

- 此技能运行的是当前源码，**不要**自动构建模块、更新包或 PyInstaller EXE。
- 不要改动 `app/state.json`、版本目录、配置或用户数据来“让它能启动”。
- 用户明确要求诊断“为什么启动失败”时，才读取可用日志或错误输出。
- 用户明确要求运行已构建版本时，先说明这不是“当前客户端源码”，再按用户指定的 `dist` 产物启动。
