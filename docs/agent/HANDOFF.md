# 当前任务交接

## 发行包模块目录裁剪（2026-09-22，方案 A）

- 背景：用户发现安装目录 `app/versions/` 里躺着 7 个模块共 6.63 MB，而整个程序才二十几 MB。运行哪个模块只由 `app/state.json` 的 `active_version` 决定，0.1.0（Git 源码基线）与 0.1.4–0.1.7 对用户没有意义。
- 实现：`tools/build_release.py` 新增 `packaged_module_versions()`（当前活动版本 + `config/module-archives.json` 中最近的较低已发布版本）、`_app_tree_ignore()` 与 `copy_app_tree()`；`tools/build_native_release.py::_copy_runtime()` 改为复用 `copy_app_tree()`，Windows 与 SteamOS/macOS 策略一致。回退机制与 `prevent_module_fallback` 保持不变（用户明确选择保留一个回退目标）。
- 数字：安装目录模块占用 6.63 MB → 2.33 MB；ZIP 内模块部分 1.52 MiB → 0.53 MiB，整包约 21.42 MiB → 20.43 MiB。已安装用户不受影响：全量更新只覆盖清单内文件、从不删除目录，旧模块目录仍在本地。
- 验证：新增 `tests/test_release_build.py` 三条用例（版本集合合法性、ignore 行为、真实复制结果只含所选版本）；`ruff check` 通过；`pytest tests/test_release_build.py tests/test_build_native_release.py tests/test_cross_platform_runtime.py` 22 项通过。
- 未执行：**没有重新打包**。`dist/` 里现有的包仍是旧的 7 版本布局，下次构建（Windows 与两个虚拟机）才会变小；线上清单里的哈希也仍然指向旧包。

## Windows 1.0.0 重新打包（2026-09-21 22:21，含补丁工具行状态修复）

- 触发：补丁工具行状态修复与随后的文案收敛（见下一条）改了 `app/versions/1.0.0/app_entry.py`，因此重新构建 Windows 侧全部产物。只打包 Windows；macOS/SteamOS 需要各自虚拟机内 `tools/build_native_release.py` 重建后才是同一份代码。
- 命令：`tools/build_module.py --all-versions app\versions` → `tools/build_release.py --upx-dir C:\Users\32173\AppData\Local\tools\upx\upx-5.0.2-win64` → `tools/prepare_update_release.py`（用 Python 传中文 notes，`--platform-package` 依次带 windows/macos/steamos 三方包）。
- 产物（大小 / SHA-256，此版为最终值）：模块 `dist/modules/SignRiver-DLC-Hub-module-v1.0.0.zip` = 298,223 / `12b68e83fa2041999d7ed4c649fcd84e54c6ab63e51737d9df641f5db6136ab6`；全量更新 `dist/updates/SignRiver-DLC-Hub-full-v1.0.0-windows-x64.zip` = 22,423,761 / `d55fd489f97b5583f49ae1b8681b0d2e7186954675e8597433909edcf7cbeb60`；首装 ZIP `dist/唏嘘南溪DLC一键解锁工具-v1.0.0-windows-x64.zip` = 22,464,968 / `e3ca73b598d1efa2ebe0af2473f9d0bc87df75c258a4647d62bf7d9bc52cd523`；自解压 EXE（含同内容别名）`dist/唏嘘南溪DLC一键解锁工具-v1.0.0-windows-x64-自解压.exe` = 22,779,258 / `252ea793e49969c2c50e98a6d9c9e544bc6d1e1c6df86aa2139ce1f863802262`。
- 清单与基线：`config/module-archives.json` 的 1.0.0 记录已更新为新哈希与大小；`dist/updates/{gitlink,github}/update-manifest.json` 已重新生成并同步到 `publisher-workspace/output/updates/{gitlink,github}/`（Windows 段指向新哈希，macOS/SteamOS 段仍是旧包哈希）。
- 验证：三个 ZIP 的 `zipfile.testzip()` 均为 None；包内 `app/versions/1.0.0/app_entry.py` 与工作区一致（含 `patch_row_status`），`dist/唏嘘南溪DLC一键解锁工具/app/versions/1.0.0/app_entry.py` 与源码除换行符外逐字节相同。
- 待办：① 用新包重新上传模块归档、两个更新包与两份清单；② macOS/SteamOS 包内客户端仍是旧逻辑，需在各自虚拟机重建后再更新清单对应哈希；③ 未推送 Git（`config/module-archives.json` 与本文档需随代码提交）。

## 补丁工具行状态改为“以游戏目录与安装记录为准”（2026-09-21）

- 用户反馈：刚解锁后每行显示准确，重启客户端后文件仍在原位却出现「补丁缺失：缓存文件不可用」。根因是 `_show_patch_tool` 的行渲染只用下载缓存快照（`DownloadState.READY` 且缓存文件存在）判断状态：缓存被清理、或快照里的资源名与 release 资产名不一致时，即使游戏目录里的文件完全正确也会报缺失；而同页顶部审计（`audit_recorded`）此时仍显示“已通过审计”，两处自相矛盾。
- 修复：新增模块级纯函数 `patch_row_status()`（`app/versions/0.1.0/app_entry.py`）统一行状态——① 安装记录里该文件 missing/modified → 缺失/异常；② 文件在游戏目录且审计 HEALTHY → 「补丁正常」；③ 已写入但无安装记录 → 只陈述「已写入：缺少安装记录」（不引导用户去点一键修复，用户要求文案到此为止）；④ 未安装时才显示下载与缓存状态。下载缓存只决定「打开文件」与能否直接安装，不再决定补丁是否有效。
- UI 侧配套：新增 `_patch_row_audit()`、`_patch_row_audit_labels()`、`_patch_row_game_path()`；`_patch_row_open_target()` 改为“游戏目录里的文件优先，其次下载缓存资源”；“打开位置”按钮直接定位游戏目录里的真实文件。
- 文案：删除误导性的「补丁缺失：缓存文件不可用」；未安装行的缓存提示改为「尚未安装：缓存资源已失效，请重新下载」。
- 版本对齐：`app/versions/1.0.0/app_entry.py`（`app/state.json` 的 `active_version`）在修改前与 `0.1.0` 逐行一致，已按功能范围同步，两边 SHA-256 均为 `98550f89…`。（`app/versions/*` 被 Git 忽略，需重启客户端才会加载新代码。）
- 验证：新增 `tests/test_patch_row_status.py`（6 例，含“缓存被清理仍显示补丁正常”“缓存状态只用于未安装行”“审计问题按文件上报”“全文不再出现缓存文件不可用”）；`tests/test_ui_theme.py` 中两处补丁工具断言改为按新语义检查；`ruff check` 通过；定向 `pytest` 88 项与全量 `pytest` 均通过。
- 未执行：未重新构建任何发布包（遵守“仅用户明确要求时才打包”约定），所以已发布的 Windows/macOS/SteamOS 包内客户端仍是旧逻辑，需要用新源码重建后才会带上本修复。

## macOS 补丁改为“只换库”模式（2026-09-21）

- 决策：macOS 不再生成任何解锁配置文件（不做 `icecream.ini`，也不做 GSE 的 `steam_settings/DLC.txt`），解锁语义交给替换型库默认的“全部解锁”；游戏只会加载已下载的 DLC。程序行为固定为：把原库改名为 `libsteam_api_o.dylib` 备份 → 写入新的 `libsteam_api.dylib`；还原时先用备份覆盖主库、再删除 `_o` 与遗留配置文件。
- 客户端实现：`PatchConfigFormat` 新增 `none`（`app/versions/0.1.0/signriver_app/domain/patches.py`、`domain/cartridges.py` 白名单）。`infrastructure/patching/engine.py` 在 `none` 模式下不写配置、事务性删除历史遗留的同名配置（如 `icecream.ini`），凭据里的 `ini_sha256` 记为空串；`audit()` / `audit_recorded()` 把“配置文件不应存在”作为健康条件，残留文件会被报成需要修复。
- 界面与功能性流程：补丁工具仍列出 release 的三个资产（解锁库 / 原版库 / AppInfo），macOS 上 AppInfo 只用于下载校验、不再产出配置；`PatchProfile.installed_file_names/paths` 新增，移除补丁与一键修复的确认对话框按该列表显示（macOS 只列两个库文件，不再提 `icecream.ini`）；一键解锁、一键修复（`repair_patch`）、一键移除/恢复原版、补丁状态审计都在同一套引擎路径上适配，全量 `pytest` 通过。
- 补丁工具的行文案（同日）：`PATCH_ROLE_LABELS` + `_patch_row_display()` 让每行显示真实落地文件——Windows 为 `steam_api64.dll` / `steam_api64_o.dll` / `cream_api.ini`，SteamOS 为 `libsteam_api.so` / `libsteam_api_o.so` / `SmokeAPI.config.json`，macOS 只显示 `libsteam_api.dylib` 与 `libsteam_api_o.dylib`（不再显示 AppInfo 行）。下载与校验仍是三个 release 资产，界面只改变展示。
- 同一处按钮语义：配置行的“打开文件”改为打开游戏目录里生成的配置文件（`_patch_row_open_target()`），下载资源行仍打开缓存资源；配置文件尚未生成时不显示该按钮。
- 偶发问题（待观察）：全量 `pytest` 曾有一次 `tests/test_cross_platform_runtime.py::test_macos_full_update_atomically_swaps_and_restores_app_bundle` 失败（`src/signriver_launcher/full_update.py:293` 抛 `FullUpdateError`），单独运行与随后重跑全量均通过，疑似 Windows 上原子替换/删除目录的瞬时占用；若再次复现需记录完整输出。
- 实测发现两处问题并修复（同日）：① 云端旧卡带仍声明 `config_format: cream_ini`，客户端按声明显示出了 macOS 的配置行——现在 `PatchProfile.__post_init__` 对 `PatchPlatform.MACOS` 强制归一为 `none`（保留 `ini_target_name` 用于清理历史文件），不再依赖卡带声明；② 补丁工具把排队中的任务也写成“补丁下载中”——现按 `DownloadState` 分别显示等待/下载/暂停/重试/校验/处理中。
- 上传 GSE 补丁后暴露的三处缺陷（同日修复）：① 客户端补丁资源校验只认瘦 Mach-O，GSE 的 universal（fat，`0xcafebabe`）库被判为“坏包 · invalid binary format”——新增公开助手 `looks_like_native_library()`（engine 已支持 FAT_MAGIC/FAT_CIGAM/FAT_MAGIC_64/FAT_CIGAM_64），客户端校验改用它，避免两处魔数表再次分叉；② “正在下载补丁”时 DLC 库页看不到“取消全部下载”——取消入口的可见性抽成 `_sync_cancel_all_button()`，并在每个界面 tick（`_drain_ui_events`）重新同步，修掉“先进入下载状态、后入队”的顺序问题；③ 点击取消要等好几秒才生效——下载分块从 256 KiB 降到 32 KiB（取消/暂停只在分块之间检查，慢速网络下 256 KiB 要数秒）。
- Stellaris macOS 补丁目录修正（同日）：`otool -L` 证明主程序链接 `@executable_path/../../../libsteam_api.dylib`，即**游戏根目录**那份库（670,560 字节），而不是包内 `stellaris.app/Contents/MacOS/libsteam_api.dylib`（5,195,264 字节）。已把 `config/cartridges/cartridge_stellaris.json`、`src/signriver_publisher/models.py`、`publisher-workspace/games/stellaris/game.json` 的 macOS `install_relative_dir` 改为 `.`，同步 `cartridges_index.json` 哈希，并新增回归 `tests/test_platform_content.py::test_stellaris_macos_patch_targets_the_game_root`。虚拟机里已把之前打错位置的包内库还原为原版（哈希 `0ff4a7c9…`）、删除 `_o`，两条陈旧补丁凭据移到 `~/cs-patch-backup-20260921/stale-receipts/`。**待办：重新发布 Stellaris 卡带（云端安装目录仍指向包内目录），之后一键解锁才会打到根目录。**
- Stellaris macOS 原版资产纠正（同日）：根目录 `libsteam_api.dylib` 已取出到 `.test-artifacts/native-libs/stellaris-libsteam_api_o.dylib`（670,560 字节，SHA-256 `dd19abd4…`，universal i386+x86_64），并替换掉工作区里那份 5,195,264 字节的 `libsteam_api_o.dylib`（`0ff4a7c9…`）——后者与 Windows 的 `steam_api64.dll` 字节完全相同，是错误资产，旧文件备份在 `.test-artifacts/workspace-backups/stellaris-libsteam_api_o.bundle-copy-5195264.dylib`。虚拟机包内 `stellaris.app/Contents/MacOS/libsteam_api.dylib` 目前仍是那个 PE 文件（游戏不加载该副本），建议用 Steam「验证游戏文件完整性」清理。**待办：把新的原版资产重新上传，并重新发布 Stellaris 卡带。**
- 卡带与发布器：`config/cartridges/cartridge_{stellaris,civilization_6,hearts_of_iron_4,rimworld,cities_skylines}.json` 的 `patch.platforms.macos.config_format` 改为 `none`（`ini_target_name` 保留 `icecream.ini` 作为历史清理目标），同步更新 `cartridges_index.json` 的 SHA-256/大小；发布器默认值 `src/signriver_publisher/models.py` 同步改为 `none`。
- 验证：`pytest -q`（全量）通过；新增回归 `tests/test_patch_engine.py::test_config_none_profile_swaps_library_and_clears_legacy_config` 与 `::test_config_none_profile_flags_legacy_config_residue`，以及卡带漂移守卫 `tests/test_platform_content.py::test_macos_cartridges_use_library_only_patch_layout`。
- 已弃用基线：icecream 的 macOS 库缺 `SteamAPI_InitSafe` / `SteamAPI_RestartAppIfNecessary`，会造成白屏，不再用于 macOS 发布；macOS 改用 Goldberg/GSE 的 universal `libsteam_api.dylib`（详见 `docs/cross-platform-patch.md` 的基线段）。
- 待办：把 macOS 的补丁资产替换为 GSE 库（放进 `publisher-workspace/games/<slug>/patches/`）、随包附 LGPL-3.0 许可证与出处；在虚拟机里重建 1.0.0 客户端包并做一次“清空配置文件后仍能进游戏”的复测；SteamOS 端重建仍未执行。

