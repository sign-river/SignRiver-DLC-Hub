# 跨平台客户端与补丁约定

0.2.0 首批支持 `windows-x64`、`steamos-x64` 和 `macos-x64`。Windows 行为与原数据目录保持兼容；SteamOS 与 macOS 将可写状态放入用户目录，发行包只保存初始模块和配置。本阶段不扩展 Apple Silicon 原生支持。

## 运行目录

- Windows：程序目录下的 `app/`、`data/`、`cache/`。
- SteamOS：`$XDG_DATA_HOME/signriver-dlc-hub` 与 `$XDG_CACHE_HOME/signriver-dlc-hub`，未设置时分别使用 `~/.local/share` 和 `~/.cache`。
- macOS：`~/Library/Application Support/SignRiver DLC Hub` 与 `~/Library/Caches/SignRiver DLC Hub`。

macOS `.app` 内的初始运行资源位于 `Contents/Resources/runtime`。首次启动只复制缺失内容，后续模块更新不会修改已签名 bundle。

三个平台的持久原生库保险库均位于 `context.paths.data/original-libraries/v1`，不属于普通下载缓存；一键修复、常规缓存清理、客户端升级和版本回滚不得清除它。

## 补丁资产与运行时原生库

发布合同统一为两项：**程序提供的代理库 + AppInfo**。游戏原生库不是发布资产；新客户端遇到旧 Release 中遗留的原生库附件时忽略它。

| 平台 | 发布的代理库 | 运行时原生库名 | 格式校验 |
| --- | --- | --- | --- |
| Windows x64 | CreamAPI `steam_api64.dll` | `steam_api64_o.dll` | PE x86_64 |
| SteamOS x64 | SmokeAPI 64 位 proxy，发布名 `libsteam_api.so` | `libsteam_api_o.so` | ELF x86_64 |
| macOS Intel x64 | icecream `libsteam_api.dylib` | `libsteam_api_o.dylib` | Mach-O x86_64 |

代理库运行时仍要求同目录 `_o`，但内容只能来自：

1. 与有效凭据匹配的当前用户原生库保险库；
2. 与有效凭据匹配的游戏目录 `_o`，导入保险库后使用；
3. 首次应用时明确处于原版状态的当前用户游戏主库，先采集保险库再使用。

不得从发布资产、其他游戏、其他安装或其他用户复制原生库。完整生命周期见 [原生库生命周期、迁移与修复操作手册](original-library-lifecycle.md)。

平台二进制不得提交到源码仓库。代理资源发布记录必须包含上游版本或提交号、SHA-256 与许可证。SmokeAPI Linux 支持和 icecream 均按实验性功能处理；HOI4 是 0.2.0 唯一要求真实游戏验收的非 Windows 卡带。

0.2.0 的固定代理库上游基线：

