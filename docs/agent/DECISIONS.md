# SignRiver DLC Hub 决策记录

> 这里只记录仍影响后续设计的长期约束；逐次操作和旧决策原文见 [`archive/DECISIONS-2026-09-04-history.md`](archive/DECISIONS-2026-09-04-history.md)。

## 发布与更新

### 强制更新必须在启动时自动检测并锁住界面（2026-09-21）

- `mandatory` 只表示“检测到后不能跳过”，它不会触发检测；检测必须由启动流程无条件发起。客户端原先把它挂在 `check_on_startup` 上，而该配置自模块化架构引入起一直是 `false`，导致强制更新实际上永远不会自动弹出（用户只能手动检查）。
- 现在：配置了更新清单时启动即检查（含 15s/45s 静默重试，失败只写日志不打扰用户）；检测到 `mandatory` 更新后先提示、随后禁用主窗口（`-disabled`，不支持的平台退化为不提供跳过入口）并禁用“取消下载”，安装完成后自动退出重启；下载/安装失败会解锁并提示，下次启动仍会强制检测（避免网络故障把用户彻底锁死）。
- `check_on_startup` 不再参与判断，仅保留在配置结构中以兼容旧文件。

### 卡带 config_format 只能使用老客户端认识的值（2026-09-21）

- 老客户端（0.2.0 及更早）解析卡带时会校验**文档里所有平台段**，遇到不认识的值直接判定卡带解析失败，DLC 目录整个读不出来（现象：`unsupported patch config format: 'none'`，且与当前操作系统无关）。
- 因此新增平台行为**不能**靠扩宽 `config_format` 取值实现：macOS 的“不生成配置文件”改为客户端内部规则（`PatchProfile` 对 `PatchPlatform.MACOS` 归一为 `NONE`），卡带里 macOS 段继续写 `cream_ini`。
- 守卫：`tests/test_platform_content.py::test_all_cartridges_keep_legacy_config_formats` 限定所有平台段只能出现 `cream_ini` / `smokeapi_json`；`tests/test_patch_engine.py::test_macos_profile_always_drops_config_file` 保证客户端内部归一化。改动卡带后必须同步 `cartridges_index.json` 的哈希与大小，并重新发布云端卡带。

### 自解压包必须把发布文件夹整包写入（2026-09-21）

- 7-Zip SFX 会把 payload 内容解压到用户选择的目录。打包时只能用 `7z a <archive> <发布目录名>`（连目录本身），**不能**用 `.\<发布目录>\*`——后者只打目录内容，用户在盘根目录解压会把 `app/`、EXE 等直接铺满整个盘（曾污染 D 盘）。
- 判定与回归：`tests/test_release_build.py::test_sfx_payload_keeps_the_release_folder` 用 `7z l -slt -sccUTF-8` 断言 payload 内每个条目都以发布目录名开头；`-sccUTF-8` 用于避免中文目录名按控制台代码页输出变成乱码。
- 现状：本机 `C:\Program Files\7-Zip` 只有标准 `7z.sfx`；它的 `ExtractTitle`/`GUIFlags`/`OverwriteMode` 等键属于 7zSD 变体，会被忽略（保留无害）。标准模块生成的 SFX 启动时会要求管理员权限（既有行为），Python 兜底 SFX（`tools/sfx_stub.py`）本来就解压到 `<exe 目录>\<发布目录名>`。
- 默认后端是 **Bandizip SFX**（`bz c -l:9 -y -sfx:<Bandizip 目录>/bdzsfx.x86.sfx <输出.exe> <发布目录>`）：产物只有 ZIP + 约 34 KB stub，stub 以 `asInvoker` 运行（不弹 UAC），解压到 `<当前目录>\<发布目录>`——双击时当前目录就是 EXE 所在目录，所以结果仍是单一文件夹。`_find_bandizip()` 通过 PATH 与注册表安装位置定位 `bz.exe`。
- 退路：Bandizip 不可用时用 7-Zip SFX（同样只带发布文件夹，但启动需要管理员权限），最后才是 Python 外壳版（`_build_python_sfx` + `tools/sfx_stub.py`：双击自动解压 + 提示 + 打开文件夹，落地同样是一个文件夹，但外壳本身约 11.9 MB，用户明确反对为体积换这点便利）。
- 注意：Bandizip SFX 的解压目标是**进程当前目录**，从命令行在别的目录启动会解压到那个目录；因为有顶层发布文件夹，最坏也只是多出一个文件夹，不会铺满整个盘。

### 全量更新必须绑定同一构建产物（2026-09-04）

