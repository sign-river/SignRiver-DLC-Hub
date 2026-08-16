# 当前任务交接

> 最后更新：2026-08-16（Asia/Shanghai）
> 当前分支：`main`
> 核对时 HEAD：`66ed8ae`（`整理 Windows 端收尾状态与 0.1.7 发布文档`）

## 开始前必须注意

当前工作区包含大量尚未提交的 `0.2.0` 跨平台实现、配置、测试和文档修改，并非干净工作区。新任务不得执行 `git reset --hard`、`git clean`、整目录覆盖或其他会丢失未提交内容的操作。

`HANDOFF.md` 是交接摘要，不是最终事实。开始工作后先运行：

```powershell
git branch --show-current
git rev-parse --short HEAD
git status --short
```

若 HEAD、文件状态或测试结果已经变化，应先更新本文件再继续。

## 当前总目标

完成 SignRiver DLC Hub `0.2.0` 的 Windows、SteamOS x64 和 macOS Intel x64 跨平台适配、原生构建、真实 HOI4 补丁验收、全量更新/回滚 E2E，以及最终三平台发布资产核验。

## 已完成的主要工作

### Windows

- Host API 3、平台识别、Steam 发现、平台化卡带和跨平台更新模型已实现；
- Windows `0.2.0` 模块、全量更新、便携 ZIP/SFX 和发布器已完成本地候选构建；
- `0.1.7 -> 0.2.0` 强制全量升级、自动重启和数据保留已通过真实安装目录 E2E。

### SteamOS

- 虚拟机、SSH、Xorg、1440×900、自动启动和 ACPI 正常关机已处理；
- 原生冻结包和本地全量更新/失败回滚 E2E 已通过；
- HOI4 + SmokeAPI 已完成真实未购买 DLC、日志、审计、修复、移除及原版恢复验收；
- 复现手册见 `docs/steamos-virtual-machine-setup.md`。

### macOS

- VMware 中的 macOS Sequoia（Darwin 24）已安装完成；
- 俄语首次设置已离线修复为简体中文；
- 2026-08-16 已完成首次设置并进入 macOS 桌面，本地账户已经创建；
- 首次设置采用：不迁移数据、不登录 Apple 账户、关闭定位和分析、手动选择中国时区、稍后设置屏幕使用时间、外观自动、系统更新自动下载但手动安装；
- 不在交接文档记录本地账户密码或 Apple/Steam 凭据；
- 复现手册见 `docs/macos-virtual-machine-setup.md`。

## 当前工作区范围

当前未提交改动覆盖以下类别：

- 启动器、全量更新和跨平台路径处理；
- 客户端卡带、Steam 发现、补丁事务与平台适配；
- 发布器三平台资源和清单；
- 多款游戏卡带配置；
- 构建工具、Steam 目录探针和 CI；
- 自动化测试、项目进度和两份虚拟机复现文档。

不要仅凭本摘要判断文件是否属于当前改动，必须以 `git status --short` 和 `git diff -- <path>` 为准。

## 最近验证状态

- 2026-08-16 在 Windows 工作区执行 `python -m pytest`：`524 passed`；
- 同日执行 `python -m ruff check .`、`python -m compileall -q src app\versions\0.1.0 tools tests` 和 `git diff --check`，均通过；
- 同日重新执行 `python tools\build_module.py --all-versions app\versions`，0.2.0 模块归档仍为 `191187` 字节，SHA-256 仍为 `896c2bbb2f8d2fc1f091a1065a0bfb75cc4d8dc2918004f2031055f63a493b34`；
- 同日已在线核验 GitLink 与 GitHub `modules` Release 中的 0.2.0 模块归档：均为 `191187` 字节，SHA-256 均为 `896c2bbb2f8d2fc1f091a1065a0bfb75cc4d8dc2918004f2031055f63a493b34`；
- SteamOS 的原生构建、更新 E2E 和 HOI4 + SmokeAPI 结果已记录在进度文档和复现手册；
- macOS 目前只完成系统安装与 OOBE，尚未进行 Intel icecream、客户端、HOI4 或更新回滚验收。

## 下一步建议顺序

1. 在 macOS VMware 中创建“完成 OOBE、进入桌面”的新快照；
2. 确认 VMware Tools、分辨率、网络、共享/传输源码方式和 SSH；
3. 在 macOS 内安装 Xcode Command Line Tools 与 Rust，按固定上游提交构建 Intel `libsteam_api.dylib`；
4. 构建并启动 SignRiver macOS `.app`，验证 Steam/HOI4 自动发现和手动路径；
5. 完成 icecream 安装、日志、未购买 DLC、审计、修复、移除和原版恢复；
6. 完成 macOS 本地全量更新、自动重启、数据保留和失败回滚 E2E；
7. 重新运行 Windows 全量测试和必要的三平台检查；
8. 核对三平台首次安装包、更新包、清单、SHA-256、更新说明和上传顺序；
9. 后续完整三平台发布资产上传并验证后，再执行最终发布推送。

## 已知风险与避免事项

- macOS 虚拟机依赖 Unlocker 和特定 VMX 拓扑，系统自动升级可能破坏启动；更新前必须关机并创建 VMware 快照；
- 当前虚拟机文件名仍是 `macOS Tahoe`，实际系统是 Sequoia，不要因名称误判或贸然重命名快照链；
- 当前 macOS 快照叶子 VMDK 编号会继续变化，禁止照抄旧编号替换磁盘；
- SteamOS 不能改回 `/usr/bin/steam-jupiter` 作为测试启动入口；
- Windows 不能替代 macOS Intel 环境构建最终 dylib；
- 不得在文档中记录账号密码、Steam Guard、Apple 登录信息或发布令牌。

## 结束下一任务时如何更新本文件

至少更新以下内容：

- 精确日期、分支和 HEAD；
- 本轮目标及实际修改范围；
- 已完成、未完成和明确放弃的事项；
- 测试命令、日期、结果和失败原因；
- 仍存在的工作区风险；
- 下一步按依赖关系排序，而不是按聊天发生顺序罗列。
