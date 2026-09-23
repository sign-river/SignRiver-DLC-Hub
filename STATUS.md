# 执行状态

> 最后更新：2026-09-23

## 当前状态

三端客户端（Windows x64、SteamOS x64、macOS Intel x64）、稳定启动器、原地全量更新链路和配套 Windows 发布器均已交付。当前线上正式版本为 `1.0.0`，启动器版本 `1.0.0`，Host API 为 `3`，活动模块为 `1.0.0`。

`updates` Release 已上线三平台全量更新包与 GitLink/GitHub 双源清单；`modules` Release 的模块维护基线为 `0.1.7`、`0.2.0`、`1.0.0`。各产物的实测大小与 SHA-256 见 `docs/current-progress.md`。

## 已完成范围

- Windows Steam 游戏发现、多游戏卡带、DLC 下载与内容寻址缓存。
- DLC 事务化安装、回执审计、保守修复和安全卸载。
- 三平台补丁安装、健康检查、修复和原版恢复（Windows CreamAPI、SteamOS SmokeAPI、macOS 替换型解锁库）。
- 稳定启动器、模块更新、全量原地更新、失败回滚和多版本回退链。
- GitLink/GitHub 双下载源，以及公告、卡带、指南、DLC 和程序更新的源联动。
- 发布器资源管理、模块归档、程序更新、双源镜像、上传进度及暂停/继续。
- 强制更新：启动后自动检查并静默重试，重要更新不可跳过。
- 报错指南：一键排错、按现象归档的解决方案、问题记录、运行日志和常用工具。
- 离线兜底：未联网时仍可启动，禁用下载操作并常驻提示。
- 按平台裁剪的发行包模块目录、PyInstaller 原生构建、UPX 压缩和 CI 三平台矩阵。

## 当前验证

- 本地全量 `python -m pytest`：`961 passed`、0 失败、0 跳过（2026-09-23）。
- `python -m ruff check src tests tools app/versions/0.1.0`：通过（2026-09-23）。
- CI（GitHub Actions）在 `windows-latest`、`ubuntu-24.04`、`macos-15-intel` 三平台执行 pytest 与 Ruff：三端全绿（2026-09-22 起，最新 run `35650193420`）。
- `app/state.json`、启动器常量与模块元数据均为 `1.0.0`。
- 三端全量更新包与本地 `dist/` 产物逐字节一致（哈希见 `docs/current-progress.md`）。

## 发布约束

- 模块业务改动先写入 `app/versions/0.1.0/`，发布时同步到新的目标版本目录。
- 每次新版本构建都要更新 `publisher-workspace/update-notes.json`。
- 更新 ZIP 必须先上传并确认可下载，最后才能替换远端清单。
- 提交代码后默认不自动推送；只有用户明确要求时才能推送。
- `publisher-workspace/`、`publisher.local.json`、测试基线和令牌不得提交或上传。

## 后续方向

- Windows 端以维护、缺陷修复和新增游戏卡带为主。
- SteamOS/macOS 端按 `docs/known-issues.md` 的 KI-011 补齐兜底卡带的平台可用性，并按需扩充游戏支持。
- 新版本发布继续保留最近三个模块归档，并验证双源清单和回滚链。