- ZIP、`update-manifest.json`、发布器准备记录和 GitLink/GitHub 附件必须来自同一次构建。
- 上传前后重新核对大小和 SHA-256，并从两个源回读确认一致；同版本但元数据不同即视为不同构建，停止发布并重新生成整套产物。
- 宿主 API 或冻结启动器变化时，`min_launcher_version` 只能填写已通过冻结包 E2E 的最低版本；验证必须覆盖更新、重启、状态保留、目标版本启动和失败回滚。

### 游戏内容按源站完成附件与主表闭环（2026-09-05）

- 游戏内容发布不能先对所有源站批量替换附件，再统一切换各源站的 `catalog.json`；后续源站失败会让前一源站暴露“新附件 + 旧主表”。
- 发布器现在按源站依次完成：附件上传、远端多余文件处理、主表切换；只有一个源站闭环完成后才进入下一个源站。
- 阶段安全检查点保存已切换源站，恢复时跳过已完成源站的主表重复切换；因此双源失败可从失败源站继续，已完成源站保持幂等。

### 版本化模块与活动版本（2026-08-23）

- `app/versions/0.1.0/` 是 Git 跟踪的模块源码基线；实际运行版本由 `app/state.json` 的 `active_version` 决定。
- 客户端改动必须明确选择：仅基线、定向同步活动模块，或正式构建并切换；禁止整目录覆盖活动模块。

### 发布资产与多平台（2026-08-16～2026-08-21）

- 发布资产必须先上传并核验，再由用户决定是否推送代码。
- SteamOS/macOS 包必须在目标平台原生构建；更新清单按平台精确选择包，不能跨平台回退。
- 发布目录是内容入队唯一凭据；构建快照只用于诊断和一致性核验。

## 客户端安全与兼容

### macOS 补丁只换库、不生成配置（2026-09-21）

- macOS 使用替换型解锁库（Goldberg/GSE）：程序只把原库改名为 `libsteam_api_o.dylib` 作为恢复凭据，再把解锁库写成 `libsteam_api.dylib`；还原时用备份覆盖主库并删除 `_o` 与遗留配置。默认全部解锁，游戏本身只会加载已下载的 DLC。
- 平台契约用 `config_format: "none"` 表达“不使用配置文件”。该模式安装时不写配置，并事务性清理历史遗留的同名配置文件；安装凭据里的 `ini_sha256` 记为空串，审计把残留配置视为需要修复。
- 不再为 macOS 生成 `icecream.ini`；发布器与卡带声明必须与客户端一致，卡带文档改动后同步 `cartridges_index.json` 的哈希与大小。

### macOS 解锁库必须做符号差集校验（2026-09-21）

- macOS 上替换 `libsteam_api.dylib` 的解锁库必须导出目标游戏所需的全部 flat API 符号：dyld 在加载期解析两级命名空间绑定，缺一个符号整库加载失败，表现为白屏或直接退出，Python 层无法捕获。
- 发布前必须做差集校验：游戏二进制用 `nm -u -arch x86_64` 得到需求集合，候选库用 `nm -gU -arch x86_64` 得到导出集合，差集非空即阻止上传；同时确认架构包含 x86_64。
- IceCream（`krnya/icecream` `0c8f746`）只导出 17 个符号，缺少 `SteamAPI_InitSafe`、`SteamAPI_RestartAppIfNecessary`，只适用于少数游戏；Goldberg/GSE 系构建（实测 1,188 个符号）覆盖完整 flat API，是 macOS 的默认选择。
- 替换型模拟器（Goldberg/GSE）读取库旁边的 `steam_settings/DLC.txt`（每行 `appid=名称`）与 `steam_settings/steam_appid.txt`；不需要原版代理，但客户端仍应保留 `libsteam_api_o.dylib` 作为恢复凭据。

### macOS 补丁目录必须按主程序的加载路径确定（2026-09-21）

- 实测：`otool -L Stellaris/stellaris.app/Contents/MacOS/stellaris` 得到 `@executable_path/../../../libsteam_api.dylib`。`@executable_path` 是 `stellaris.app/Contents/MacOS`，向上三级回到**游戏根目录**，所以 Stellaris macOS 真正加载的是根目录那份库（670,560 字节）；包内 `Contents/MacOS/libsteam_api.dylib`（5,195,264 字节）只是随包副本。
- 结论：macOS 卡带的 `install_relative_dir` 必须写成主程序实际解析到的那一级（Stellaris 为 `.`），不能因为“包内也有同名库”就假定补丁位置——写错会得到“补丁显示正常、游戏实际没生效”的假象。
- 判定方法：对主程序执行 `otool -L <主程序> | grep -i steam`，按 `@executable_path` 展开真实路径后再定目录。
- 平台资产必须是目标平台的二进制：Stellaris 的 macOS “原版”资产曾经就是 Windows CreamAPI 的 `steam_api64.dll`（两者都是 5,195,264 字节、SHA-256 `0ff4a7c9…`），而发布器与客户端都不校验原版资产的格式，结果把一个 PE 文件写进了 macOS 游戏目录。发布 macOS 资产前必须核对文件类型（Mach-O / universal）与 SHA-256，不能只看大小。
- 已由用户确认：钢铁雄心 IV、文明 6、边缘世界不在 macOS 支持范围内；它们卡带里的 `patch.platforms.macos` 只是占位，不得据此发布。