## macOS 城市天际线白屏：改用 Goldberg/GSE 解锁库（2026-09-21）

- 根因：IceCream（`krnya/icecream` 提交 `0c8f746`）只导出 17 个符号，缺 `SteamAPI_InitSafe` 与 `SteamAPI_RestartAppIfNecessary`；`ColossalNative` 在 dyld 加载期解析失败（`Symbol not found: _SteamAPI_InitSafe`），游戏停在白屏。上游 `main` 与该提交源码一致，README 自述仅 Hearts of Iron IV 验证过。
- 候选来源：GitHub 仓库 `da-wood69/goldberg-emulator-macos`（LGPL-3.0，描述为 Goldberg 的 macOS universal 构建），release `macos-universal-2026-09-02` 资产 `ge-macos-universal-2026-09-02.zip`（4,470,778 字节），发布方给出的 sha256 `d17c3d9d1bb9ae23175fdce303ae446e40fe49a7a1642c5d2b3087779ee84de3` 与本地下载一致；包内 `libsteam_api.dylib` 为 5,310,608 字节，sha256 `4ad99f3d949f22878ee8309bfdf792f4f7c20aef4a166a0b8c479876043d58bc`，universal（x86_64 + arm64）。
- 符号门槛：`ColossalNative` 需要 12 个 Steam 符号，候选库导出 1,188 个，差集为空（含 `SteamAPI_InitSafe`、`SteamAPI_RestartAppIfNecessary`）。
- VM 部署：现状备份到 `~/cs-patch-backup-20260921/`（IceCream 库、原版 `libsteam_api_o.dylib`、`icecream.ini`）；把候选库放到 `Cities.app/Contents/Plugins/ColossalNative.bundle/Contents/MacOS/libsteam_api.dylib`；新建 `steam_settings/DLC.txt`（76 条 `appid=名称`）、`steam_settings/steam_appid.txt`（255710）、`steam_settings/force_language.txt`（schinese）。
- 验证：经 Paradox 启动器进入游戏主菜单成功（用户确认），新 `Player.log` 不再出现 `Symbol not found`；未执行真实存档、联机与 DLC 内容可用性检查。
- VM 游戏性能调优（同日）：`~/Library/Application Support/Colossal Order/Cities_Skylines/gameSettings.cgs` 的 8 个画质键（dofMode/antialiasing/texturesQuality/shadowsQuality/shadowsDistance/anisotropicFiltering/levelOfDetail/vsync）全部写 0（原地改 4 字节小端整数，文件长度不变）；Unity 偏好改为窗口化 1280x720 且画质 0；Steam `localconfig.vdf`（userdata/1390570194）在 `Software/Valve/Steam/apps/255710/LaunchOptions` 写入 `-screen-width 1280 -screen-height 720 -screen-fullscreen 0 -noWorkshop -disableMods`。修改前备份在 `~/game-perf-backup-20260921/`。仍未解决：`Cities` 的输入监控权限需要用户在系统设置里勾选（TCC 数据库读不到，无法代改）。
- VM 操作备忘：Steam 的正确启动入口是 `/Applications/Steam.app`（`open -a` 该路径）；`Steam.AppBundle` 本身没有可执行入口，`launchctl submit` 与直接跑 `steam_osx` 都不稳定。改 `localconfig.vdf` 前必须先用 `steam_osx -shutdown` 正常退出，否则会被覆盖。来宾的 `py312` Python 可用于二进制/文本补丁。
- 待办：客户端与发布器目前仍按 `cream_ini` 生成 `icecream.ini`（`app/versions/0.1.0/signriver_app/infrastructure/patching/engine.py`、`src/signriver_publisher/cream.py`，以及各卡带 JSON 的 `config_format`/`ini_target_name`），要改用 GSE 的 `steam_settings/DLC.txt` 才能让“一键解锁”产出同一套结果；LGPL-3.0 需随包附许可证与出处；候选库哈希需固定进发布清单。本轮未上传、未发布、未推送。

## macOS 1.0.0 启动崩溃修复与原生重建（2026-09-21）

### 强制更新改成“启动自动检测 + 锁住界面”（2026-09-21）

- 用户反馈：发布时勾了强制更新，但打开 0.2.0 客户端没有任何提示，必须手动去设置里检查。根因：`app_entry.py` 的启动检查写作 `if updates.enabled and updates.check_on_startup`，而 `config/update.json`（以及 `config/defaults/update.json`）自模块化架构起一直是 `check_on_startup: false`，因此启动根本不检查；`mandatory` 只影响“检测到后能否跳过”。
- 修改：启动检查改为只看 `updates.enabled`（不再依赖该配置），并在 `config/update.json`、`config/defaults/update.json` 把 `check_on_startup` 设为 `true`；新增 `_lock_window_for_mandatory_update()` / `_release_mandatory_update_lock()`。更新提示改为自定义对话框 `_ask_update_choice()`（措辞委婉，不再写“必须更新”）：强制更新为「立即更新」「退出程序」，关闭窗口等同退出程序；非强制更新为「下载更新包」「暂不更新」。强制更新**不自动下载**：确认后锁住主窗口、隐藏取消/暂不更新入口，只留一个「下载更新包」按钮（触发 `_begin_update_download(release, mandatory=True)`）；非强制更新在更新区同时提供「下载更新包 / 取消下载 / 暂不更新」三个入口（`_prepare_optional_update` / `_dismiss_optional_update`）。下载/安装失败或模块安装完成后解锁。回归覆盖在 `tests/test_ui_theme.py::test_startup_update_check_is_unconditional_and_blocks_mandatory_release` 与 `tests/test_ui_units_mandatory.py::test_update_check_consumes_mandatory_flag`。
- 用户本机那份 0.2.0 测试副本（`D:\唏嘘南溪DLC一键解锁工具-v0.2.0-windows-x64\...`）已把 `config/update.json` 的 `check_on_startup` 改为 `true`（原文件备份 `.test-artifacts/user-0.2.0-update.json.bak`），用于验证“启动自动检查 → 强制更新”链路。
- 重新构建：1.0.0 模块归档 295,492 / `554a27b5…`（`config/module-archives.json` 已同步）、Windows 全量更新 22,418,716 / `302b8130…`、首装 ZIP 22,459,923 / `37167acf…`、自解压 22,776,138 / `52164914…`；两份清单重新生成并同步到发布器收件目录，四条记录校验通过。macOS/SteamOS 包未重建（包内模块仍是旧版本；两端暂无用户）。

### 发布兼容性事故：卡带 config_format=none 打挂老客户端（2026-09-21）

- 现象：用户打开已保存的 0.2.0 客户端验证 0.2.0 → 1.0.0 更新时，DLC 目录读取失败，提示 `无法从远端加载游戏卡带 stellaris: unsupported patch config format: 'none'`（GitLink/GitHub 都一样）。
- 根因：为让 macOS 不生成配置文件，我把 5 张卡带 macOS 段的 `config_format` 写成了新值 `none`；老客户端解析卡带时会校验**所有平台段**，不认识 `none` 直接判定卡带解析失败，Windows 上也一样。云端 5 张卡带都已带该值。
- 修复：卡带声明全部改回 `cream_ini`（仓库卡带 + `cartridges_index.json` + 发布器默认值 + 工作区 `game.json`），macOS“不生成配置文件”改由客户端内部归一化保证（新客户端行为不变）；新增硬约束测试 `test_all_cartridges_keep_legacy_config_formats`，并更新原 macOS 卡带用例断言。
- 重建：Windows 首装 ZIP（22,457,878 / `764c24dc…`）、自解压（22,773,906 / `1687703a…`）、全量更新（22,416,674 / `67764f99…`）与两份清单已重新生成并同步到发布器收件目录；macOS/SteamOS 包与 1.0.0 模块归档不含卡带，哈希未变。
- 待办（用户侧）：**重新发布这 5 张卡带到双源**，老客户端才能恢复读取；然后重跑 0.2.0 → 1.0.0 更新验证，并按新哈希上传 Windows 包与清单。

### Windows 1.0.0 构建与三平台更新清单（2026-09-21）

