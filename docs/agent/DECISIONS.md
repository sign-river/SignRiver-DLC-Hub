# SignRiver DLC Hub 决策记录

本文件只记录会影响后续任务的方案选择、原因和已放弃路线。临时进度写入 `HANDOFF.md`，操作细节写入对应专题文档。

## 2026-08-16：采用分层的上下文交接文件

### 背景

项目同时包含多平台代码、发布资产、两套虚拟机和较长的真实游戏验收链，仅依靠单个长对话容易丢失约束或重复失败尝试。

### 决定

- 永久规则保留在根目录 `AGENTS.md`；
- 稳定架构写入 `PROJECT_CONTEXT.md`；
- 技术选择和失败路线写入 `DECISIONS.md`；
- 最新任务状态写入可覆盖更新的 `HANDOFF.md`；
- 新任务必须用 Git、代码和测试重新验证交接内容。

### 影响

今后切换任务时不复制整段聊天；只迁移仍有效的目标、结论、失败路线、验证结果和下一步。交接文件不得记录凭据。

## 稳定启动器与版本化模块

### 背景

客户端需要支持模块更新、启动失败回退和全量原地更新，同时尽量减少稳定宿主的变化。

### 决定

使用 `src/signriver_launcher/` 作为稳定宿主，业务 UI 和逻辑放入 `app/versions/<version>/`，通过 `app/state.json` 原子切换活动版本并保留回退链。

### 影响

模块兼容性和 Host API 变更必须显式管理；不能把发行模块当成单一、不可回退的覆盖安装。

## `app/versions/0.1.0/` 是模块源码唯一首改位置

### 背景

多个目标版本目录容易产生分叉和漏同步。

### 决定

日常模块业务修改先写入受 Git 跟踪的 `app/versions/0.1.0/`，发布时再同步到目标版本目录。

### 放弃的做法

不直接只改 `app/versions/0.1.7/`、`0.2.0/` 等生成或发布目录，否则下一次构建会丢失修改或产生版本不一致。

## 发布资产先就绪，代码提交后默认不推送

### 背景

仓库 CI 会在 push 后从线上 GitLink 恢复模块归档并校验 SHA-256。代码和清单先推送、线上资源尚未上传时，CI 必然失败。

### 决定

可以按用户要求提交，但默认不自动推送。发布包与清单先上传并验证，只有用户明确要求“推送”或“提交并推送”时才执行 `git push`。

## 多平台包必须原生构建并精确选择

### 背景

Windows、SteamOS 和 macOS 的可执行格式、路径大小写、Unix mode、签名及补丁资产不同，错平台包可能造成不可恢复的覆盖。

### 决定

- 各平台最终冻结包在对应原生系统构建；
- 更新清单按平台和架构精确选择包；
- 没有匹配平台包时直接拒绝，不回退到其他系统包；
- Windows 发布器统一校验和上传各平台产物，但不替代原生构建。

## SteamOS 验收使用标准内核路线

### 背景

SteamOS OOBE 环境与 VirtualBox VMSVGA、Steam 启动脚本存在兼容问题。

### 决定

保留原 SteamOS 内核作为 GRUB 回退项，并安装带 `vmwgfx` 的并存 LTS 测试内核；测试环境启动 Steam 使用 `/usr/lib/steam/steam`，不使用会清空配置的 `/usr/bin/steam-jupiter`。

### 详细记录

成功步骤、下载链接和失败路线见 `docs/steamos-virtual-machine-setup.md`。

## macOS 验收使用 VMware + Apple Recovery 路线

### 背景

VirtualBox + OpenCore、`e1000e`/`e1000`、桥接网络和若干强制 Recovery 方法在本机均失败或不稳定。

### 决定

- 用 OpenCorePkg 的 `macrecovery.py` 动态获取 Apple BaseSystem；
- 将 Recovery 转为 VMDK 后由 VMware 直接启动；
- 使用 NAT + `vmxnet3`；
- xHCI、PCIe Root Port 和虚拟 USB 键鼠使用已验证 VMX 拓扑；
- 俄语 Setup Assistant 通过 Recovery 离线修改系统级语言 plist；
- 禁止再次使用会导致 EFI 循环的 `nvram recovery-boot-mode=unused` 和 `macosguest.forceRecoveryModeInstall = "TRUE"`。

### 详细记录

完整复现、资源链接、快照链和失败路线见 `docs/macos-virtual-machine-setup.md`。