### tkinter 终结器只能在主线程调用 Tcl（2026-09-21）

- macOS 自带 Tk 未开启线程支持，任何非主线程的 Tcl 调用都可能以 `EXC_BAD_ACCESS` 直接终止进程，无法用 Python 异常捕获。
- `tkinter.font.Font`、`tkinter.Variable`、`tkinter.Image` 的 `__del__` 会释放 Tcl 资源。后台线程触发分代回收时这些终结器就在错误线程上执行，因此客户端启动时必须调用 `signriver_app/infrastructure/tk_thread_safety.py` 的 `install()`，并由 UI 事件泵定期 `flush_pending()`。
- 后台线程仍然禁止直接操作控件；新增后台任务必须继续通过 `_post_ui` 回主线程。
- 判定方法：崩溃报告 `faultingThread` 非 0，且堆栈同时出现 `Tcl_EvalObjv` / `Tkapp_Call` 与 `gc_collect_main` / `slot_tp_finalize`，即属此类问题。

### 原生平台补丁资源由发布器显式物化（2026-09-21）

- `patch_platforms` 只描述客户端应读取的平台库名；只把 `libsteam_api.so` / `libsteam_api.dylib` 放进 `patches/` 不会自动变成 Release 附件。
- `published_platform_resources[platform].patch = true` 是发布承诺。发布器必须按卡带声明的 `unlocker_dll_name` 和 `runtime_original_library_name` 物化原文件名到输出目录，写入 `catalog.json`，并在任一文件缺失时阻止构建。
- 未明确标记为已发布的平台不得因本地目录存在原生文件而自动声明可用，避免客户端看到不完整的发布状态。


### 工具、指南和诊断（2026-08-23～2026-08-25）

- 指南与工具按独立索引和发布源维护；客户端只下载附件，不自动执行未知脚本或命令。
- 一键排错只执行显式声明的只读检查；修复动作必须用户确认且使用受控白名单。
- 内置指南不得因云端缺失阻断启动；平台和游戏适用范围必须可验证。

### 指南资源的跨平台解析（2026-09-21）

- 启动器 `RuntimePaths._seed_packaged_runtime()` 只把 `app/state.json`、`config/update.json`、`config/defaults`、`config/cartridges`、`config/announcement.json` 和应用图标复制到可写根目录，**不复制 `config/guides`**。
- 可写根目录在 Windows 上是安装目录（两者重合），但在 macOS 是 `~/Library/Application Support/SignRiver DLC Hub`、SteamOS 是 `~/.local/share/signriver-dlc-hub`。因此客户端不能写死 `paths.root/config/guides`，否则 SteamOS/macOS 的「解决方案」列表会整体为空，而且不产生任何报错。
- 采用方案：`resolve_bootstrap_dir()` 按“候选目录里是否真的存在 `guides_index.json`”选择指南根，候选顺序为 `paths.install/config/guides`、`paths.install/Contents/Resources/runtime/config/guides`、`paths.root/config/guides`。`paths.install` 由宿主传入 `RuntimePaths.resources_root`，已对 macOS 做 `.app` 内运行时归一化。
- 结论：模块读取任何随包发布的只读配置时，都要容忍宿主可写目录缺少该资源；不要假设 seed 列表会覆盖全部 `config` 内容。

### UI 与生命周期（2026-08-25～2026-08-26）

- 页面切换保持单次绘制提交；异步加载先显示稳定加载态。
- 关闭窗口遵循隐藏外壳、叶子到根销毁、退出事件循环、最后销毁根窗口的顺序。
- 活动模块、发布器和跨平台行为的结论必须以对应实际运行对象和定向测试为准。

### P 社启动器目录识别（2026-09-13）

- P 社自动更新会遗留只有 `.cpatch` 的版本命名目录，不能因目录名匹配就当成可修复的安装。
- 候选目录必须同时具备 `Paradox Launcher.exe`、`resources/app.asar` 与目标 `steam_api64.dll`；完整候选按目录名中的全部数字版本段排序，禁止字符串倒序比较。

### 补丁与内容兼容（2026-08-20～2026-08-24）

- 补丁安装前后都校验来源、大小和 SHA-256；异常时恢复原文件。
- 已发布字段改名必须保留旧模块兼容别名；平台可用性以云端资源状态为准，不由本地声明推断。