- 模块归档：`tools/build_module.py --all-versions app\versions` 重建 0.1.4–1.0.0；`config/module-archives.json` 同步基线 0.1.7（未变）/0.2.0（`e011d633…`，289,622）/1.0.0（`9505e6b8…`，295,000）。
- Windows 产物：`dist/唏嘘南溪DLC一键解锁工具-v1.0.0-windows-x64.zip`（22,459,368 字节，SHA-256 `aa00aead…`）、`dist/唏嘘南溪DLC一键解锁工具-v1.0.0-windows-x64-自解压.exe`（22,776,398，`5085e4fe…`，另有别名 `唏嘘南溪DLC一键解锁工具-自解压.exe`）、`dist/updates/SignRiver-DLC-Hub-full-v1.0.0-windows-x64.zip`（22,418,164，`954fd6aa…`）；启动器 EXE 17,702,368 字节。
- 自解压包确认走 Bandizip 后端：`7z l` 显示 `Type = zip`、`Embedded Stub Size = 344076`，payload 顶层就是发布文件夹（无 11.9 MB 外壳）。
- 三平台清单：`dist/updates/{gitlink,github}/update-manifest.json`，`version=1.0.0`、`kind=full`、`min_launcher_version=0.1.2`、`mandatory=true`，`platform_packages` 含 `windows-x64`（22,418,164 / `954fd6aa…`）、`macos-x64`（24,942,781 / `6253a688…`）、`steamos-x64`（45,076,499 / `85f6f0cc…`）；四条记录与实际文件哈希/大小核对一致（脚本 `.test-artifacts/verify_manifest_100.py`）。
- 待办（用户侧）：上传模块归档（0.1.7/0.2.0/1.0.0 及各自 `.release.json`）、Windows 首装 ZIP 与自解压包、三平台全量包、两份 `update-manifest.json`，然后 `git push`；0.2.0 → 1.0.0 的真实更新 E2E 仍未执行。
- 发布器收件目录与更新说明（同日）：`publisher-workspace/output/updates/` 放入三端 1.0.0 全量包、`output/modules/` 放入 1.0.0 模块归档（用发布器自己的 `ArtifactCollector` 验证：采纳 3 个包 + 1 个模块归档），并把双源清单放到 `output/updates/{gitlink,github}/update-manifest.json`；0.1.7/0.2.0 模块归档需走「兼容发布 → 单源发布模块归档」。
- 1.0.0 更新说明最终定稿（只写「报错指南」界面与其内容；不写平台支持与实现细节，因为能看到这条更新的只有 Windows 测试版用户）："【1.0.0】正式版更新：\n· 新增「报错指南」界面，把启动失败、游戏打不开、补丁不生效、文件被安全软件拦截等常见问题整理成参考解决方案；\n· 每个问题都给出具体操作步骤，并可直接跳转到相关工具或系统设置；\n· 新增「常用工具」入口：一键排错、日志资料收集、补丁工具、杀毒软件检测等，都能在界面里直接运行并查看结果；\n· 问题解决不了时，可一键收集诊断资料并附上事件 ID 反馈，方便定位。\n建议尽快更新。"；两份清单已用该文案重新生成并同步到 `publisher-workspace/output/updates/{gitlink,github}/`。

### Windows 自解压包解压落点修复（2026-09-21）

- 用户反馈：自解压 EXE 把文件解压到当前目录，曾在 D 盘根目录铺满整个盘。根因是 `tools/build_release.py::_build_sfx` 用 `.\<发布目录>\*` 只把目录**内容**打进 7z payload，SFX 又把内容解压到用户选择的目录。
- 修复：改为 `7z a <archive> <发布目录名>`（连目录本身一起打包），解压后只会得到 `<目标目录>\唏嘘南溪DLC一键解锁工具\...` 一个文件夹，与 ZIP 内布局一致。
- 验证：新增 `tests/test_release_build.py::test_sfx_payload_keeps_the_release_folder`（本机有 7-Zip 时构建真实 SFX 并断言 payload 条目都以发布目录名开头，无 7-Zip 时 skip）；另用 `.test-artifacts/verify_sfx_layout.py` 实测解压，目标目录里只有发布文件夹一项。全量 `pytest` 与 Ruff 通过。
- 备注：现有 `dist/` 里 0.2.0 的 SFX 仍是旧行为，1.0.0 构建时会自动带上此修复；标准 `7z.sfx` 生成的 SFX 会要求管理员权限（既有行为，与本次修复无关）。
- 自解压后端最终定为 **Bandizip 优先**（同日）：`bz c -sfx:bdzsfx.x86.sfx <输出.exe> <发布目录>`，产物 ≈ ZIP + 34 KB stub、asInvoker 不弹 UAC、解压为单一发布文件夹；`_find_bandizip()` 走 PATH + 注册表（本机 `D:\useless\bandizip\Bandizip\bz.exe`）。7-Zip SFX 与 Python 外壳版依次兜底；外壳版实测 11,878,865 字节，用户认为为这点便利多 11 MB 不划算，故不作为默认。
- 经验：Bandizip SFX 解压到「进程当前目录」，双击时即 EXE 所在目录；测试里不要启动 GUI SFX（会弹窗等待、遗留进程会锁住产物），改为用 7-Zip 解 payload 校验布局，见 `test_bandizip_sfx_payload_extracts_into_a_single_folder`。

### SteamOS 1.0.0 最终构建与部署（2026-09-21，来宾 16:50）

- 来宾通道：SSH `deck@192.168.233.130`；快照回滚后 `~/.ssh/authorized_keys` 被清空，本轮改用 paramiko（临时 venv `.test-artifacts/tmp-ssh-venv`，密码只放进程环境变量 `SIGNRIVER_GUEST_PASSWORD`）并按 `.test-artifacts/steamos_guest.py` 重新装回公钥。辅助脚本 `steamos_guest.py` 支持 run/put/get/install-key，`get` 的参数顺序是「本地 远端」。
- 构建：源码归档 `signriver-steamos-source-20260921j.tar.gz` 解包到 `~/signriver-steamos-build`（保留 `.venv-steamos`、`build/`、`dist/`），`tools/build_native_release.py --platform steamos` 状态码 0；来宾定向测试 180 项通过（需先 `mkdir -p .test-artifacts`，归档不含该目录，否则 pytest 的 basetemp 报错）。
- 产物：`dist/SignRiver-DLC-Hub-v1.0.0-steamos-x64.tar.gz`（44,817,592 字节，SHA-256 `b40eea969eb5237a45acad82c771672ee620db0f2bdbba0e13947ee41cd79cac`）与 `dist/updates/SignRiver-DLC-Hub-full-v1.0.0-steamos-x64.zip`（45,076,499 字节，SHA-256 `85f6f0cc1c23a2e954a426af9a60ebf8b0897e39063e046d3425c9464ee1d60d`）；`tar -tzf`/`unzip -t` 通过，`dist/SignRiver-DLC-Hub-steamos-x64/SignRiver-DLC-Hub` 为 x86-64 ELF、权限 755。
- 一致性：发布包内 `SignRiver-DLC-Hub-steamos-x64/SignRiver-DLC-Hub` 与部署目录中的二进制同为 `b5ba62251543190d1860994c3a982741b4894aa146c648d389306e2aeebd8f41`；主机副本在 `.test-artifacts/steamos-dist/`，哈希与来宾一致。
- 部署与验收：数据目录模块 `1.0.0` 改名为 `1.0.0.bak-20260921-final` 由启动器重新播种（新模块含 `looks_like_native_library` 等今日修复），以 `DISPLAY=:0 XAUTHORITY=/home/deck/.Xauthority` 启动 GUI（PID 10182/10186），`launcher.log` 出现 `Starting application module 1.0.0` 与同步结果，等待用户界面验收。
- 备注：宿主与来宾时钟相差约 2.8 小时，`tar` 解包会提示 "time stamp in the future"，属提示性告警，不影响构建。

### macOS 1.0.0 最终发布包（2026-09-21 04:49 构建，冻结）

- 产物：`dist/SignRiver-DLC-Hub-v1.0.0-macos-x64.app.zip`（24,927,322 字节，SHA-256 `0757469ad194e1df3206a6269d2fcb52f24fc1d46cc7584dd0823c4ed851e77f`）与 `dist/updates/SignRiver-DLC-Hub-full-v1.0.0-macos-x64.zip`（24,942,781 字节，SHA-256 `6253a6884057fa50e29b5a7c4b86352c302f731e717aa14b6f6680f2d66fd50f`）。
- 一致性核对：主机 `.test-artifacts/macos-dist/` 两份 ZIP 的 SHA-256 与来宾 `~/macos-build-20260919/dist/` 完全一致；app.zip 内 `SignRiver-DLC-Hub.app/Contents/MacOS/SignRiver-DLC-Hub` 与来宾已部署 `.app` 的主程序同为 `4207b430…`；包内 `config/cartridges/cartridge_stellaris.json` 为 `13d92382…`（含 `install_relative_dir: "."` 修正）。虚拟机中正在运行的客户端（04:49:45 启动）就是该 `.app`。
- 版本信息：模块 `1.0.0`、`api_version 3`、宿主 `app/state.json` 的 `active_version=1.0.0`、`bad_versions` 为空；`codesign --verify --deep --strict` 通过，主程序 x86_64。构建源码为 `f86b0a9`。
- 该包包含本日全部修复：tkinter 终结器线程守护、补丁工具按平台显示落地文件、macOS 强制无配置、下载状态文案、universal（fat）Mach-O 资源校验、取消入口常驻与 32 KiB 分块、Stellaris 补丁目录指向游戏根目录。
- 待办（内容侧，非本包）：重新上传 Stellaris 的 macOS 补丁资源（`libsteam_api_o.dylib` 换成根目录 670,560 字节那份）并重新发布 Stellaris 卡带；云端卡带当前仍声明包内目录。

- 现象：macOS VM 中 1.0.0 客户端启动约 5 秒后进程退出，`~/Library/Logs/DiagnosticReports` 新增两份 `.ips`，异常为 `EXC_BAD_ACCESS (SIGSEGV) KERN_INVALID_ADDRESS at 0x8`。
- 根因：崩溃线程是后台工作线程，堆栈为 `sorted(生成器)` → 构造对象 → `gc_collect_main` → `slot_tp_finalize` → `Tkapp_Call` → `Tcl_EvalObjv` → `Tk_FontObjCmd`。即工作线程触发 GC 时回收了 tkinter 字体对象，在非主线程执行了 Tcl `font delete`；macOS 自带 Tk 未开启线程支持，直接段错误。
- 修改：新增 `app/versions/0.1.0/signriver_app/infrastructure/tk_thread_safety.py`，包装 `tkinter.font.Font`、`tkinter.Variable`、`tkinter.Image` 的 `__del__`——工作线程只登记待清理对象，主线程执行真正的 Tcl 释放；`app_entry.py` 在创建 Tk 后调用 `install_tk_finalizer_guard()`，UI 事件泵每 50ms 调 `flush_tk_finalizers(limit=200)`。已定向同步到活动模块 `app/versions/1.0.0/`。
- 测试：新增 `tests/test_tk_thread_safety.py` 4 项（守护幂等、工作线程延后、主线程立即释放、入口接线）。Windows：`pytest -q tests/test_tk_thread_safety.py tests/test_ui_theme.py tests/test_platform_content.py tests/test_loader.py` 通过，Ruff 通过。来宾（macOS，py312 环境临时安装 pytest 9.1.1）：`pytest -q tests/test_build_native_release.py tests/test_tk_thread_safety.py tests/test_cross_platform_runtime.py` 16 项通过。
- 重建：来宾 `/Users/signriver/macos-build-20260919`，`python tools/build_native_release.py --platform macos` 状态码 0，产物 `dist/SignRiver-DLC-Hub.app`、`dist/SignRiver-DLC-Hub-v1.0.0-macos-x64.app.zip`、`dist/updates/SignRiver-DLC-Hub-full-v1.0.0-macos-x64.zip`。
- 校验：两个 ZIP `unzip -t` 通过；主程序 `Mach-O 64-bit executable x86_64`；`codesign --verify --deep --strict` 通过；包内 `app/state.json.active_version=1.0.0`、`app/versions/1.0.0/signriver_app/` 81 个文件且含 `tk_thread_safety.py`、`config/guides` 16 条。
- 启动验证：先把数据目录旧模块改名为 `1.0.0.bak-20260921-tkguard` 让启动器重新播种；`open dist/SignRiver-DLC-Hub.app` 后进程存活超过 40 秒，无新增崩溃报告，日志出现 `Starting application module 1.0.0`、`已同步 2 款游戏`、`已加载 都市天际线 (Cities: Skylines) 的支持数据`。用户当前看到的客户端就是该 `dist/SignRiver-DLC-Hub.app`。
- 回传：`.test-artifacts/macos-dist/SignRiver-DLC-Hub-v1.0.0-macos-x64.app.zip`（24,920,421 字节，SHA-256 `5b334546022434997122bb1011cb52b6830f2ac41bc0ba0f99f05c1f6df6771f`）、`.test-artifacts/macos-dist/SignRiver-DLC-Hub-full-v1.0.0-macos-x64.zip`（24,935,654 字节，SHA-256 `34e3e995bf29b8af5bf1386f6937696fb9334cc40641d3b82f7a99654ed2359f`），与来宾 `shasum -a 256` 一致。
- 本轮未执行：真实 DLC 下载、补丁生命周期、Steam 登录、游戏内运行、上传、线上清单切换、push；未安装到 `~/Applications`。

