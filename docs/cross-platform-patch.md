# 跨平台客户端与补丁约定

0.2.0 首批支持 `windows-x64`、`steamos-x64` 和 `macos-x64`。Windows 行为与原数据目录保持不变；SteamOS 与 macOS 将可写状态放入用户目录，发行包只保存初始模块和配置。

## 运行目录

- Windows：程序目录下的 `app/`、`data/`、`cache/`。
- SteamOS：`$XDG_DATA_HOME/signriver-dlc-hub` 与 `$XDG_CACHE_HOME/signriver-dlc-hub`，未设置时分别使用 `~/.local/share` 和 `~/.cache`。
- macOS：`~/Library/Application Support/SignRiver DLC Hub` 与 `~/Library/Caches/SignRiver DLC Hub`。

macOS `.app` 内的初始运行资源位于 `Contents/Resources/runtime`。首次启动只复制缺失内容，后续模块更新不会修改已签名 bundle。

## 补丁资产

- Windows：CreamAPI，`steam_api64.dll`，原版备份为 `steam_api64_o.dll`。
- SteamOS：SmokeAPI 64 位 proxy 模式，`libsmoke_api64.so` 发布时命名为 `libsteam_api.so`，原版备份为 `libsteam_api_o.so`，配置为 v4 `SmokeAPI.config.json`。
- macOS Intel：icecream 构建 `libsteam_api.dylib`，原版备份为 `libsteam_api_o.dylib`，配置为 `icecream.ini`。动态库和 `.app` 使用 ad-hoc 签名。

平台二进制不得提交到源码仓库。资源发布记录必须包含上游版本或提交号、SHA-256 与许可证。SmokeAPI Linux 支持和 icecream 均按实验性功能处理；HOI4 是 0.2.0 唯一要求真实游戏验收的非 Windows 卡带。

0.2.0 的固定上游基线：

- SmokeAPI：`v4.1.3`，Unlicense；SteamOS x64 官方 `libsmoke_api64.so` 的 SHA-256 为 `dcb21dc733d38c51b5d673c581edd31f995bbdbaff5582540ece7981eb94b6d2`。
- icecream：[`krnya/icecream`](https://github.com/krnya/icecream) 提交 `0c8f74628d00b944ebbb750bf84c34a91475419d`，MIT；源码归档 SHA-256 为 `49aca4f18cb5a2aedc18d577936d9342a3ff1d937eb2e16b157793c4c85c4b80`；macOS 原生 x86_64 `libsteam_api.dylib` 大小为 `612,912` 字节，SHA-256 为 `68a32d893a00df57010396e439116f33193f44de0d0a817361b4bf1550936daa`。

## 卡带平台字段

`patch.platforms.<platform>` 可独立覆盖：

- `executable_relative_path`
- `dlc_relative_dir`
- `install_relative_dir`
- 补丁文件名、备份文件名和配置文件名
- `config_format`

严禁在 Unix 平台缺少布局时回退到 Windows `.exe` 路径。卡带 JSON 修改后必须同步 `cartridges_index.json` 中的 SHA-256 和字节数。

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

必须先把三个包上传到 GitLink 和 GitHub 并校验，再替换两端清单。