- SmokeAPI：`v4.1.3`，Unlicense；SteamOS x64 官方 `libsmoke_api64.so` 的 SHA-256 为 `dcb21dc733d38c51b5d673c581edd31f995bbdbaff5582540ece7981eb94b6d2`。
- icecream：[`krnya/icecream`](https://github.com/krnya/icecream) 提交 `0c8f74628d00b944ebbb750bf84c34a91475419d`，MIT；源码归档 SHA-256 为 `49aca4f18cb5a2aedc18d577936d9342a3ff1d937eb2e16b157793c4c85c4b80`；macOS 原生 x86_64 `libsteam_api.dylib` 大小为 `612,912` 字节，SHA-256 为 `68a32d893a00df57010396e439116f33193f44de0d0a817361b4bf1550936daa`。

## 卡带平台字段

`patch.platforms.<platform>` 可独立覆盖：

- `executable_relative_path`
- `dlc_relative_dir`
- `install_relative_dir`
- `unlocker_dll_name`
- `runtime_original_library_name`
- 配置文件名和 `config_format`
- `interference_files`：安装补丁前需要清理的显式游戏相对文件路径列表。Windows 使用 `patch.interference_files`，SteamOS/macOS 在各自 `patch.platforms.<platform>` 中独立声明；禁止绝对路径、`..`、目录、符号链接目标和通配符。

补丁安装会在写入代理库、原生库和配置文件前清理这些干扰文件。清理动作属于同一事务：任一删除、写入或最终校验失败都会回滚已删除文件；安装成功后清理结果不会在移除补丁时恢复。未配置该字段时按空列表处理。

`runtime_original_library_name` 只定义代理库运行时需要的同目录文件名，不代表发布资源。解析器暂时接受 `original_backup_dll_name` 和 `patch_original_backup_name` 作为兼容别名，受跟踪卡带应统一写新字段。

严禁在 Unix 平台缺少布局时回退到 Windows `.exe` 路径。卡带 JSON 修改后必须同步 `cartridges_index.json` 中的 SHA-256 和字节数。

## 平台文件操作与签名

### Windows x64

- 文件被游戏、Steam 或启动器占用时立即阻断，提示退出相关进程。
- 所有替换使用同卷临时文件和原子替换。
- 路径检查拒绝符号链接和 reparse point；不能依据约 283 KB 的经验大小判断原生库。

### SteamOS x64

- 严格区分路径大小写，拒绝符号链接越界。
- 部署运行时原生库时保留可用 Unix mode，不以放宽整个目录权限作为修复手段。
- 真实验收覆盖只读、权限拒绝、文件所有权和进程中断。

### macOS Intel x64

- 不修改、不重签用户原生库，采集、部署和应用签名前后均核对其 SHA-256。
- 只对程序提供的代理库及既有要求的应用层执行 ad-hoc 签名。
- 原生库保险库存放在用户 Application Support 数据目录，不写入已签名 `.app` bundle。

## 构建

PyInstaller 产物只能在目标系统原生构建：

```bash
# SteamOS x64
python tools/build_native_release.py --platform steamos

# macOS Intel x64
python tools/build_native_release.py --platform macos
```

SteamOS 输出便携 `tar.gz` 和 flat 全量更新 ZIP；macOS 输出 ad-hoc 签名的 `.app.zip`，自动更新 ZIP 的根目录保存外置清单和完整签名 `.app`。macOS 更新助手先在安装目录旁准备新 bundle，再原子交换整个 `.app`，失败时恢复旧 bundle；清单不会写进已签名应用。清单 schema 保持为 1，并记录 `target_platform`、`target_arch`、可选 `bundle_path` 和 Unix `mode`。

原生构建在启动 PyInstaller 前必须验证 `LAUNCHER_VERSION`、`app/state.json.active_version` 和 `app/versions/<version>/module.json.version` 三者一致，且活动模块元数据存在，避免生成启动器与模块版本错配的发布包。

冻结版 macOS 启动更新助手时，`install_root` 必须是完整 `.app` 路径（`RuntimePaths.install_root`），不能传 `Contents/Resources/runtime`；后者只是可写运行资源来源，不满足整个 bundle 原子交换的前置条件。

## 更新清单

顶层包字段始终指向 Windows 包，以兼容 0.1.7。0.2.0 客户端读取 `platform_packages` 并精确选择当前 `os-arch`，没有匹配项时不得下载其他平台包。

生成双源清单示例：

```powershell
python tools/prepare_update_release.py `
  dist\updates\SignRiver-DLC-Hub-full-v0.2.0-windows-x64.zip `
  --version 0.2.0 --kind full --min-launcher-version 0.1.2 --mandatory `
  --platform-package windows-x64=dist\updates\SignRiver-DLC-Hub-full-v0.2.0-windows-x64.zip `
  --platform-package steamos-x64=dist\updates\SignRiver-DLC-Hub-full-v0.2.0-steamos-x64.zip `
  --platform-package macos-x64=dist\updates\SignRiver-DLC-Hub-full-v0.2.0-macos-x64.zip
```

必须先把三个包上传到 GitLink 和 GitHub 并校验，再替换两端清单。补丁 Release 与客户端全量更新包是两个合同：前者只含平台代理库和 AppInfo，后者仍按目标平台分别构建完整客户端。