## 发布器原生平台补丁资源构建（2026-09-21）

- 根因：客户端已经按平台卡带字段读取原生库名，但发布器构建只复制 Windows 的 `unlocker.dll` / `original.dll` 及旧别名，不会处理 `patch_platforms` 声明的 macOS/SteamOS 原生文件。
- 修改：`src/signriver_publisher/workspace.py` 在 `published_platform_resources[platform].patch == true` 时，按 `patch_platforms` 中的 `unlocker_dll_name` / `runtime_original_library_name` 从 `patches/` 复制到发布输出目录，并纳入 `catalog.json`；缺文件时构建失败。未标记为已发布的平台不受影响。
- 测试：`tests/test_publisher_workspace.py` 新增原生库输出与缺文件阻止构建用例；全文件 87 项、`tests/test_dlc_catalog.py` 14 项、`tests/test_patch_platforms.py` 18 项通过；Ruff 与 `git diff --check` 通过。
- 真实工作区核对：macOS 有 `libsteam_api.dylib` 与 `libsteam_api_o.dylib`；SteamOS 当前只有 `libsteam_api_o.so`，缺少 `libsteam_api.so`。现有 SmokeAPI 候选文件为 `publisher-workspace/acceptance/steamos/SmokeAPI-v4.1.3/libsteam_api.so`（尚未复制到 Stellaris 的 `patches/`）。
- 本轮未执行：真实 Stellaris 重新构建、上传、双源回读、线上主表切换、push。

## macOS 原生库导出与 SteamOS VM 切换（2026-09-20）

- 从 macOS Sequoia VM 的 Stellaris 安装目录复制截图选中的 `libsteam_api.dylib` 到 Windows 临时导出目录 `.test-artifacts/libsteam_api.dylib`；文件大小 `5,195,264` 字节，SHA-256 为 `0FF4A7C9D44A600BF514D069982D884C0ADD67431BAE24341063C18CE310A11F`。
- macOS VM `D:\\vmware\\macos-vm\\macOS Sequoia.vmx` 已通过 VMware 正常挂起；未关机、未修改 VMX。
- 已启动 SteamOS VMware VM：`D:\\vmware\\steamos\\workstation\\SteamOS-VMware.vmx`。未执行 SteamOS 构建命令或资源上传。

## 原生平台补丁资源严格隔离（2026-09-20）

- 云端核对：GitLink/GitHub 的 `hub/cartridges_index.json` 当前所有卡带仅标记 `windows`；群星 `stellaris` Release 只有 `unlocker.dll`、`original.dll`、`steam_api64.dll`、`steam_api64_o.dll` 与 AppInfo，没有 `libsteam_api.so` 或 `libsteam_api.dylib`。当前不能宣称云端已有 SteamOS/macOS 补丁。
- 根因：客户端 `ReleaseCatalogService` 过去只按通用角色名解析补丁，macOS/SteamOS 也会接受 Windows DLL，并在后续哈希审计中被误判为健康。
- 修改：`app/versions/0.1.0/signriver_app/application/dlc_catalog.py` 对 Windows 保留旧别名；SteamOS/macOS 只接受卡带平台字段声明的原生库文件名。缺少原生资产时返回缺失补丁，阻止下载与“一键解锁成功”；同步到活动模块 `app/versions/0.2.0/`，未整目录覆盖。
- 测试：`tests/test_dlc_catalog.py` 新增 Windows DLL 不得冒充 macOS 补丁、原生文件名可正常解析的回归覆盖；`pytest -q tests/test_dlc_catalog.py tests/test_cartridge_catalog.py tests/test_platform_content.py` 全部通过；compileall 与 `git diff --check` 通过。
- 发布说明：当前发布器的 `patches/` 工作区和既有 Release 命名只产出 Windows 稳定资产；仅把 `.so`/`.dylib` 丢进目录不会自动生成原生 Release 资产，也不会更新 `published_platform_resources`。原生补丁需先按平台扩展发布器资源合同、生成平台原生资产并回读双源，再把对应平台标记为已发布。本轮未上传、未改云端。
- 当前 VM 已同步客户端模块源码；需重启 VM 中活动客户端后，macOS 无原生补丁时应显示资源缺失/禁用一键解锁，而不是成功。

## 发布器补丁列表显示文件大小（2026-09-20）

- 修改范围：`src/signriver_publisher/content_management_ui.py`、`tests/test_publisher_ui_threading.py`。
- 本地资源页的“补丁资源”列表现在在文件名与删除按钮之间显示每个补丁文件大小；使用 B/KB/MB/GB 格式，文件在刷新期间消失时显示“大小未知”。DLC 文件夹列表保持原布局。
- 已执行：`& .\\.venv\\Scripts\\python.exe -m pytest -q tests/test_publisher_ui_threading.py`（通过）；`& .\\.venv\\Scripts\\python.exe -m ruff check src/signriver_publisher/content_management_ui.py tests/test_publisher_ui_threading.py`（通过）；`& .\\.venv\\Scripts\\python.exe -m compileall -q src/signriver_publisher/content_management_ui.py tests/test_publisher_ui_threading.py`（通过）；`git diff --check`（通过）。
- 未执行：发布器 GUI 人工验收、构建发布器 EXE、资源发布和推送；当前源码发布器需重启后查看界面。

## macOS 平台主表兼容修复（2026-09-20）

- 根因：VM 用户目录的远端卡带主表只含 Windows `platform_resources`，启动时优先于包内兼容主表，导致 macOS 默认群星被误判为“暂无资源”。这不是 `.app` 缺少 `0.2.0` 模块。
- 修改：`app/versions/0.1.0/signriver_app/application/cartridge_catalog.py` 的主表选择会跳过不包含当前平台任何资源的候选，优先使用包内兼容主表；同步测试 `tests/test_cartridge_catalog.py`。活动版本目录中的同文件已定向同步，未整目录覆盖。
- 验证：定向卡带/平台测试 46 项通过；Ruff、compileall、`git diff --check` 通过；macOS 原生包重新构建成功，ZIP 完整性、x86_64 Mach-O、签名和包内 `0.2.0` 内容均通过。
- VM：`/Users/signriver/macos-build-20260919/dist/SignRiver-DLC-Hub.app` 已重新打开，客户端进程存活。旧 Windows-only 数据主表已可恢复地备份为 `~/Library/Application Support/SignRiver DLC Hub/data/cartridges/cartridges_index.windows-only-20260920.json`；未删除数据。
- 手动打开路径：Finder 使用 `Command + Shift + G`，输入 `/Users/signriver/macos-build-20260919/dist/SignRiver-DLC-Hub.app`。
- 本轮未执行真实 DLC 下载、补丁生命周期、Steam 登录、游戏内运行、上传、线上清单切换、commit 或 push。

## 发布器同名 DLC 导入覆盖（2026-09-20）

- 修改范围：`src/signriver_publisher/workspace.py`、`tests/test_publisher_workspace.py`。
- 修复同名 DLC 重复导入时递增生成新编号的问题：按安装目录名匹配已有托管目录，并通过暂存备份安全替换；单个 DLC、根目录批量导入、共享文件对和聚合叶目录导入均支持同名覆盖，覆盖失败会恢复旧目录。
- 已新增 `CityStations` 同名覆盖回归测试；替换已有 DLC 不会消耗新的自动编号。
- 已执行：`& .\\.venv\\Scripts\\python.exe -m pytest -q tests/test_publisher_workspace.py tests/test_publisher_ui_threading.py`（通过）；`& .\\.venv\\Scripts\\python.exe -m ruff check src/signriver_publisher/workspace.py tests/test_publisher_workspace.py tests/test_publisher_ui_threading.py`（通过）；`& .\\.venv\\Scripts\\python.exe -m compileall -q src/signriver_publisher tests/test_publisher_workspace.py tests/test_publisher_ui_threading.py`（通过）；`git diff --check`（通过）。
- 未执行：发布器 GUI 人工验收、构建发布器 EXE、资源发布和推送；当前源码发布器需重启后验证界面导入流程。

## macOS 原生构建收尾（2026-09-19）

- 活动客户端版本：`0.2.0`；实际活动模块为 `app/versions/0.2.0/`，本轮采用“正式原生构建”对齐方式，未修改版本号、`app/state.json` 或线上清单。
- Windows 侧工作区在开始和结束时均保持无受跟踪改动；分支 `main`，HEAD `d12a25a47afc2eee17fa4c5d6f2c2a8e07ef3e18`。交接文档此前记录的旧 HEAD 已过时，以 Git 实际状态为准。
- 已执行定向测试：`\.venv\Scripts\python.exe -m pytest -q tests/test_build_native_release.py tests/test_macos_update_helper.py tests/test_cross_platform_runtime.py`，13 项通过。
- 来宾：`D:\vmware\macos-vm\macOS Sequoia.vmx`，通过 VMware Tools 受控通道连接；来宾确认 `Darwin 24.6.0 x86_64`。因系统 Python 仅为 Xcode 占位程序，在 `/Users/signriver/py312` 放置临时 Intel Python 3.12.14，并安装 Command Line Tools for Xcode 16.4 以提供 `install_name_tool`；未修改 VMX、未升级 macOS。
- 构建目录：`/Users/signriver/macos-build-20260919`；命令：`python tools/build_native_release.py --platform macos`，构建状态码 0。
- 来宾产物：`dist/SignRiver-DLC-Hub.app`、`dist/SignRiver-DLC-Hub-v0.2.0-macos-x64.app.zip`、`dist/updates/SignRiver-DLC-Hub-full-v0.2.0-macos-x64.zip`。
- 首装 ZIP（修复后重建）：`24,578,931` bytes，SHA-256 `03C148B01722B00AD52D68D53790AA6EEC67A2B77802CE44982FFDEEEC847C05`；全量更新 ZIP：`24,593,063` bytes，SHA-256 `0E319EAE87EAE0AC77E2839EF9C223F5620B87E7A36C013E2D8DBBCB5AD67BF8`。Windows 侧临时副本位于 `.test-artifacts/fixed-app.zip` 与 `.test-artifacts/fixed-update.zip`。
- 验证通过：两个 ZIP 在来宾 `unzip -t`；主程序 `Mach-O 64-bit executable x86_64` 且 `lipo -info` 为 `x86_64`；`codesign --verify --deep --strict`；`.app` 内 `app/versions/0.2.0/signriver_app/` 80 个文件、`app/state.json.active_version` 为 `0.2.0` 且 `bad_versions` 为空。
- 启动验证：从隔离构建目录用 `open dist/SignRiver-DLC-Hub.app` 启动，观察至少 8 秒有进程记录；无新增 `~/Library/Logs/DiagnosticReports` 崩溃报告；随后仅结束隔离进程，未安装到 `~/Applications`。
- 未执行：真实 DLC 下载、补丁生命周期、Steam 登录、游戏内运行、远端上传、线上清单切换、commit、push；未修改或覆盖用户应用目录。


## 本次任务（Windows 客户端打包，2026-09-13）

