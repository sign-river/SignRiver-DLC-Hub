# 当前任务交接

> 最后更新：2026-08-16（Asia/Shanghai）
> 分支：`main`
> 本轮功能提交：`b7aa825`、`4a6289c`、`19e175a`
> 远端基线：整理前已确认 `main == origin/main == d4193dd`；本轮提交尚待按用户明确指令推送

## 当前有效结论

- `0.2.0` 跨平台实现、既有 CI 修复和 SteamOS 验收保持有效；GitHub Actions 运行 `31937836027` 的 Windows、Ubuntu 24.04、macOS 15 Intel 三个任务均成功。
- macOS Sequoia 15.7.9（Darwin 24.6.0，x86_64）VMware 环境已完成 SSH、VMware Shared Folder、高速源码/产物传输、Xcode/Rust/Python 构建环境准备。
- Intel icecream 已按上游 `krnya/icecream` 提交 `0c8f74628d00b944ebbb750bf84c34a91475419d` 原生构建；`libsteam_api.dylib` 为 `612,912` 字节，SHA-256 `68a32d893a00df57010396e439116f33193f44de0d0a817361b4bf1550936daa`，MIT 许可证已保留在 Git 忽略验收目录。
- 最新 macOS 首装包 `SignRiver-DLC-Hub-v0.2.0-macos-x64.app.zip`：`21,587,550` 字节，SHA-256 `fcfdb50822f8b535dfe2100719f5c5a9b307d149d27617237db62d0fd93d6daf`。
- 最新 macOS 全量更新包 `SignRiver-DLC-Hub-full-v0.2.0-macos-x64.zip`：`21,593,680` 字节，SHA-256 `4eccd3641f219f75a2e9c760762178d773b00777bb4a23dab662f22183ce5982`。
- macOS 包已验证 Mach-O x86_64 与 `codesign --verify --deep --strict`；最新源码在 macOS 为 `528 passed, 1 skipped`，Ruff、compileall 通过。
- macOS `0.1.7 -> 0.2.0` 全量更新成功 E2E 已通过：下载和 SHA-256、平台/架构/完整清单、整个 `.app` 原子交换、自动重启、事务 `confirmed`、用户数据与 `0755` 权限保留、确认后备份清理均验证成功。
- macOS 注入第二次 `os.replace` 失败的回滚 E2E 已通过：事务 `rolled_back`，原 `.app`、签名和用户数据恢复，candidate/backup/failed 路径无残留。
- Steam for macOS 已安装并完成客户端自更新，当前停在登录窗口；HOI4 与 icecream 真实游戏验收尚未执行。

## 修改范围

- 任务开始前已存在且必须保留的未提交修改：工人与资源卡带/索引、发布器卡带与模型、`tests/test_multi_game_cartridges.py`、`docs/agent/DECISIONS.md`、`docs/agent/HANDOFF.md`。
- 本轮代码修改：`tools/build_native_release.py` 增加原生构建版本元数据预检；`src/signriver_launcher/updater.py` 修复 macOS helper 安装根目录；新增 `tests/test_build_native_release.py`、`tests/test_macos_update_helper.py`。
- 本轮文档修改：`docs/current-progress.md`、`docs/cross-platform-patch.md`、`docs/agent/DECISIONS.md`、`docs/agent/HANDOFF.md`。
- 未提交、未推送；macOS/SteamOS 二进制只保存在 `dist/` 或 `publisher-workspace/` 等 Git 忽略目录，不进入源码仓库。

## 验证结果

- Windows 在构建预检修改后曾完成：`528 passed in 9.55s`、Ruff 通过、compileall 通过、`git diff --check` 通过。
- 加入 macOS helper 修复后的 Windows 定向测试：`tests/test_macos_update_helper.py tests/test_updater.py tests/test_cross_platform_runtime.py`，`25 passed`。
- macOS 同步最新源码后的完整测试：`528 passed, 1 skipped`；Ruff、compileall 通过。
- Windows 最新全量验证已完成：`python -m pytest` 为 `529 passed in 9.42s`；`python -m ruff check .`、compileall 和 `git diff --check` 均通过。