- 活动客户端版本：`0.2.0`；按正式 Windows 流程重新构建模块归档和全量更新包。
- 修正 `config/module-archives.json` 中 `0.1.7`、`0.2.0` 归档的大小与 SHA-256，使其与本地新构建产物一致。
- 产物：`dist/updates/SignRiver-DLC-Hub-full-v0.2.0-windows-x64.zip`、`dist/<中文产品名>-v0.2.0-windows-x64.zip`、对应自解压 EXE，以及 `dist/modules/SignRiver-DLC-Hub-module-v0.2.0.zip`。
- 已验证：`build_module.py --all-versions`、`build_release.py --upx-dir ...`、`prepare_update_release.py` 均成功；Windows 全量 ZIP 与 GitLink/GitHub 清单大小和 SHA-256 一致；`git diff --check` 通过。
- Windows 全量 ZIP：`22092217` bytes，SHA-256 `ec410df53833f7b20a102ea3d3a4ff6e6d128bd885eb15f7c3bb16cfa2657dae`。
- 未执行：真实远端上传、发布器批次、GUI 人工验收和推送；用户如需发布，需先上传并完成双源回读核验。

> 本文件只保留当前状态；历史流水见 [`archive/`](archive/)。长期约束见 [`DECISIONS.md`](DECISIONS.md)。

## 当前状态（2026-09-13）

- 分支：`main`
- HEAD：`aac4d6ab8ce77487c6c4ea575319d60d1a1e3760`（本任务提交后以 Git 实际提交为准）
- 活动客户端版本：`0.2.0`，`app/state.json` 与活动模块一致。
- 工作区：本次开始时干净；全量测试问题修复已验证，按项目约定随本次交接提交。

## 最新任务（全量测试修复）

- 修改范围：`src/signriver_publisher/models.py`、`tests/test_client_problem_center.py`。
- `PublisherCartridge.to_dict()` 现在将新增的 `patch_interference_files` 元组显式序列化为 JSON 列表，补齐发布工作区完成清单的稳定序列化契约。
- 同步更新三项已经落后于现有产品行为的客户端测试：补丁应用结果夹具包含干扰文件清理字段；一键解锁成功文案使用当前简化提示；从问题记录打开解决方案时验证来源和返回上下文。
- 已执行：4 个原失败测试定向运行通过；`\.venv\Scripts\python.exe -m pytest -q` 全量 886 项通过；`\.venv\Scripts\python.exe -m ruff check .` 通过；`\.venv\Scripts\python.exe -m compileall -q src app/versions/0.1.0 app/versions/0.2.0` 通过；`git diff --check` 通过。
- 未执行：GUI 人工验收、构建、发布和推送；本任务只修复自动化回归与序列化遗漏。

## 最新任务（界面调整）

- 修改范围：`src/signriver_publisher/ui.py`、`src/signriver_publisher/cartridge_management_ui.py`、`tests/test_publisher_ui_threading.py`、`docs/publisher-guide.md`。
- “DLC 时效检查”已移到发布器左侧独立工作区；结果不再使用弹窗，而是在页面内的可滚动四列表持久展示游戏、资源提交时间、Steam 最新 DLC 上线时间和状态。卡带与公告页已移除该检查按钮与临时状态区域。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests/test_dlc_freshness.py tests/test_publisher_ui_threading.py -k "freshness or cartridge_management or task_oriented_workspace"`（8 项通过）；`\.venv\Scripts\python.exe -m ruff check src/signriver_publisher/ui.py src/signriver_publisher/cartridge_management_ui.py tests/test_publisher_ui_threading.py` 通过；`\.venv\Scripts\python.exe -m compileall -q src/signriver_publisher tests/test_publisher_ui_threading.py` 通过；`git diff --check` 通过。
- 未执行：发布器 GUI 人工验收、完整测试、构建发布器 EXE、资源发布和推送。

## 最新任务

- 修改范围：`src/signriver_publisher/{freshness,workspace,cartridge_management_ui}.py`、`src/signriver_publisher/__init__.py`、`tests/test_dlc_freshness.py`、`tests/test_publisher_ui_threading.py`、`docs/publisher-guide.md`。
- 发布器“游戏支持数据 → 卡带与公告 → 卡带与公告”新增“检查全部 DLC 时效”。任务在后台逐个请求 Steam DLC 上线时间，与当前本地/发布输出的资源提交时间比较；不会写入 AppInfo、改动资源或触发发布。结果会逐项显示“资源过时”“未过时”或“无法判断”。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests/test_dlc_freshness.py tests/test_publisher_ui_threading.py -k "freshness or cartridge_management"`（7 项通过）；`\.venv\Scripts\python.exe -m ruff check src/signriver_publisher/freshness.py src/signriver_publisher/workspace.py src/signriver_publisher/cartridge_management_ui.py src/signriver_publisher/__init__.py tests/test_dlc_freshness.py tests/test_publisher_ui_threading.py` 通过；`\.venv\Scripts\python.exe -m compileall -q src/signriver_publisher tests/test_dlc_freshness.py tests/test_publisher_ui_threading.py` 通过；`git diff --check` 通过。
- 未执行：发布器 GUI 人工验收、完整测试、构建发布器 EXE、资源发布和推送。

## 前次任务

- 修改范围：`app/versions/0.1.0/app_entry.py`、`tests/test_ui_theme.py`；定向同步运行时忽略目录 `app/versions/0.2.0/app_entry.py`。
- 修复切换下载源时始终加载索引默认游戏的问题。现在会捕获并刷新用户当前选中游戏的卡带，避免非默认游戏的完成回调被丢弃、页面永久停在“正在加载”。
- 已采用“定向同步到当前活动模块”：基线和 `0.2.0` 的同一代码块均已更新；用户重启客户端后生效，未构建或发布新版本。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests/test_ui_theme.py`（74 项通过）；`\.venv\Scripts\python.exe -m ruff check app/versions/0.1.0/app_entry.py tests/test_ui_theme.py` 通过；`\.venv\Scripts\python.exe -m compileall -q app/versions/0.1.0 app/versions/0.2.0` 通过；`git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

## 本次任务

- 修改范围：`config/guides/guide_graphics_device_compatibility.json`、`tests/test_platform_content.py`；运行时配置目录直接生效，不修改客户端模块。
- 已删除图形设备指南中的“打开日志资料收集”操作入口；保留图形设备工具入口及联系开发者入口。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests\test_platform_content.py -k graphics`（1 项通过）；`\.venv\Scripts\python.exe -m ruff check tests\test_platform_content.py` 通过；`\.venv\Scripts\python.exe -m compileall -q tests\test_platform_content.py` 通过；`git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

- 修改范围：`config/guides/guide_graphics_device_compatibility.json`、`tests/test_platform_content.py`；运行时配置目录直接生效，不修改客户端模块。
- 已删除图形设备指南中“它仅适用于 Windows，不代表所有启动失败都由图形配置引起”的补充句，以及“修复失败或仍无法启动”标题与其说明段；操作入口与联系开发者入口保留。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests\test_platform_content.py -k graphics`（1 项通过）；`\.venv\Scripts\python.exe -m ruff check tests\test_platform_content.py` 通过；`\.venv\Scripts\python.exe -m compileall -q tests\test_platform_content.py` 通过；`git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

- 修改范围：`config/guides/guide_graphics_device_compatibility.json`、图形设备指南资源、`tests/test_platform_content.py`；运行时配置目录直接生效，不修改客户端模块。
- 图形设备指南已删除旧的“无法创建图形设备”长截图，改为两步说明与新配图：先在工具中打开 DirectX 诊断工具、于“显示”页确认 DirectDraw/Direct3D 加速状态；若显示“未启用”或“已禁用”，关闭诊断工具后点击“修复图形设备配置”。保留修复前备份、用户确认、管理员权限及修复后重启说明。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests\test_platform_content.py -k graphics`（1 项通过）；`\.venv\Scripts\python.exe -m ruff check tests\test_platform_content.py` 通过；`\.venv\Scripts\python.exe -m compileall -q tests\test_platform_content.py` 通过；已视觉核对两张新资源；`git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

- 修改范围：`app/versions/0.1.0/app_entry.py`、两份 P 社启动器指南、`docs/tool-item-ui-spec.md`、`tests/test_ui_theme.py`；定向同步运行时忽略目录 `app/versions/0.2.0/app_entry.py`。
- 统一用户可见名称为“P 社启动器修复”：工具卡片、详情标题和按钮均使用相同表述；指南和工具规范已同步。原内部标识 `paradox-launcher-warning` 保持不变，既有指南跳转兼容。
- 活动客户端版本为 `0.2.0`；已定向同步同一代码块，用户重启客户端后生效，未构建或发布新模块。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests\test_ui_theme.py tests\test_platform_content.py -k paradox_launcher`（2 项通过）；`\.venv\Scripts\python.exe -m ruff check app\versions\0.1.0\app_entry.py tests\test_ui_theme.py` 通过；`\.venv\Scripts\python.exe -m compileall -q app\versions\0.1.0\app_entry.py app\versions\0.2.0\app_entry.py` 通过；旧表述检索无结果；`git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

- 修改范围：`app/versions/0.1.0/app_entry.py`、`tests/test_ui_theme.py`；定向同步运行时忽略目录 `app/versions/0.2.0/app_entry.py`。
- 修复 P 社启动器安装程序下载完成后的 UI 状态：此前“打开安装程序”按钮未保留引用，下载回调只更新卸载按钮，导致已下载时仍禁用；现在回调会将该按钮设为可用。
- 活动客户端版本为 `0.2.0`；已定向同步同一代码块，用户重启客户端后生效，未构建或发布新模块。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests\test_ui_theme.py -k paradox_launcher`（1 项通过）；`\.venv\Scripts\python.exe -m ruff check app\versions\0.1.0\app_entry.py tests\test_ui_theme.py` 通过；`\.venv\Scripts\python.exe -m compileall -q app\versions\0.1.0\app_entry.py app\versions\0.2.0\app_entry.py` 通过；`git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

- 修改范围：`app/versions/0.1.0/app_entry.py`、`tests/test_ui_theme.py`；定向同步运行时忽略目录 `app/versions/0.2.0/app_entry.py`。
- 修复 P 社启动器安装工具：官网按钮改为 `https://www.paradoxinteractive.com/our-games/launcher`；下载安装程序改为官方 `v2/paradox-launcher-installer-windows` 端点，移除旧 `/installer/Paradox%20Launcher.exe` 的 404 地址。用户提供的 `_gl` / `_ga` 统计参数未固化，避免会话参数过期；无参数端点可稳定重定向到当前安装程序。
- 活动客户端版本为 `0.2.0`；已定向同步同一代码块，用户重启客户端后生效，未构建或发布新模块。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests\test_ui_theme.py -k paradox_launcher`（1 项通过）；`\.venv\Scripts\python.exe -m ruff check app\versions\0.1.0\app_entry.py tests\test_ui_theme.py` 通过；`\.venv\Scripts\python.exe -m compileall -q app\versions\0.1.0\app_entry.py app\versions\0.2.0\app_entry.py` 通过；`curl.exe -I -L --max-time 30 -A "SignRiver-DLC-Hub" "https://launcher.paradoxinteractive.com/v2/paradox-launcher-installer-windows"` 返回 302 后 200；`git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

- 修改范围：`app/versions/0.1.0/app_entry.py`、新增 `app/versions/0.1.0/signriver_app/infrastructure/paradox_launcher.py`、`tests/test_paradox_launcher_discovery.py`、`tests/test_ui_theme.py`；定向同步运行时忽略目录 `app/versions/0.2.0/app_entry.py` 和同名基础设施模块。
- 修复 P 社启动器警告清除工具：不再按目录名字符串排序，而是按全部数字版本段比较；并且仅接受同时包含 `Paradox Launcher.exe`、`resources/app.asar` 与目标 `steam_api64.dll` 的完整安装目录。`.cpatch` 单独存在的残缺版本目录会被忽略。
- P 社启动器修复的原始 DLL 备份名已统一为 `steam_api64_o.dll`，与普通游戏补丁链路一致；此前仅这条专用路径错误使用 `steam_api64.original.dll`。
- 活动客户端版本为 `0.2.0`；已定向同步同一逻辑，用户重启客户端后会优先处理完整的 `launcher-v2.2026.11.1`，而不是错误选中 `launcher-v2.2026.8.1`；未构建或发布新模块。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests/test_paradox_launcher_discovery.py tests/test_ui_theme.py -k "paradox_launcher"`（3 项通过）；`\.venv\Scripts\python.exe -m ruff check app/versions/0.1.0/app_entry.py app/versions/0.1.0/signriver_app/infrastructure/paradox_launcher.py tests/test_paradox_launcher_discovery.py` 通过；`\.venv\Scripts\python.exe -m compileall -q app/versions/0.1.0/app_entry.py app/versions/0.1.0/signriver_app/infrastructure/paradox_launcher.py app/versions/0.2.0/app_entry.py app/versions/0.2.0/signriver_app/infrastructure/paradox_launcher.py` 通过；`git diff --check` 通过。
- 已执行：`\.venv\Scripts\python.exe -m pytest -q tests/test_paradox_launcher_discovery.py tests/test_ui_theme.py -k "paradox_launcher"`（3 项通过）；`\.venv\Scripts\python.exe -m pytest -q tests/test_ui_theme.py -k paradox_launcher`（1 项通过）；`\.venv\Scripts\python.exe -m ruff check app/versions/0.1.0/app_entry.py app/versions/0.1.0/signriver_app/infrastructure/paradox_launcher.py tests/test_paradox_launcher_discovery.py` 与 `\.venv\Scripts\python.exe -m ruff check app/versions/0.1.0/app_entry.py tests/test_ui_theme.py` 均通过；两轮 `compileall` 与 `git diff --check` 通过。
- 未执行：客户端 GUI 人工验收、完整测试、构建、发布和推送。

## 最近结论

- 已确认 `0.1.5 → 0.2.0` 报错的主要发布风险是同版本存在多套包，且 GitHub、GitLink、本地清单的大小/SHA-256 不一致。
- `0.2.0` 使用 Host API 3；最低启动器版本必须以真实冻结包 E2E 验证结果为准，不能只依据清单可解析来声明兼容。
- 详细事故记录已归档至 [`HANDOFF-2026-09-04-history.md`](archive/HANDOFF-2026-09-04-history.md)。

## 当前风险与下一步

- 本次修复降低跨源失败造成的半套发布窗口，但同一源站的远端附件替换仍依赖 provider 的幂等恢复；未实现远端附件内容备份/事务回滚。
- 后续发布必须执行单一构建产物、双源回读校验，以及仍受支持旧启动器到新版本的更新矩阵测试。
- 线上发布前需确认远端清单和附件完全匹配；不得使用 `dist`、`publisher-workspace/output` 或历史包中的旧清单。
- 未完成：真实远端包完整下载复核、下一版本发布门禁自动化；均不得写成已验证。

## 最近验证

- `python -m pytest -q tests/test_full_update.py tests/test_updater.py tests/test_loader.py tests/test_state.py tests/test_versioning.py tests/test_release_build.py tests/test_build_module.py tests/test_restore_module_archives.py`：通过。
- `python -m compileall -q src app/versions/0.1.0 app/versions/0.2.0 tools`：通过。
- `git diff --check`：通过。
- 未执行 GUI、真实上传、推送或完整远端包下载。
## 最新任务（SteamOS 原生构建）

- 已将当前工作区源码（含未提交的跨平台补丁选择与索引过滤修复）及活动模块 `0.2.0` 同步到 SteamOS VMware 虚拟机，在 `Linux x86_64` / Python 3.13.5 环境内建立隔离构建环境并运行 `python tools/build_native_release.py --platform steamos`。
- 已生成并复制回工作区：`[SignRiver-DLC-Hub-v0.2.0-steamos-x64.tar.gz](../../.test-artifacts/steamos-dist/SignRiver-DLC-Hub-v0.2.0-steamos-x64.tar.gz)`（44,531,151 字节，SHA-256 `db26e35a01ca6358f9960de27e1ab56f2763d5c570ac187684f1a1da343fe352`）和 `[SignRiver-DLC-Hub-full-v0.2.0-steamos-x64.zip](../../.test-artifacts/steamos-dist/SignRiver-DLC-Hub-full-v0.2.0-steamos-x64.zip)`（44,749,426 字节，SHA-256 `14c410fa557cf0704f0e1104c7c052ab7006ab26d8e0d20d58b9305dd1286ec1`）。
- 已验证：tar.gz 可解包；ZIP `testzip` 通过；两个包均含 `app/state.json` 与完整 `app/versions/0.2.0/`；活动版本为 `0.2.0`；主程序为 ELF 64-bit x86-64（机器类型 62）。已在虚拟机中直接启动主程序观察 8 秒，进程保持运行至超时退出（退出码 124），未报告启动崩溃。
- 已执行定向测试：`tests/test_build_native_release.py`、`tests/test_cross_platform_runtime.py`、`tests/test_patch_platforms.py`、`tests/test_dlc_catalog.py`、`tests/test_cartridge_catalog.py`、`tests/test_platform_content.py`，全部通过。未执行真实 DLC 下载、补丁生命周期、Steam 登录、远端上传、线上清单切换、commit 或 push。
- 当前活动模块对齐方式：本次使用源码归档中的完整 `app/versions/0.2.0/` 进行正式 SteamOS 构建；未修改 `app/state.json`，用户运行该包前无需额外同步。SteamOS VM 保持运行，macOS VM 已挂起。
## 最新任务（SteamOS/macOS 平台专属指南与组件适配）

- 修改范围：`config/guides/{guides_index,guide_network_basics,guide_game_directory_missing,guide_disk_space,guide_patch_state,guide_update_module_basics}.json`、`docs/tool-item-ui-spec.md`、`app/versions/0.1.0/{app_entry.py,signriver_app/application/guides.py,signriver_app/infrastructure/diagnostics/support_bundle.py}`，以及对应 `0.2.0` 活动模块同步文件和定向测试。
- 指南目录新增平台文案能力：索引支持 `title_by_platform`/`summary_by_platform`，正文支持 `platform_text` 与块级 `platforms` 过滤。SteamOS/macOS 的补丁指南明确只接受原生 `.so`/`.dylib`，不再显示 `unlock.dll`、Windows Defender 或 Windows 专属替代方案；游戏目录、网络、磁盘空间和更新指南同步说明 Steam 库、兼容层、`.app` 和原生包差异。
- 补丁工具组件按当前平台显示“SteamOS 原生补丁”/“macOS 原生补丁”，下载提示使用真实补丁文件数量；日志资料收集组件按平台显示系统信息类型。资料收集器现在在 SteamOS 收集 `uname` 与 `/etc/os-release`，在 macOS 收集精简 `system_profiler` 信息，并为 Paradox 日志增加 macOS `Library/Application Support` 与 SteamOS `~/.local/share` 路径。
- 当前活动版本：`0.2.0`；采用“基线实现 + 定向同步到当前活动模块”，未修改 `app/state.json`。用户重启活动客户端后生效；本轮未重新构建或发布原生包。
- 已执行：`pytest -q tests/test_platform_content.py tests/test_support_bundle.py tests/test_support_collection_ui.py tests/test_ui_theme.py tests/test_diagnostics.py tests/test_dlc_catalog.py tests/test_cartridge_catalog.py tests/test_cross_platform_runtime.py`（全部通过）；Ruff、compileall、`git diff --check` 均通过。未执行 GUI 人工验收、云端资源上传、线上清单切换、commit 或 push。
## 最新任务（macOS 1.0.0 正式包与部署，2026-09-21）

- macOS VM 构建环境复检：`/Users/signriver/py312/python/bin/python3.12`（Python 3.12.14）+ PyInstaller 6.22.3 + customtkinter 5.2.2，Xcode CLT 提供 `codesign`/`install_name_tool`；构建目录 `/Users/signriver/macos-build-20260919`。
- 源码同步后执行 `tools/build_native_release.py --platform macos`（exit=0）。
- 产物（已回传 `.test-artifacts/macos-dist/`，与来宾 `shasum` 一致）：`SignRiver-DLC-Hub-v1.0.0-macos-x64.app.zip` 24,910,905 字节 SHA-256 `A1B036299ECC17EC59B2AEB7D8825A2201EDA32FB96A408A73EC8549DF9B5CAC`；`SignRiver-DLC-Hub-full-v1.0.0-macos-x64.zip` 24,925,924 字节 SHA-256 `439CE5C4790927CD32A0F3B897FAD19A99AFAF48DA66B8F4B51D9DB07A0D17E5`。
- 验证：两个 ZIP `unzip -t` 通过；主程序 `Mach-O 64-bit executable x86_64`（`lipo -info` 确认非 fat）；`codesign --verify --deep --strict` 通过；包内 `Contents/Resources/runtime/app/versions/1.0.0/module.json` = 1.0.0/api 3、`signriver_app` 80 文件、`app/state.json` = 1.0.0、`config/guides` 16 条索引（含 2 条 macOS 专属指南）。
- 部署：数据目录 `app/state.json` 备份为 `state.json.bak-before-100` 后切到 `active_version=1.0.0`；`open` 启动 1.0.0 `.app`，日志 `Starting application module 1.0.0`、`app/versions/1.0.0` 已播种，进程存活，供人工验收。
- 未完成：Windows 1.0.0 全量包与发布器清单（`tools/build_release.py` + `tools/prepare_update_release.py`）、模块归档与三端包的上传、0.2.0 → 1.0.0 真实更新 E2E、push。当前 SteamOS VM 已关闭（一次仅运行一台虚拟机）。

## 最新任务（SteamOS 部署 1.0.0 供验收，2026-09-21）

- 文档：`docs/agent/PROJECT_CONTEXT.md` 新增「模块版本目录、module.json 与 API 版本」一节，说明源码目录（0.1.0，唯一入库）／发行副本（未跟踪）／活动模块（`app/state.json`）的区别、`api_version ≤ HOST_API_VERSION` 的校验规则，以及"改代码改 0.1.0、发版复制新版本目录"的流程；提交 `5d90d7a`。
- SteamOS 虚拟机已部署 1.0.0 供人工验收：把 `SignRiver-DLC-Hub-v1.0.0-steamos-x64.tar.gz` 上传后在 `~/signriver-steamos-build/dist/` 解压；旧部署改名为 `SignRiver-DLC-Hub-steamos-x64.0.2.0-bak` 保留；数据目录 `app/state.json` 备份为 `state.json.bak-before-100` 后切到 `active_version=1.0.0`（previous 0.2.0、bad_versions 空）。
- 验证：客户端日志 `Starting application module 1.0.0`；数据目录自动播种 `app/versions/1.0.0`（83 文件）；包内模块 + 包内配置端到端解析成功（SteamOS 8 条指南、bootstrap 目录正确）；Stellaris 29 GB 完好。
- 未执行：0.2.0 → 1.0.0 自动更新 E2E（需要先上传模块归档与发布清单）、macOS/Windows 1.0.0 包、上传与 push。

## 最新任务（1.0.0 版本升级与 SteamOS 正式包，2026-09-21）

- 已提交此前遗留的未提交修复（`c465cba`：优先使用支持当前平台的卡带主表与原生补丁资源）。
- 版本升级（提交 `b3e3935`）：新建 `app/versions/1.0.0/`（源码取自 0.1.0 基线，`module.json` 改为 `version 1.0.0` + `api_version 3`，与 Host API 3 一致）；`app/state.json` → `active_version 1.0.0`、`previous_version 0.2.0`、`bad_versions` 为空；`src/signriver_launcher/constants.py` → `LAUNCHER_VERSION 1.0.0`；`publisher-workspace/update-notes.json` 新增 1.0.0 中文更新说明。
- 模块归档：`tools/build_module.py --all-versions app\versions` 生成 `dist/modules/SignRiver-DLC-Hub-module-v1.0.0.zip`（289,617 字节，SHA-256 `abe3f32f7a85696cf21ef8bf55a33a306eecfe9da1c740af1c003f58f472d9de`），`config/module-archives.json` 更新为最近 3 个版本（0.1.7 / 0.2.0 / 1.0.0）。注意：本地重建的 0.2.0 模块归档与登记值不一致（源码在 0.2.0 发布后有修复），**不要重新上传 0.2.0 模块归档**，除非同步更新登记。
- SteamOS 1.0.0 原生包（在 SteamOS VM 内构建，rc=0，已回传 `.test-artifacts/steamos-dist/`，双侧 sha256 一致）：`SignRiver-DLC-Hub-v1.0.0-steamos-x64.tar.gz` 44,804,617 字节 SHA-256 `FE2484B346AE49C84FD703252445294F47CD7B2497524DEB7EFF050F1B753C8A`；`SignRiver-DLC-Hub-full-v1.0.0-steamos-x64.zip` 45,060,428 字节 SHA-256 `04FDBCC05A599B2C25E96C4019256D4D6F70F4D63522672BC27131DFCBA109AD`。
- 包内校验：ELF 64-bit x86-64、755、`app/versions/1.0.0/signriver_app` 80 文件、`config/guides` 16 条索引、包内 `module.json` = 1.0.0/api 3、`app/state.json` = 1.0.0；tar 与 ZIP 完整性通过（595 项）。
- 全量 `pytest`、Ruff 通过；本轮提交全部为本地提交，未推送。
- 未完成（按用户要求，三个平台齐备后再推送）：macOS 1.0.0 原生包（需切换到 macOS VM，一次只能开一台虚拟机）、Windows 1.0.0 全量包与发布器清单（`tools/build_release.py` + `tools/prepare_update_release.py`）、模块归档与各平台包的上传、0.2.0 → 1.0.0 真实更新 E2E（含 `min_launcher_version` 冻结包验证）。

## 最新任务（SteamOS 重新构建并导入基线，2026-09-21）

- 起因：Steam 客户端因快照残留的"更新未落地"状态进入"下载→重启→再下载"循环，界面（Chromium 内核的 `steamwebhelper`，桌面显示为 `Chromium-browser`）每隔数秒抢焦点并留下崩溃转储；排查确认系统未安装任何独立浏览器，这是 Steam 自身行为。
- 处理：先用最新源码（含 DLC 批量提示修复）在虚拟机内原生重建 → 导出产物 → 回退到快照 `20260921-可用基线` → 再导入新包部署。
- 新产物（已回传 `.test-artifacts/steamos-dist/`，与来宾 `sha256sum` 一致）：`SignRiver-DLC-Hub-v0.2.0-steamos-x64.tar.gz` 44,548,109 字节 SHA-256 `F07902BF0814B780B18E5F673E5871710F00A12B1EE01E4496246D1D7A7BD936`；`SignRiver-DLC-Hub-full-v0.2.0-steamos-x64.zip` 44,765,083 字节 SHA-256 `25B790A71319714673987845938F4E7ED1817B306974CDD932832A4DFEF578CF`。
- 部署：包解压到 `~/signriver-steamos-build/dist/SignRiver-DLC-Hub-steamos-x64`；旧的数据目录模块改名 `0.2.0.bak-before-import` 后由启动器重新播种（83 文件，含 `_notify_batch_install_completion`）；客户端经 `systemd-run --user` 启动正常，SteamOS 侧 8 条指南全部解析通过；Stellaris 28 GB 仍在客户端目录之外。
- 仍待处理：该基线的 Steam 客户端依旧是"更新已下载未落地"状态，直接启动 Steam 会再次进入循环（游戏数据安全）。需要时用 `~/signriver-steamos-build/../.local/share/Steam/steam.sh -steamdeck`（不加 `-skipinitialbootstrap`）启动一次完成更新，之后建议重拍基线快照。

## 最新任务（DLC 批量下载只提示一次，2026-09-21）

- 问题：一键解锁/批量下载时，每个 DLC 安装完成都会弹一次「下载并安装成功！…」提示条（用户反馈每下载一个就弹一次），而流程末尾本来就有一次「一键解锁成功」对话框。
- 修改：`app/versions/0.1.0/app_entry.py` 的 `_on_auto_install_success()` 不再逐个 `_notify`，改为置位 `batch_install_success_pending`；新增 `_notify_batch_install_completion()`，仅在 `_on_auto_install_worker_done()` 判定 `not self._content_work_is_active()`（下载与安装全部结束）时提示一次，且 `unlock_workflow_active` 为真时跳过（由解锁完成对话框负责告知）。`_start_dlc_batch()` 开始时清零该标志。同一改动已同步到活动模块 `0.2.0`。
- 测试：`tests/test_ui_theme.py` 新增 `test_dlc_batch_reports_one_completion_notice_per_batch`；全量 `pytest -q`、Ruff、compileall、`git diff --check` 通过。
- SteamOS VM：已把更新后的 `app_entry.py` 同步到数据目录模块、包内运行时与构建源码三处并重启客户端，`signriver-check.service` active、日志 `Starting application module 0.2.0` 正常。
- 未执行：Windows 发布包重建、macOS 端同步、上传、推送。

## SteamOS 干净基线快照（2026-09-21）

- 已创建关机状态快照 `20260921-可用基线`（无内存文件，确认是 poweroff 后拍摄）。当前快照链：`steamos-installed-plasma-x11` → `下载stellaris` → `20260921-可用基线`。
- 制作过程：停掉 Steam 与客户端程序 → 写入游戏库登记（`~/.local/share/Steam/{steamapps,config}/libraryfolders.vdf`）→ `systemctl poweroff` → `vmrun snapshot`。首次拍摄误在关机过程中进行（带了 8 GB 内存文件），已删除并重拍；期间遇到残留 `.vmx.lck`（持有者 PID 已不存在），将其改名释放后快照成功。
- 基线内容：Stellaris 28 GB（`~/Games/SteamLibrary/steamapps/common/Stellaris`，3 个 appmanifest，`StateFlags=4`）；客户端发布包已部署（`~/signriver-steamos-build`）且 `~/.local/share/signriver-dlc-hub` 数据目录正常；`~/register-steam-library.sh` 与 `~/Games/SteamLibrary/libraryfolders.vdf.backup` 用于重新登记游戏库。
- 已知情况：该基线的 Steam 客户端仍处于"已下载但未落地"的历史状态（`package/*.installed` 缺失）。首次启动 Steam 时它会自动补装客户端（约 496 MB，2–3 分钟）；**补装会重建 `~/.local/share/Steam`，但不会再删除游戏**（游戏已在 Steam 根目录之外）。补装并登录后若库里未显示 Stellaris，执行 `~/register-steam-library.sh` 再重启 Steam，或在 设置 → 存储空间 → 添加驱动器 中选择 `/home/deck/Games/SteamLibrary`（不会重新下载）。
- 经验：SteamOS 正常启动参数带 `-skipinitialbootstrap`；在客户端有未应用更新时用该参数启动会导致"下载→不安装→下次再下载"的循环，此时用 `steam.sh -steamdeck`（不带该参数）可让更新真正落地。

## 游戏库迁移与三项恢复（SteamOS，2026-09-21）

- 二次事故：用户尝试打开 Steam 时，Steam 再次自我重装客户端并清空 `~/.local/share/Steam`，游戏库第二次被删（已由快照恢复）。定位到快照 `下载stellaris` 是在 **Steam 客户端更新途中**拍的（`package/` 只有 `beta`，没有 `*.installed`），因此该快照下每次启动 Steam 都会触发一次完整客户端重装。
- 已完成迁移（游戏库移出 Steam 根目录）：`~/.local/share/Steam/steamapps/{common,downloading,appmanifest_*.acf}` → `~/Games/SteamLibrary/steamapps/`；并在 `steamapps/libraryfolders.vdf` 与 `config/libraryfolders.vdf` 两个位置登记第二个库（`/home/deck/Games/SteamLibrary`）。之后 Steam 再重装客户端只会重建客户端，不会再删除游戏。
- 当前状态：Stellaris 28 GB 位于 `/home/deck/Games/SteamLibrary/steamapps/common/Stellaris`（`appmanifest_281990.acf` 状态 `StateFlags=4`）；Steam 客户端已更新完成并显示登录窗口（客户端重装导致登录状态丢失，需重新登录一次）；`dolphin` 已打开该目录；我们的客户端已重新部署并运行（`signriver-check.service` active，模块 `0.2.0`）。
- 注意事项：不要在 Steam 运行时改动来宾系统时钟（历史事故触发条件之一）；本 VM 的快照仍保留一份未完成客户端安装的状态，若回退到该快照会再次触发客户端重装（对已迁移的游戏库无害）。

## 事故与恢复（SteamOS 快照回退，2026-09-21）

- 事故：本机对 SteamOS VM 执行时钟校正（`systemctl restart systemd-timesyncd`）时时钟一次性前跳 18 小时 33 分；11 秒后 Steam 启动脚本判定客户端异常，执行 `rm -rf ~/.local/share/Steam` 自我重装，而 SteamOS 默认游戏库 `steamapps/` 位于该目录内，导致约 29 GB 游戏数据（含 Stellaris）被删除。证据：`journalctl -b -1` 中 `14:14:58 Initial clock synchronization` 紧随 `14:15:09 steam[...]: rm: cannot remove '/home/deck/.local/share/Steam': Directory not empty` 与 `app-steam@*.service ... status=1/FAILURE`。用户重启发生在 14:24，晚于删除，不是原因。
- 恢复：将 VM 回退到快照 `下载stellaris`（磁盘 `steamos-target-128gb-000001.vmdk`，31.4 GB），Steam 客户端与 Stellaris（32 GB 库）恢复；回退同时丢弃了当天的虚拟机部署，已按下方重新完成。
- 教训：**不要在任何 Steam 客户端可能运行/被启动的时刻改动来宾系统时钟**；正确做法是确保 Steam 完全停止后再校正时间，并把游戏库放在 `~/.local/share/Steam` 之外，避免客户端自我重装时连带删除游戏。
- 我方引入的第二个缺陷：源码归档排除规则曾按“路径任意一层名为 cache 即排除”，误删模块内的 `signriver_app/infrastructure/cache` 包，导致 SteamOS 部署后 `ModuleNotFoundError: _signriver_app_0_2_0.signriver_app.infrastructure.cache`。已改为仅排除仓库顶层运行目录（`data`、`cache`、`build`、`dist` 等），并核对模块文件数与仓库一致（80/80）。

## 最新任务（SteamOS 快照回退后重新交付，2026-09-21）

- 重新生成 5,215,935 字节源码归档并覆盖解压到 `~/signriver-steamos-build`，重建 `.venv-steamos`（Python 3.13.5 + PyInstaller 6.22.3），执行 `tools/build_native_release.py --platform steamos`（rc=0）。
- 包内校验：ELF 64-bit x86-64、755、`app/versions/0.2.0/signriver_app` 80 文件、`config/guides` 19 项 / 16 条索引（含 `patch_assets_missing`、`steamos-app-permission`、`steamos-proton-native`）；`tar -tzf` 与 ZIP 校验通过（500 项，testzip 为空）。
- 部署：清掉用坏包播种的 `~/.local/share/signriver-dlc-hub/app/versions/0.2.0` 后重新播种（83 文件），客户端经 `systemd-run --user` 启动并保持运行，日志 `Starting application module 0.2.0` 无错误。
- 端到端：包内模块 + 包内配置解析到 `dist/.../config/guides`，SteamOS 侧 8 条指南全部加载成功。
- 新产物（已回传 `.test-artifacts/steamos-dist/`，与来宾 `sha256sum` 一致）：`SignRiver-DLC-Hub-v0.2.0-steamos-x64.tar.gz` 44,547,181 字节 SHA-256 `A494C9679B71F0FEEFC3C66C781DE4588EDDB109FE27DFCC957481EC51DEB2B7`；`SignRiver-DLC-Hub-full-v0.2.0-steamos-x64.zip` 44,763,958 字节 SHA-256 `3B77CEC4F11B97111D5C2B22CE9BC562C9D5F2820F132C75A4C68019CFAFA4D5`。
- 时钟：已在 Steam 停止状态下重新校正为 `Asia/Shanghai` 并启用 NTP，与宿主机一致。
- 未完成/待办：游戏库仍在 `~/.local/share/Steam` 内，存在再次被客户端自我重装删除的风险，建议迁移到独立库目录（待用户确认后执行）。未执行上传、清单切换、发布器批次、Steam 登录、真实 DLC 下载、push。

## 最新任务（SteamOS 原生重建与部署，2026-09-21）

- 在 SteamOS VM（`deck@192.168.233.130`）完成与 macOS 等价的交付：备份 → 源码同步 → 原生重建 → 覆盖部署 → 数据目录模块重新播种 → 启动验证 → 产物回传。
- 备份（回滚用）：`~/.local/share/signriver-dlc-hub/app/versions/0.2.0.bak-20260921`、`~/.local/share/signriver-dlc-hub/app/state.json.bak-20260921`、`~/signriver-steamos-build/dist/SignRiver-DLC-Hub-steamos-x64.bak-20260921`，以及旧 `*.tar.gz.bak-20260921`、`*.zip.bak-20260921`。
- 源码归档：5,202,470 字节 / 722 文件，排除 `.git`、`.venv`、`build`、`dist`、`data`、`cache`、`.test-artifacts`、`publisher-workspace`、缓存与凭据，但保留被 Git 忽略的 `app/versions/0.2.0`；SFTP 上传后覆盖解压到 `~/signriver-steamos-build`，`.venv-steamos`、`build`、`dist` 均保留。
- 构建：`.venv-steamos/bin/python tools/build_native_release.py --platform steamos`（rc=0）。包内校验：ELF 64-bit x86-64、权限 755、`app/versions/0.2.0/signriver_app` 80 个文件、`config/guides` 19 项 / 16 条索引（含 `patch_assets_missing`、`steamos-app-permission`、`steamos-proton-native`）；`tar -tzf` 与 ZIP 完整性通过（512 项，testzip 为空）。
- 部署：删除数据目录旧模块以触发 `paths.ensure()` 重新播种；播种后模块含新代码标记（`resolve_bootstrap_dir`=2、`platform_text`=1），共 83 个文件；数据目录 `state.json` 保持 `active_version=0.2.0`、`bad_versions` 为空。
- 启动验证：`DISPLAY=:0` 启动后进程存活（PID 17899/17901），日志出现 `Starting application module 0.2.0`，无模块加载或指南加载错误；窗口保持打开供用户查看。
- 端到端证明：用包内模块加载包内配置运行 `resolve_bootstrap_dir` + `GuideCatalogService(platform="steamos")`，解析到包内 `config/guides`，SteamOS 侧 8 条指南全部加载且正文为 SteamOS 专属文案。
- 新产物（已回传 `.test-artifacts/steamos-dist/`，与来宾 `sha256sum` 完全一致）：`SignRiver-DLC-Hub-v0.2.0-steamos-x64.tar.gz` 44,547,367 字节 SHA-256 `6BEF73F1BA663D706210D6D4AB0CDD9A7910A135E65F0254C40A8FE96E466A64`；`SignRiver-DLC-Hub-full-v0.2.0-steamos-x64.zip` 44,763,988 字节 SHA-256 `CEB0E75AB1FF82B39E39D637CBED69999A49382ED101355611864DA7CAC14E96`。
- 本轮未改任何仓库代码（未发现 SteamOS 专属缺陷）。SteamOS VM 时钟已于 2026-09-21 校正：该机未装 open-vm-tools，虚拟机挂起/恢复后 `systemd-timesyncd` 未重新同步，导致时钟落后宿主机 18 小时 33 分；执行 `sudo systemctl restart systemd-timesyncd` 后立即通过 NTP 校正，并把时区统一为 `Asia/Shanghai`、回写 RTC，现与宿主机一致（差异 ≤1 秒）。若再次挂起后出现时间偏差，同样用该命令修复。
- 未执行：上传发布包、线上清单切换、发布器批次、Steam 登录、真实 DLC 下载、补丁生命周期、push。

## 最新任务（清理日志收集的用户可见“跳过/忽略”措辞，2026-09-21）

- 背景：日志资料收集完成弹窗原样显示内部候选路径统计（“已整理 4 个文件；跳过 27 项；失败 0 项”），用户无法得知含义且容易误解为异常。内部 `skipped`/`skipped_dumps` 字段保留，仅调整用户可见文案。
- 修改：`SupportCollectionResult.summary` 改为“已整理 N 个文件。”；收集工具默认提示去掉“未找到的文件会安全跳过”；崩溃转储提示改为“另有 N 个崩溃转储（.dmp）体积较大，未一并打包”；一键排错中不可捕获输出的工具改为“未运行（…）”；一键解锁进度文案改为“已有 N 项无需重新下载”。基线与活动模块 `0.2.0` 同步。
- 契约：`docs/tool-item-ui-spec.md` 明确“跳过/忽略”计数不得出现在用户可见文案，只用于内部与诊断明细。
- 测试：`tests/test_support_bundle.py` 新增 summary 不含跳过/忽略/失败的用例，`tests/test_support_collection_ui.py` 新增客户端措辞回归用例；全量 `pytest -q`、Ruff、compileall、`git diff --check` 通过。
- macOS VM：模块文件已同步到用户目录模块副本、`.app` 内置运行时和隔离源码目录，重新临时签名并验证通过，应用已重启（22:47 启动）供用户查看。
- 未执行：完整 macOS/SteamOS 原生重新构建、真实 DLC 下载、补丁生命周期、上传、线上清单切换、push。

## 最新任务（修复 SteamOS/macOS 指南列表为空，2026-09-21）

- 根因：客户端固定从 `paths.root/config/guides` 读取指南，但启动器 `_seed_packaged_runtime()` 从不把 `config/guides` 复制到可写根目录；Windows 上 `root` 即安装目录所以正常，macOS/SteamOS 上 `root` 是用户数据目录，导致「解决方案」列表整页为空且不报错。macOS 日志中留有 2026-09-19 的“未找到对应教程”记录作为旁证。
- 修改：`signriver_app/application/guides.py` 新增 `resolve_bootstrap_dir()`，按候选目录中是否真实存在 `guides_index.json` 选择指南根；`app_entry.py` 新增 `_guide_bootstrap_candidates()`，候选顺序为 `paths.install/config/guides`、`paths.install/Contents/Resources/runtime/config/guides`、`paths.root/config/guides`。基线与活动模块 `0.2.0` 同步实现。
- 测试：`tests/test_platform_content.py` 新增 `resolve_bootstrap_dir` 选择规则用例与客户端装配断言；全量 `pytest -q`、Ruff、compileall、`git diff --check` 通过。
- macOS VM：模块三件（`app_entry.py`、`application/guides.py`、`application/__init__.py`）已同步到用户目录模块副本、`.app` 内置运行时模块和隔离源码目录，并重新临时签名且通过 `codesign --verify --deep --strict`；`open` 启动后进程存活，新进程日志无指南加载错误。用户在虚拟机上直接查看「解决方案」列表即可确认。
- 未执行：完整 macOS/SteamOS 原生重新构建、真实 DLC 下载、补丁生命周期、上传、线上清单切换、push。

## 最新任务（补丁资源缺失与原生平台专项解决方案，2026-09-21）

- 根因一：客户端多处引用指南 id `patch_assets_missing`（主界面“补丁资源缺失，暂无法一键解锁”提示的跳转目标），但 `guides_index.json` 中从未存在该指南，点击后只会提示“未找到对应教程”。现已新增 `config/guides/guide_patch_assets_missing.json` 与索引项（`platforms: ["all"]`），并用 `platform_text` 分别说明 Windows 资源、SteamOS 原生 `.so`、macOS 原生 `.dylib`，明确禁止把 Windows `.dll` 改名混用。
- 根因二：macOS 客户端从 `~/Library/Application Support/SignRiver DLC Hub/app/versions/0.2.0/` 加载模块，而此前只更新了 `.app/Contents/Resources/runtime/`，用户目录模块副本仍是旧代码，因此日志收集卡片继续显示“Windows DxDiag.txt”，且旧 `guides.py` 不认识 `platform_text`，平台化指南正文被整体丢弃。现已把最新模块文件同步到用户目录模块副本。
- 新增平台专项指南：`macos-app-blocked`（Gatekeeper 拦截与“已损坏”）、`macos-game-not-unlocked`（补丁后仍未解锁）、`steamos-app-permission`（可执行权限与桌面模式）、`steamos-proton-native`（通过 Proton 运行时原生补丁不生效）。
- 契约同步：`docs/tool-item-ui-spec.md` 增加“补丁资源缺失与原生平台专项指南”一节，并明确任何 `_open_solution_article(<id>)` 引用都必须同时提供同 id 的索引项和详情文件。
- 验证：`tests/test_platform_content.py` 新增“客户端引用的指南 id 必须存在”和平台专项指南覆盖用例，全量 `pytest -q` 通过；Ruff、`git diff --check` 通过。
- macOS VM：新指南已同步到 `/Users/signriver/macos-build-20260919/config/guides`、`.app/Contents/Resources/runtime/config/guides`，并重新临时签名且通过 `codesign --verify --deep --strict`；用户目录模块副本已更新（`app_entry.py`/`guides.py` 新代码标记已核对）。需完全退出后重新打开客户端才会生效。
- 未执行：完整 macOS/SteamOS 原生重新构建、真实 DLC 下载、补丁生命周期、上传、线上清单切换、push。

## 最新操作（macOS VM 同步最新活动模块，2026-09-21）

- macOS VM `D:\\vmware\\macos-vm\\macOS Sequoia.vmx` 已通过 VMware Tools 受控通道同步当前活动模块 `0.2.0` 的最新 `app_entry.py`、指南/诊断/卡带目录/DLC 目录模块，以及 `config/guides/` 平台指南文件。
- 同步目标包括隔离源码目录 `/Users/signriver/macos-build-20260919/` 和现有测试包 `/Users/signriver/macos-build-20260919/dist/SignRiver-DLC-Hub.app/Contents/Resources/runtime/`；未覆盖用户 `~/Applications` 安装目录或用户数据目录。
- 修改 `.app` 内运行时后已在来宾内使用临时签名重新签署，并通过 `codesign --verify --deep --strict`；未启动客户端，等待用户在 Finder 手动双击查看。
- 手动打开路径：`/Users/signriver/macos-build-20260919/dist/SignRiver-DLC-Hub.app`。本次未重新执行完整 macOS 原生构建、未上传、未切换线上清单、未 commit 或 push。