## 已确认失败路线

- 不得通过修改共享 `os` 模块的 `os.name` 模拟 Windows；应替换被测模块自己的平台依赖或使用局部 helper。
- 测试不得默认依赖被 Git 忽略的 `app/versions/0.2.0/`；源码级测试使用 `app/versions/0.1.0/`，发布集成测试需先恢复目标归档。
- SteamOS 测试入口不得改回 `/usr/bin/steam-jupiter`；继续使用 `/usr/lib/steam/steam`。
- macOS 不再重复 VirtualBox + OpenCore、`e1000e`/`e1000`、桥接网络或强制 Recovery 标志路线；已验证 VMware + Apple Recovery + NAT + `vmxnet3`。
- macOS 更新 helper 不能把 `Contents/Resources/runtime` 当安装根目录；必须传完整 `.app`。
- 原生发布构建不能只检查 `app/state.json`；必须同时检查活动模块 `module.json` 存在且版本一致。

## 风险

- Steam 登录、Steam Guard、HOI4 许可/下载和游戏内 DLC 状态需要用户账户授权或人工判断；不得把账户信息或凭据写入文档、脚本、日志或回复。
- macOS 的构建与更新 E2E 已通过，但真实 HOI4/icecream 补丁生命周期仍未验收，0.2.0 暂不能发布。
- `app/versions/*`、`dist/` 和发布器工作区包含 Git 忽略产物，不能仅凭本机存在判断干净 checkout 或线上资产完整性。
- macOS 虚拟机依赖 Unlocker、特定 VMX 拓扑和快照链；虚拟机名称可能显示 Tahoe，但实际系统是 Sequoia，禁止据此替换快照叶子 VMDK。
- 推送会立即触发线上模块归档恢复和 SHA-256 校验；发布资产未先上传并核验时不得推送。

## 2026-08-16：提交整理与总体验证

- `b7aa825`：修复 macOS 全量更新安装根目录，并增加原生构建版本元数据预检；
- `4a6289c`：修正工人与资源 DLC 安装根目录；
- `19e175a`：融合 Steam 目录分析、DLL 收集、缺失游戏明细和 DLC 根候选报告；
- 总体验证：`python -m pytest` 为 `533 passed in 11.36s`；`python -m ruff check .`、`python -m compileall -q src tools tests` 和 `git diff --check` 通过；
- 当前仅剩 `docs/agent/DECISIONS.md`、`docs/agent/HANDOFF.md` 待作为交接文档提交，然后按用户明确要求推送 `main`。

## 下一步

1. 用户在 macOS Steam 登录窗口完成登录及可能的 Steam Guard。
2. 安装 HOI4；若账户无许可或 macOS depot 不可用，暂停并由用户决定。
3. 验证原版 HOI4 启动，随后完成 icecream 安装、配置、ad-hoc 签名、日志/DLC 状态、审计、损坏识别、修复、安全卸载和原版恢复闭环。
4. 核对三平台最终候选包和双源清单；先上传并验证发布资产，再按用户明确指令提交或推送。

## 2026-08-16：工人与资源 DLC 根目录修复

- 根据本地真实 DLC 包 `D:\下载\待下载\工人与资源 苏维埃共和国\media_soviet` 核对，内容为 `dlc1`、`dlc2`、`dlc3`、`dlc4` 四个一级目录；
- 已将工人与资源卡带的 `dlc_relative_dir` 从错误的 `media_soviet/sounds` 修正为 `media_soviet`；
- 已同步 `config/cartridges`、发布器内置卡带、默认模型映射、相关测试和本地 `publisher-workspace` 游戏配置；
- 已同步 `cartridges_index.json`：SHA-256 为 `22c84c54657cac9efc1c8f4957a5156baff1ef9f0934a07437a94c649562e157`，字节数为 `1127`；
- 验证：`python -m pytest tests/test_multi_game_cartridges.py tests/test_cartridge_catalog.py tests/test_publisher_workspace.py`，`89 passed`；
- 验证：`python -m ruff check src/signriver_publisher/cartridges.py src/signriver_publisher/models.py tests/test_multi_game_cartridges.py`，通过；
- 卡带修复已提交为 `4a6289c`；未单独构建或发布卡带。

## 2026-08-16：Steam 目录分析与 API64 DLL 收集融合工具

- 目标：把原有 Steam 全游戏目录分析工具与 `steam_api64.dll` 自动收集、归类和压缩能力合并为一个入口。
- 新增 `tools/collect_steam_api64.py`，复用 `tools/steam_directory_probe.py` 的注册表、`libraryfolders.vdf`、manifest 和目录分析逻辑；同一次完整目录扫描同时产出诊断报告并定位 DLL，不重复遍历全部游戏。
- 原有双击入口 `tools/probe_steam_games.bat` 已切换到融合脚本；不再保留单独的 `collect_steam_api64.bat`，避免用户面对两个入口。
- `tools/build_steam_directory_probe.py` 已改为把融合脚本构建进原有 `Steam游戏目录扫描器.exe`；`tools/steam_directory_probe_README.txt` 已同步新的输出结构和隐私说明。
- 每次成功运行会创建时间戳外层文件夹及同名 ZIP；其中包含 TXT/JSON 目录诊断报告、`收集清单.json`、按游戏名建立的子目录和所有找到的 `steam_api64.dll`。
- 多个同名 DLL 会保留游戏内相对路径，避免覆盖；游戏名会清理 Windows 非法字符，同名游戏目录追加 AppID。未找到 DLL 的游戏既记录在清单中，也会在控制台直接列出名称、AppID 和目录。
- 目录诊断报告格式升级为 `report_format: 3`：`dlc_directories` 保留当前安装中真实命中的全部路径，新增 `dlc_root_candidates` 保存上层根目录候选、证据路径及未验证的投影路径；TXT 同样分为“实际命中路径”和“可能的 DLC 安装根目录（仅供人工判断）”。
- 对 `media_soviet/sounds/dlc1` 这类误导案例，报告会同时保留实际路径、`media_soviet` 与 `media_soviet/sounds` 根候选，以及明确标为“未验证存在”的 `media_soviet/dlc1`，不会再用嵌套命中覆盖其他判断可能。
- 新增/更新测试，覆盖融合报告、单次扫描复用、多 DLL、相对路径、大小写、非法/重复游戏名、无 DLL 明细输出、DLC 实际路径与根候选并存。
- 验证：`python -m pytest tests/test_steam_directory_probe.py tests/test_collect_steam_api64.py`，`7 passed`。
- 验证：`python -m ruff check tools/steam_directory_probe.py tools/collect_steam_api64.py tools/build_steam_directory_probe.py tests/test_steam_directory_probe.py tests/test_collect_steam_api64.py`，通过。
- 验证：相关脚本 `compileall`、`python tools/collect_steam_api64.py --help`、冻结 EXE `--help` 和 `git diff --check`，通过；`git diff --check` 仅显示工作区既有 LF/CRLF 转换提示。
- 已重新构建融合版 Windows EXE：`python tools/build_steam_directory_probe.py --upx-dir C:\Users\32173\AppData\Local\tools\upx\upx-5.0.2-win64`，成功；EXE `7,242,476` 字节，分发 ZIP `7,084,450` 字节。
- Steam 工具改动已提交为 `19e175a`；未执行真实本机 Steam 全库收集，避免未经用户确认生成包含游戏 DLL 的本地归档；构建产物位于 Git 忽略的 `dist/`。
