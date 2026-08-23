# 当前任务交接

> 最后更新：2026-08-23（Asia/Shanghai）
> 分支：`main`
> Git：本轮已修复卡带文档与已发布模块的字段兼容性；完成验证后应仅提交卡带配置、回归测试与交接文档，`app/state.json` 是运行时恢复状态，不应随本轮提交。
> 工作区：启动器曾因 0.2.0 与 0.1.7 初始化失败自动回退至 0.1.6。现已恢复活动模块为 `0.2.0`、清空 `bad_versions`，并已从源码启动验证（PID 87104）；该状态恢复后与 Git 基线一致。

## 2026-08-23：卡带字段向后兼容与启动恢复

- 根因：卡带 JSON 已使用新字段 `patch.runtime_original_library_name`，但已发布的模块 `0.1.6` 与 `0.1.7` 仍强制要求旧字段 `patch.original_backup_dll_name`。启动器回退到旧模块时，缓存和内置卡带均被拒绝，最终报“没有可用的游戏卡带”。
- 已在全部 10 个内置 `config/cartridges/cartridge_*.json` 中保留旧字段，并令其值与新字段相同；同步重算 `config/cartridges/cartridges_index.json` 的 SHA-256 与字节数。新模块继续读取新字段，旧模块可读取兼容字段，避免配置演进破坏回退模块。
- `tests/test_cartridge_catalog.py` 增加回归断言，强制两种字段在每个内置卡带中保持一致，防止今后导出时再次遗漏旧字段。
- 实际活动版本为 `0.2.0`。对齐方式：直接恢复启动器保护性回退前的 Git 基线状态（`active_version=0.2.0`、`previous_version=0.1.7`、空 `bad_versions`），而非修改版本模块目录；同时验证 0.1.6 卡带服务仍可回退到内置卡带，及 0.2.0 可从源码启动。当前客户端已启动，用户无需额外重启；若已关闭，可正常重新运行 `launcher.py`。
- 验证（2026-08-23）：` .\.venv\Scripts\python.exe -m pytest -q tests/test_cartridge_catalog.py tests/test_cartridge_default_fallback.py tests/test_platform_content.py`（23 通过）；` .\.venv\Scripts\python.exe -m ruff check tests/test_cartridge_catalog.py` 通过；` .\.venv\Scripts\python.exe -m compileall -q app/versions/0.1.0 src tests` 通过；以 0.1.6 模块直接离线加载卡带通过；`launcher.py` 以恢复后的活动模块 0.2.0 启动后 4 秒进程仍在运行（PID 87104）；`git diff --check` 通过。未构建、未上传、未推送。
# 当前任务交接

> 最后更新：2026-08-23（Asia/Shanghai）
> 分支：`main`
> Git：任务结束时已创建本地提交 `feat: publish troubleshooting guide resources with hub`；未推送。
> 工作区：本任务文件已随本地提交保存；未重置或覆盖其他文件，未读取或修改发布凭据，未执行真实上传或远端写入。

## 2026-08-23：活动模块对齐规则与指南缓存容错修复

- 已将“客户端基线与活动模块对齐”升级为根目录 `AGENTS.md` 的永久规则，并同步写入 `docs/agent/DECISIONS.md`：任何 AI 在改客户端或宣称当前 GUI 生效前，必须动态读取 `app/state.json` 的 `active_version`、确认对应模块目录；然后明确选择仅基线实现、只定向同步本任务变更到活动模块，或走正式发布构建/切换。规则严禁写死 `0.1.0`、`0.2.0` 或其他版本号，严禁整目录覆盖活动模块，严禁擅自改动状态文件；交接必须记录对齐方式、实际验证对象和是否需重启。
- 已修复报错指南的可选缓存容错：缓存中的文章详情若为下载源的 404 JSON、无效 JSON、非对象、`guide_id` 不一致、`blocks`/`tools` 结构错误或工具字段无效，客户端会记录警告并继续回退到出厂 `config/guides/` 同名文章，而不是让可选指南资源阻断整个客户端启动。
- 修复已进入 Git 跟踪的 `app/versions/0.1.0/` 基线，并按上述“定向同步”策略前移到 Git 忽略的本地 `app/versions/0.2.0/`，没有整目录复制或覆盖 0.2.0 的其他独立改动。针对 404 缓存与 ID 不匹配缓存新增了基线回归测试；另以 `ModuleLoader` 隔离加载本地 0.2.0，模拟相同 404 缓存后确认仍可离线加载 7 篇出厂指南。
- 当前 `app/state.json` 是启动器保护性回退后留下的用户状态：实际活动版本为 `0.1.7`，`0.2.0` 位于 `bad_versions`。本轮未擅自修改或暂存该文件，也尚未重新启用 0.2.0；如需恢复，应在用户明确授权后移除坏版本标记并作一次真实启动验证。
- 验证（2026-08-23）：`.\.venv\Scripts\python.exe -m pytest -q tests/test_platform_content.py tests/test_publisher_guides.py tests/test_publisher_ui_threading.py`（82 通过）；`.\.venv\Scripts\python.exe -m compileall -q app\versions\0.1.0 app\versions\0.2.0 src tests` 通过；使用 `ModuleLoader` 的 0.2.0 隔离导入、404 缓存回退出厂指南验证通过；`git diff --check` 通过。未启动完整 GUI、未构建、未上传、未推送。

## 2026-08-23：报错指南内容补充与 Hub 指南资源发布

- 客户端出厂 `config/guides/` 已补齐 7 篇低风险指南：网络/下载/TLS/DNS、游戏目录、磁盘空间、补丁状态、补丁资源缺失、安全软件疑似干扰（仅 Windows）及程序更新/模块基础异常。远程 hub 的同一 `guide_id` 现在覆盖出厂正文，不再生成 `remote_<guide_id>` 重复卡片；离线或远程失败时继续读取出厂内容。
- 问题记录与一键排错统一跳转到稳定指南 ID；检查仍为只读、只报告和跳转，绝不自动修复系统、游戏文件、网络或安全软件设置。附件下载改为用户确认后保存到本地指南缓存、打开所在目录并提示自行查看，已删除自动执行 PowerShell、CMD、Shell 或未知可执行文件的行为。
- 发布器增加固定本地运营目录 `publisher-workspace/guides/`：可选的 `guides_index.json`、文章详情 JSON 与 `assets/` 会在现有 hub 生成/发布流程中自动纳入。仅进行 JSON 对象、索引详情、附件存在和平铺文件名/重名检查；不新增独立 Release、在线编辑器、签名、哈希清单或上传队列。导出清理由 `.guides-manifest.json` 限定，只删除此前指南导出器登记的资源，不会误删卡带或公告。
- 发布器卡带中心显示“报错指南”状态、在生成日志中记录已纳入数量，并提供“打开指南目录”按钮；目录不存在时仍可正常生成和发布 hub。首批 7 篇不附带脚本或修复工具。
- 验证（2026-08-23）：` .\.venv\Scripts\python.exe -m pytest -q tests/test_platform_content.py tests/test_publisher_guides.py tests/test_cartridge_catalog.py tests/test_publisher_workspace.py tests/test_publisher_ui_threading.py tests/test_ui_theme.py` 退出码 0；此前专项组合 `tests/test_platform_content.py tests/test_publisher_guides.py tests/test_cartridge_catalog.py tests/test_publisher_ui_threading.py` 为 91 项通过。` .\.venv\Scripts\python.exe -m ruff check app/versions/0.1.0/app_entry.py app/versions/0.1.0/signriver_app/application/guides.py src/signriver_publisher/client_guides.py src/signriver_publisher/workspace.py src/signriver_publisher/cartridge_management_ui.py tests/test_platform_content.py tests/test_publisher_guides.py`、` .\.venv\Scripts\python.exe -m compileall -q app/versions/0.1.0 src tests` 和 `git diff --check` 通过。未启动 GUI 做人工布局验收，未构建发布包或 EXE，未上传或推送；任务结束时已创建本地 Git 提交。
- 风险/后续：未来附带 `asset_name` 的云端附件要求客户端为本次或更高模块版本；首批文章的 `tools` 为空。新增内容必须继续遵守 `docs/error-guide-content-catalog.md` 的安全边界，禁止将 Mod、存档、游戏启动器特化、学习版、加速器、SteamCMD、关闭防护、自动改系统设置、未知脚本或散装 DLL 作为全局指南或自动操作上线。
- 2026-08-23 运行时核对：截图中的 `程序 v0.2.0` 由 `app/state.json` 的 `active_version: "0.2.0"` 加载；该本地、Git 忽略的目标模块未随上一轮基线改动同步，因此仍显示旧的 6 张硬编码卡片。已仅将本轮指南功能前移到本地 `app/versions/0.2.0/`（保留其余 0.2.0 改动），包括指南服务、出厂/远程覆盖、稳定跳转和只下载不执行附件。已用 0.2.0 模块离线读取 7 篇出厂文章通过，并以 `compileall` 通过语法检查；必须完全退出并重新打开客户端后才会加载这些本地改动。该同步目录受 Git 忽略，未新增发布包、远端资源或 Git 跟踪文件。
- 已将“客户端基线与活动模块对齐”写入根目录 `AGENTS.md` 和长期决策：所有后续 AI 必须动态读取 `app/state.json` 的 `active_version`，在当前 GUI 验收前明确并验证“仅基线 / 定向同步 / 正式发布切换”三种处理方式之一；禁止写死版本号、整目录覆盖活动模块，或只验证基线便宣称当前客户端生效。

> 最后更新：2026-08-22（Asia/Shanghai）
> 分支：`main`
> HEAD：`913d115`（`feat: 完善多端卡带与报错指南分化`）
> 工作区：存在多组此前任务留下的未提交发布器、测试、文档和本地状态改动，必须保留；本轮仅新增了客户端一键排错说明、主表保守兼容导出和对应测试。未读取、展示或修改 `config/publisher.local.json`，未进行真实发布、上传或远端写入。

## 2026-08-22：多端卡带与报错指南完成性审计

- 已确认 `tools/build_release.py` 使用 `copytree(ROOT / "config", release / "config")` 递归复制完整配置目录，因此 `config/guides/` 会随 Windows 全量更新包和首次安装包交付；模块更新包只包含模块源码，客户端仍可通过本地缓存或云端 Hub Release 获取指南。
- 一键排错的通用项（网络、游戏目录、近期异常）保持三端可用；仅当当前游戏为本平台声明补丁字段时，才加入补丁状态检查。界面明确提示：Windows 后续可增加更多本地检查，SteamOS/macOS 目前只运行通用检查与可用的补丁状态检查。
- 直接调用 `build_client_cartridge_index()` 而未传入云端资源状态时，兼容回退现仅标记历史 Windows 资源；不能再因 `patch_platforms` 声明而把未上传的 SteamOS/macOS 资源写进主表。正常工作区导出本来就传入精确资源图；文明 VII 仍为 Windows patch-only，不会被隐藏。
- 验证（2026-08-22）：` .\.venv\Scripts\python.exe -m pytest -q tests\test_platform_content.py tests\test_publisher_content_pipelines.py tests\test_cartridge_catalog.py tests\test_cartridge_default_fallback.py`（36 项通过）；` .\.venv\Scripts\python.exe -m pytest -q tests\test_publisher_ui_threading.py`（69 项通过）；` .\.venv\Scripts\python.exe -m pytest -q tests\test_ui_theme.py -k "patch_only_release or catalog_assigns_entries or active_cartridge_switch"`（3 项通过）；`compileall -q app\versions\0.1.0 src`、相关 Ruff 和 `git diff --check` 通过（后者仅既有 CRLF 提示）。未同步忽略的 `app/versions/0.2.0`，未构建、未上传、未推送。

## 2026-08-21：奇迹时代4共享 Launcher DLC 文件组

- 《奇迹时代4》的 `Launcher/dlc` 不是 `Content/<单个 DLC>` 目录集合，而是共享的扁平目录；每项 DLC 由 `slug.dlc.json`（也兼容 `slug.json`）和同名 `slug.png` 组成。
- 发布器新增 `shared_file_pairs` 导入布局：选择该 `dlc` 目录时按 JSON/PNG 对拆成独立受管 DLC，仍分别构建、缓存和发布。卡带改为 `Launcher/dlc`、`grouped_directory` 与根目录覆盖模式；旧工作区在 `initialize()` 自动迁移。
- 客户端将对应 ZIP 作为受限的扁平覆盖包安装到共享目录；仅允许 JSON/PNG 所在的一层文件，安装回执可精确回滚。安装检测要求描述与缩略图同时存在，手动移除也只删除该对文件，绝不删共享目录或其他 DLC。
- 验证：`tests/test_publisher_workspace.py tests/test_multi_game_cartridges.py tests/test_cartridge_catalog.py tests/test_install_engine.py tests/test_publisher_content_pipelines.py tests/test_publisher_ui_threading.py -q` 通过；Ruff、`compileall`、`git diff --check` 通过。未启动 GUI、未构建 EXE、未连接真实远端、未 commit 或 push。

## 2026-08-21：内置 DLC（仅补丁激活）交付模式

- 新增卡带字段 `dlc_delivery_mode`，可选 `download_packages`（默认）和 `built_in`。文明7已经设为 `built_in`；已有发布器工作区会在 `initialize()` 时自动迁移该卡带设置。
- 服务端对此模式不扫描、导入或构建 DLC ZIP，只构建 `unlocker.dll`、`original.dll` 和 AppInfo，并会在构建清理阶段移除旧 DLC ZIP 产物。资源页明确提示“DLC 已随游戏本体安装，无需导入、构建或发布；仅准备补丁资源即可激活”。
- 客户端卡带文档已携带该字段。客户端加载文明7时仍读取 Release 的补丁资产，但 DLC 列表会显示“DLC 已随游戏本体安装，无需额外下载；安装补丁后即可激活”，禁用下载型 DLC 控件并使用“安装补丁并激活”作为主操作。配置卡带和 Hub 索引摘要已同步。
- 验证：`.\.venv\Scripts\python.exe -m pytest -q`、`.\.venv\Scripts\python.exe -m ruff check .`、`.\.venv\Scripts\python.exe -m compileall -q src app\versions\0.1.0` 和 `git diff --check` 均通过。未启动 GUI、未构建 EXE、未连接真实远端、未 commit 或 push。

## 2026-08-21：修复发布器启动时构建队列工具栏布局冲突

- 根因：构建队列标题卡片本身已经以 `grid` 管理子控件，但新增的“一键加入上传队列”按钮误直接挂在该卡片并使用 `pack`，Tk 因同一父容器混用布局管理器而在启动时抛出 `TclError`。
- 按钮现与“刷新”一起挂在独立的 `header_actions` 容器中；标题卡片只使用 `grid`，内部按钮容器只使用 `pack`。已补充源码回归断言，防止重犯。
- 验证：`.\.venv\Scripts\python.exe -m pytest tests\test_publisher_ui_threading.py -q`、Ruff、`py_compile` 与 `git diff --check` 通过；用源码入口隐藏启动 3 秒仍保持运行，随后仅终止本次验证进程。未构建 EXE、未连接真实远端、未 commit 或 push。

## 2026-08-21：远端维护兼容发布开关

- “远端资源维护”工具栏重排为：首行的“刷新远程 / 选择文件上传 / 全部删除”，次行的“兼容发布：保留云端仅有文件”与返回入口；已移除手动“信任云端 DLC”按钮及其写入复用缓存的实现。
- 兼容开关按游戏持久化到工作区的 `.content-publish-options.json`。创建 `GAME_CONTENT` 计划时会冻结该设置：开启时仍上传新增或变化文件与最终 catalog，但不删除本地不存在的远端附件；关闭时保持既有“读取差异、二次确认、镜像删除”逻辑。
- 执行阶段以 `preserve_remote_only_files` 强制屏蔽删除，即使旧的或手工编辑的队列记录含有 `mirror_delete_confirmed=true` 也无法删掉远端旧文件。远端差异摘要和云端详情会随开关显示“云端保留”及相应说明。

验证（2026-08-21）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp C:\ct-compat-check
.\.venv\Scripts\python.exe -m compileall -q src app\versions\0.1.0
.\.venv\Scripts\python.exe -m ruff check .
git diff --check
```

结果：全量 pytest、编译检查、Ruff 通过；diff 检查无空白错误（仅工作副本 LF/CRLF 提示）。未启动 GUI、未构建 EXE、未连接真实远端、未 commit 或 push。

下一步：按日常约定可直接使用 `\.venv\Scripts\python.exe publisher.py` 做人工界面验收；开启兼容发布后加入一个测试队列项，确认确认弹窗与远端详情均显示“保留”，且关闭时仍显示删除清单。用户确认后再决定是否提交当前所有未提交改动。

## 2026-08-21：维多利亚 3 DLC 根目录导入

- 根因：维多利亚 3 的 `game/dlc` 实际是包含多个 `dlcNNN_name` 子目录的根目录，但发布器卡带仍采用单目录导入模式，导致用户选择正确的 `dlc` 根目录后被错误地作为单个 DLC 校验。
- 维多利亚 3 现改为 `children_if_root`；导入根目录会逐项导入其一级子目录，并保留已存在的 `dlcNNN_name` 编号，不会重复添加前缀。已有工作区在下次 `initialize()` 时自动迁移该设置。
- 验证：`.\.venv\Scripts\python.exe -m pytest tests\test_publisher_workspace.py tests\test_publisher_ui_threading.py -q`、`py_compile`、Ruff 与 `git diff --check` 通过。未启动 GUI、未执行真实导入、未构建 EXE、未 commit 或 push。

## 2026-08-21：构建队列批量加入上传队列

- “资源构建队列”顶部新增“一键加入上传队列（N）”，仅在存在构建完成项时可用，顺序以构建队列当前顺序为准。
- 点击后后台顺序读取所有完成项的双端目录差异，完成后显示一次汇总确认：严格镜像项目列出将删除的远端仅有文件，兼容发布项目列出将保留的文件。确认后才依次创建/确认并加入上传队列；预览任一项失败时不加入任何项目。
- 验证：`.\.venv\Scripts\python.exe -m pytest tests\test_publisher_ui_threading.py tests\test_publisher_upload_queue.py tests\test_publisher_content_pipelines.py tests\test_publisher_workspace.py -q`、`py_compile`、Ruff 与 `git diff --check` 通过。未启动 GUI、未连接真实远端、未构建 EXE、未 commit 或 push。

## 2026-08-21：空 DLC 占位目录作为可安装目录包保留

- 部分游戏的 DLC 根目录会保留已编号但没有文件的占位目录（例如维多利亚 3 的主题 DLC）。这类目录可能是最终安装布局的一部分，因此不能跳过。
- 发布器现在生成仅含目录条目的极小 ZIP（嵌套空目录也会保留），正常进入 catalog、远端差异和上传队列；不写入任何伪造占位文件。客户端通用目录安装器已由回归测试覆盖：解压后实际创建目录、回执校验为健康、卸载后目录消失。
- 构建日志以“保留空目录 · 将生成可安装目录包”直出；符号链接仍会拒绝。
- 验证：`.\.venv\Scripts\python.exe -m pytest tests\test_publisher_workspace.py tests\test_install_engine.py tests\test_publisher_ui_threading.py -q` 通过。未启动 GUI、未构建 EXE、未 commit 或 push。

## 2026-08-21：恢复任务后的基础回归与测试契约同步

- 实际工作区以 `main` 的 `bdae05f`（`refactor(publisher): 重构发布中心与上传队列，优化资源与程序发布流程`）为准，相对 `origin/main` 领先 7、落后 0；此前页首记录的 `9f402e3`、领先 5 及既有未提交改动已过期。
- 修复客户端基线的静态检查：延迟焦点回调改为捕获已导入的 `TclError`，两处事件回调改为具名局部函数，并移除无用局部变量；同样改动已同步到被 Git 忽略的活动目录 `app/versions/0.2.0/app_entry.py`。
- SteamOS 补丁测试已对齐发布资产优先级：旧调用即使从游戏主库取得后备原生库，安装凭据也统一标记为 `published_original`。
- 程序发布批次测试已按现行门禁补充当前版本模块归档，并对齐“程序包及模块归档均同名直接替换、随后回读校验”的行为；不再断言远端同哈希文件可跳过上传。
- 已用源码入口启动 `publisher.py`（PID 163128），但未进行人工 GUI 操作或真实双源连通性、上传和发布。

验证（2026-08-21）：

```powershell
python -m pytest -q
python -m ruff check .
python -m compileall -q src app/versions/0.1.0 app/versions/0.2.0
git diff --check
```

结果：全部通过；`git diff --check` 仅显示 Windows 工作副本的 LF/CRLF 转换警告。当前跟踪改动为 `app/versions/0.1.0/app_entry.py`、`tests/test_patch_platforms.py`、`tests/test_publisher_release_batches.py` 和本交接文件；未 commit 或 push。

下一步：人工检查已启动的发布器四个工作区和上传队列 UI；确认后由用户决定是否提交当前改动。不要进行真实上传、构建发布包或 push，除非用户明确要求。

## 2026-08-21：本地 DLC / 补丁资源列表手动刷新

- “资源管理 → 本地资源”中的 DLC 文件夹与补丁资源卡片各新增“刷新列表”按钮；点击后只重新扫描当前游戏对应的本地资源目录并重绘两张列表，不读取云端、不创建发布记录，也不影响发布队列。
- 导入、清理等已有操作完成后仍会自动刷新，手动把文件复制到已打开目录后可用新按钮立即显示。
- “本地与云端差异”页移除了页首泛用的“返回发布包与归档”，仅保留工具栏中更准确的“返回本地发布文件”。
- 验证：`python -m pytest tests/test_publisher_ui_threading.py tests/test_publisher_workspace.py tests/test_publisher_content_pipelines.py -q`（通过）、相关 Ruff 与 `py_compile` 通过、`git diff --check` 仅有 Windows LF/CRLF 提示。
- 已重建 `dist/publisher/SignRiver-Publisher.exe`：15,712,192 B，SHA-256 `68A825449917387CBAF75431A59B0C9F87B66DA34FBA9EB4D391483594ABD285`。未启动新 EXE 做人工验收，未 commit 或 push。

## 2026-08-21：修复“加入上传队列”自动构建的遗留控件引用

- 根因：资源页面已改为只有“加入上传队列”入口，但 `build_all()` 及其进度/完成/失败回调仍直接访问已不存在的旧 `build_button`，因此点击队列入口会在构建开始前抛出 `AttributeError`。
- 构建状态现在统一通过 `_configure_build_actions()` 更新当前页面实际存在的按钮；旧布局若仍提供 `build_button` 也兼容，当前队列页面只更新 `content_enqueue_button`。构建完成后再自动进入既有的队列流程。
- 验证：`python -m pytest tests/test_publisher_workspace.py tests/test_publisher_upload_queue.py tests/test_publisher_ui_threading.py -q`（通过）、`python -m pytest -q`（通过）、相关 Ruff 和 `py_compile` 通过。已重建 `dist/publisher/SignRiver-Publisher.exe`：15,713,850 B，SHA-256 `2D239635C03DB76DE2033F508A1F0C291F8902130A99F2DACF1457D5DE8EA2BF`。未真实构建游戏资源、上传、commit 或 push。

## 2026-08-21：资源构建改为独立队列并恢复上传入口

- 新增持久化 `ContentBuildQueue`：DLC / 补丁发布页的“加入构建队列”会按 FIFO 一次构建一个游戏，构建中的项目在重启后安全重新排队。构建不再占用全局写锁，操作人可以切换到其他游戏继续整理资源；关闭发布器仍会提示等待当前构建结束。
- 构建完成的项目明确显示“待加入上传队列”，只有操作人点击该项的“加入上传队列”才会读取云端差异并要求镜像删除确认，避免构建完成后自动触发远端操作。
- 主发布页现同时保留“查看构建队列”和“查看上传队列”入口；此前后者被错误替换的问题已修复。构建进度改为合并最新事件后再写入 Tk，避免大量压缩进度更新与日志刷新导致界面抽搐。
- 验证：`python -m pytest -q`（通过）、构建队列/上传队列/UI/工作区专项测试、Ruff 与 `py_compile` 通过，`git diff --check` 仅有 LF/CRLF 工作副本提示。已重建 `dist/publisher/SignRiver-Publisher.exe`：15,723,104 B，SHA-256 `8D8EFB4C1BC7AEA95E772F2D3F5A94AF797BC76C2B3A3BC942C2B035F5EAA39E`。未真实上传、commit 或 push。

## 2026-08-21：修复远端维护页读取已移除控件

- 根因：远端维护页已迁移到“账户与测试 → 发布目标”配置，但 GitHub 刷新仍读取旧 `owner_entry/repo_entry/token_entry`，GitLink 路径也保留旧 `token_entry`。点击刷新会抛出 `AttributeError`，使页面停在“正在读取远程资源”。
- GitHub 与 GitLink 远端维护现在统一从已保存的 `PublisherSettings` 读取目标和令牌；配置不完整时会走既有失败收尾，恢复刷新按钮和状态提示，不再卡住。
- 验证：远端维护/UI/工作区/Provider 专项测试、`python -m pytest -q`、相关 Ruff 和 `py_compile` 均通过；`git diff --check` 仅有 LF/CRLF 工作副本提示。已重建 `dist/publisher/SignRiver-Publisher.exe`：15,723,721 B，SHA-256 `A0D734CFEF42E79DCCDC7C7FC379F7A3592400EE5A6B1F52ED1BFB545817F544`。未连接真实远端、上传、commit 或 push。

## 2026-08-21：构建与上传队列按游戏保留最新提交

- 构建队列和上传队列现在以 `game_id` 为唯一键：同游戏的新提交在原队列位置替换旧提交，任何状态下都不会出现第二行同游戏项目。已完成、失败、暂停或等待项会立即改为等待最新提交。
- 若构建或上传正在安全执行，新提交不会强杀当前 ZIP/网络步骤；该唯一队列项会标记“已保留最新提交”。构建的当前步骤结束后自动以最新源文件重新排队；上传的当前步骤结束或失败后自动回到等待状态，以最新 Release 批次重传。这样不会丢失新提交，也不会制造重复项。
- 验证：构建/上传队列、UI、工作区和内容流水线专项测试、`python -m pytest -q`、相关 Ruff 与 `py_compile` 通过；`git diff --check` 仅有 LF/CRLF 工作副本提示。已重建 `dist/publisher/SignRiver-Publisher.exe`：15,724,823 B，SHA-256 `58E0BE4A97B2DA69303F60792336585D1B37B13D180778C722BFC13CB73264D4`。未真实上传、commit 或 push。

## 2026-08-21：程序“发布文件”改为预检后显式开始

- 点击“发布文件”现在只进入执行子页面并自动完成预检；预检通过时明确提示操作人核对结果，并启用“开始发布”按钮。该阶段不会冻结输入、创建上传线程或写入远端。
- 只有点击“开始发布”才会冻结已通过预检的批次，并启动实际后台上传；已暂停、中断、降级或失败的既有批次仍可通过同一按钮继续执行。预检失败及其他未就绪状态均不会上传。
- 验证：`python -m pytest tests/test_publisher_ui_threading.py tests/test_publisher_release_service.py tests/test_publisher_release_batches.py -q`（通过）、`python -m pytest -q`（通过）、相关 Ruff 与 `py_compile` 通过。已重建 `dist/publisher/SignRiver-Publisher.exe`：15,712,843 B，SHA-256 `BEA08202E23872A2FA19CF9B6515C6B313080D858A62007D87BE50B6ACD558C4`；未进行真实上传、未 commit 或 push。

## 2026-08-21：修复远端检测误下载与只读操作阻止退出

- 远端目录、差异和连通性检测现只读取 GitHub/GitLink API 的仓库或 Release 元数据；程序与模块基线不再下载 `update-manifest.json`，游戏内容镜像预览也不下载附件。
- DLC、补丁和 Hub 发布不再在上传前完整下载远端同名附件来判断复用。由于 Release 列表不提供可信 SHA-256，现统一同名直接替换上传，并保留上传后的完整分块回读哈希校验；删除附件则按元数据中的附件 ID 删除并重新读取列表确认。
- “刷新远程资源”改为只读守护任务，不再占用关闭保护；网络卡住时用户可关闭发布器。真正上传、删除和发布仍受关闭保护。GitHub/GitLink API 元数据请求超时已收敛到 12 秒。
- 已重建 `dist/publisher/SignRiver-Publisher.exe`：15,713,215 B，SHA-256 `603CD56C9E6AA268AAE5A54D117727499F643C6A9DA24B8CEF21FE4939565DC3`。

验证（2026-08-21）：

```powershell
python -m pytest -q
python -m ruff check .
python -m compileall -q src app/versions/0.1.0 app/versions/0.2.0
python tools/build_publisher.py --upx-dir C:\Users\32173\AppData\Local\tools\upx\upx-5.0.2-win64
git diff --check
```

结果：pytest、Ruff、编译检查通过；发布器 EXE 构建成功。未启动新 EXE 进行人工 UI 验收，未连接真实 GitLink/GitHub、未读取或修改本地令牌、未真实上传/删除、未 commit 或 push。

## 2026-08-20：移除卡带配置页的旧 Hub / 公告入口

- 删除“游戏卡带配置”页中空置的“Hub / 公告发布”卡片及“创建 Hub / 公告发布记录”按钮；该入口要求手动选择快照和主表，已不符合目前独立的卡带与公告管理流程。
- 一并移除仅供该入口调用的 UI 方法；底层 Hub 发布服务及其覆盖测试仍保留，未影响既有数据兼容能力。
- 验证：`py_compile src/signriver_publisher/content_management_ui.py src/signriver_publisher/release_actions_ui.py`、`pytest tests/test_publisher_ui_threading.py tests/test_publisher_acceptance.py -q`（57 项通过）、相关 Ruff 检查及 `git diff --check` 均通过；后者仅提示既有 LF/CRLF 警告。
- 未重启发布器、未执行真实发布/上传、未提交或推送。

## 2026-08-20：DLC / 补丁远端维护归入资源管理

- “远端维护”实际管理当前游戏的 DLC / 补丁 Release 附件，已从“账户与测试”的二级导航迁入“资源管理”的内部页面。
- DLC / 补丁发布页新增“远端资源维护”入口；维护页增加“返回资源入口”，保持本地资源、上传队列与远端资源处于同一工作区。
- 验证：`py_compile src/signriver_publisher/ui.py src/signriver_publisher/content_management_ui.py src/signriver_publisher/remote_maintenance_ui.py`、`pytest tests/test_publisher_ui_threading.py tests/test_publisher_acceptance.py tests/test_publisher_content_pipelines.py -q`（67 项通过）、相关 Ruff 检查及 `git diff --check` 均通过；后者仅提示既有 LF/CRLF 警告。
- 未重启发布器、未执行真实发布/上传、未提交或推送。

## 2026-08-20：发布目标页改用可点击仓库链接

- 移除 GitLink、GitHub 发布目标卡片中重复的“在浏览器打开仓库”按钮。
- 仓库 URL 改为更大字号的蓝色下划线链接，点击后使用系统默认浏览器打开对应仓库。
- 验证：`py_compile src/signriver_publisher/publisher_targets_ui.py`、`pytest tests/test_publisher_ui_threading.py tests/test_publisher_acceptance.py -q`（57 项通过）、相关 Ruff 检查及 `git diff --check` 均通过；后者仅提示既有 LF/CRLF 警告。
- 未重启发布器、未执行真实发布/上传、未提交或推送。

## 2026-08-20：本地发布文件的云端比较拆为独立差异页

- “验证并查看差异”在完成本地扫描和双端只读核验后，切换到独立的“本地与云端差异”页面。
- 左列汇总本地待新增、同名替换文件；右列按 GitLink/GitHub 展示同名差异及仅云端保留文件。远端保留项只作展示，程序更新同步不会删除。
- 验证：`py_compile src/signriver_publisher/release_center.py src/signriver_publisher/release_center_ui.py`、`pytest tests/test_publisher_ui_threading.py tests/test_publisher_release_service.py -q`（52 项通过）、相关 Ruff 检查及 `git diff --check` 均通过；后者仅提示既有 LF/CRLF 警告。
- 未重启发布器、未执行真实发布/上传、未提交或推送。

## 2026-08-20：程序发布收敛为单次“发布文件”操作

- 本地发布文件页将“进入预检与发布”改为“发布文件”。点击后自动创建或复用当前发布记录、运行预检、在通过时冻结输入并立即进入上传。
- 发布页面保留预检输出、总上传进度、当前文件进度与安全暂停；预检失败会明确显示错误且不会开始上传。
- 验证：`py_compile src/signriver_publisher/release_center.py`、`pytest tests/test_publisher_ui_threading.py tests/test_publisher_release_service.py -q`（52 项通过）、相关 Ruff 检查及 `git diff --check` 均通过；后者仅提示既有 LF/CRLF 警告。
- 未重启发布器、未执行真实发布/上传、未提交或推送。

## 2026-08-20：发布器“发布目标”页合并来源卡片

- 删除“账户与测试 → 发布目标”页顶部的黄色说明框，避免与页面内容重复。
- GitLink、GitHub 各保留一张完整卡片：同一张卡内依次展示当前发布目标、凭据是否已配置、仓库链接与打开操作，以及可编辑的所有者/仓库和保存按钮；不再将“实际目标”和“账号配置”拆成四个彼此交叉的模块。
- 未读取或显示令牌；保存行为仍只更新对应来源的坐标，不影响已冻结的历史上传或发布记录。
- 验证：`py_compile src/signriver_publisher/publisher_targets_ui.py`、`pytest tests/test_publisher_ui_threading.py -q`（42 项通过）、相关 Ruff 检查及 `git diff --check` 均通过；后者仅提示工作区既有 LF/CRLF 警告。
- 未重启发布器、未执行真实发布/上传、未提交或推送。

## 2026-08-20：发布包与归档的历史记录改为只读查看

- 首页两张入口卡片的说明文字明确设为左对齐，避免在宽卡片中出现居中的段落。
- 发布器启动时只将最新的程序更新/公告记录初始化为当前发布上下文；历史列表点击改为 `view_history_record()`，只渲染已保存的详情和远端核对摘要，不会覆盖 `current_batch_id`、版本、收件目录或流程按钮状态。
- 历史详情页移除归档、读取远端基线和导出基线等动作入口，保留为单纯的展示工具；新建或恢复发布仍通过发布准备流程建立当前上下文。
- 验证：`py_compile src/signriver_publisher/release_center.py`、`pytest tests/test_publisher_ui_threading.py tests/test_publisher_release_service.py -q`（52 项通过）、相关 Ruff 检查及 `git diff --check` 均通过；后者仅提示工作区既有 LF/CRLF 警告。
- 未重启发布器、未执行真实发布/上传、未提交或推送。

## 2026-08-20：发布包改用本地文件与云端比较入口

- 移除“替换 Windows 包 / SteamOS 包 / macOS 包”三个单文件按钮；首页主入口改为“管理本地发布文件”，进入带返回按钮的子页面。
- 子页面以收件目录作为本地发布文件目录，点击“刷新并比较云端”会按需创建内部发布记录、重新扫描本地文件并异步读取 GitLink/GitHub 远端目录。
- 比较区逐端展示新增、同名替换、已一致的数量，并列出需新增或替换的文件名；明确同步只新增或覆盖同名文件，绝不删除远端其他旧文件。原有程序更新流水线也不含远端镜像删除步骤。
- 验证：`py_compile src/signriver_publisher/release_center.py src/signriver_publisher/release_center_ui.py`、`pytest tests/test_publisher_ui_threading.py tests/test_publisher_release_service.py -q`（52 项通过）、相关 Ruff 检查及 `git diff --check` 均通过；后者仅提示工作区既有 LF/CRLF 警告。
- 未重启发布器、未执行真实发布/上传、未提交或推送。

## 2026-08-19：修复 0.2.0 客户端设置页启动失败

### 原因与修复

- `_blue_switch()` 已默认传入 `width=154`，而两个无文本设置开关又传入 `width=54`；两次传递同名关键字参数使 `CTkSwitch` 初始化直接抛出 `TypeError`。
- 该帮助函数现在通过 `kwargs.pop("width", 154)` 允许调用方覆盖默认宽度，保持无文本开关原有的 `54 px` 宽度。
- 修复先写入受跟踪基线 `app/versions/0.1.0/app_entry.py`，再同步到活动模块 `app/versions/0.2.0/app_entry.py`；`app/state.json` 已恢复为活动版本 `0.2.0`，并清空 `bad_versions`。
- 日志中的 `0.1.7` 数据库 schema 版本过旧错误是 0.2.0 启动失败后回退旧模块造成的连带结果；恢复 0.2.0 后不会走该回退路径。

### 验证与边界

- `./.venv/Scripts/python.exe -m py_compile app/versions/0.1.0/app_entry.py app/versions/0.2.0/app_entry.py`：通过。
- `./.venv/Scripts/python.exe -m pytest tests/test_ui_theme.py tests/test_user_settings.py tests/test_client_problem_center.py -q`：60 项通过。
- 已用源码入口启动客户端（PID 164996），供人工确认窗口正常出现。
- `ruff` 仍仅报告基线既有的 `app/versions/0.1.0/app_entry.py:6851` 未使用局部变量 `cartridge`；未扩大本次修复范围处理。`git diff --check` 仍仅报告用户已有 `src/signriver_publisher/ui.py` 文件尾空行。

## 2026-08-19：测速的瞬时 TLS EOF 自动重试

- 用户遇到的 `SSL: UNEXPECTED_EOF_WHILE_READING` 表明连接在读取任何测速数据前被对端提前关闭；随后人工重新测速成功，符合瞬时连接中断特征。
- `measure_download_speed()` 现在仅对首次、尚未读取数据的该类 TLS EOF 等待 `0.4` 秒后自动重试一次；证书校验失败、下载中途失败或第二次失败仍保持原始错误。
- 修改已同步到 `app/versions/0.1.0/` 与活动的 `app/versions/0.2.0/`。
- 验证：`py_compile` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_speed_test.py tests/test_ui_theme.py tests/test_user_settings.py -q` 为 53 项通过；针对测速文件与测试的 Ruff 检查通过。`git diff --check` 仍仅报告用户已有 `src/signriver_publisher/ui.py` 文件尾空行。

## 2026-08-19：恢复当前游戏选择器的紧凑外观

- 保留可搜索、可滚动的现有游戏选择弹层；未展开的触发器改为白底文本区加右侧独立蓝色下拉按钮，接近原 `CTkComboBox` 的视觉层级，不再整块填充蓝色。
- 游戏加载和修复期间会同时禁用文本区与下拉按钮，防止绕开既有的游戏切换锁。
- 修改已同步到受跟踪基线与活动 `0.2.0` 模块。`py_compile` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_ui_theme.py tests/test_user_settings.py -q` 为 50 项通过。
- 已启动最新源码客户端（PID 171484）供人工视觉核对。Ruff 仍仅报告既有未使用的 `cartridge` 局部变量；`git diff --check` 仍仅报告用户已有发布器 UI 文件尾空行。

### 后续修正

- 先前以 `CTkFrame + CTkButton` 拼接的版本未能正确裁切分段圆角，视觉效果不合格，已替换。
- 现在直接使用 `CTkComboBox` 的原生画布分段外观（白底输入区、圆角边框、右侧蓝色箭头），并把输入区、右侧区域和箭头的点击事件全部重定向到既有可搜索弹层；不会打开原生列表。
- 重新验证：两个版本 `py_compile` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_ui_theme.py tests/test_user_settings.py -q` 为 50 项通过；相关 Ruff 检查通过。`git diff --check` 仍只报告既有发布器 UI 文件尾空行。

## 2026-08-19：精简游戏搜索结果行

- 搜索列表不再把内部 `game_id` 当作每个游戏的第二行展示；该标识仍参与中英文/标识搜索。
- 非当前游戏改为单行紧凑条目；当前游戏保留第二行“✓ 当前选择”提示。
- 验证：两个版本 `py_compile` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_ui_theme.py tests/test_user_settings.py -q` 为 50 项通过；相关 Ruff 检查通过。`git diff --check` 仍只报告既有发布器 UI 文件尾空行。

## 2026-08-19：将问题中心与日志收敛到报错指南入口

- 侧栏一级入口由“问题中心 / 日志”改为单个“报错指南”；未解决问题数量继续显示在该入口上。
- 报错指南首页提供下载/测速、TLS、DLC/补丁与安全软件四类常见处理提示，并提供“问题记录”和“运行日志”两个二级入口。
- 原有问题记录和运行日志功能均保留为详情页；详情页新增“返回指南”，不再占用侧栏一级导航。
- 修改同步到受跟踪基线与活动 `0.2.0` 模块。验证：两个版本 `py_compile` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_ui_theme.py tests/test_client_problem_center.py tests/test_user_settings.py -q` 为 61 项通过；相关 Ruff 检查通过。`git diff --check` 仍只报告用户已有发布器 UI 文件尾空行。


## 2026-08-18：0.2.0 三端客户端构建核对与收尾

### 已完成

- 已核对版本链路：`src/signriver_launcher/constants.py` 的 `LAUNCHER_VERSION`、`app/state.json` 的 `active_version` 与 `app/versions/0.2.0/module.json` 均为 `0.2.0`。
- 由于 `app/versions/0.2.0/` 被 Git 忽略且包含比 `0.1.0` 基线更晚的问题中心、补丁健壮性等业务逻辑，本轮仅将已验收的设置页分组和可搜索游戏选择器**选择性移植**到活动目录的 `app/versions/0.2.0/app_entry.py`；没有整目录覆盖，避免回退现有业务能力。
- 已通过：
  - `./.venv/Scripts/python.exe -m py_compile app/versions/0.2.0/app_entry.py`
  - `./.venv/Scripts/python.exe -m pytest tests/test_ui_theme.py tests/test_user_settings.py tests/test_client_problem_center.py -q`（60 项通过）
  - `git diff --check`
- 已重新生成平台无关的活动模块归档，并核验归档内的 `app_entry.py` 同时包含设置页分组和可搜索游戏选择器：`dist/modules/SignRiver-DLC-Hub-module-v0.2.0.zip`，`201,129` B，SHA-256 `3802e2fff8fdc53b7b53751a3282e07ea320be7bdc298549ef12833ab5e206db`。
- Windows 当前源码包已重新构建并核验包内包含 `0.2.0` 的设置页分组及可搜索游戏选择器：
  - `dist/bin/SignRiver-DLC-Hub.exe`：`17,334,682` B；SHA-256 `432a04c5ff76fb09410e765a16a19a4884538586f9c52c4071f3d231190c280a`
  - `dist/唏嘘南溪DLC一键解锁工具-v0.2.0-windows-x64.zip`：`19,274,231` B；SHA-256 `92f7006e51e09eab112dfb19aa964c989d4c07f0eb83b5361a5195c9a8dda816`
  - `dist/updates/SignRiver-DLC-Hub-full-v0.2.0-windows-x64.zip`：`19,242,235` B；SHA-256 `fb071a5c9977cd577571afa1c30db321c08cff1b3202aee6339be2724fe7c585`
- 未启动 Windows GUI 进行人工视觉验收；未生成或替换任何远端更新清单，未上传发布资产，未执行 commit 或 push。

### 当前阻塞：SteamOS 原生重建

- SteamOS VirtualBox 虚拟机及本机 `127.0.0.1:2222` SSH 转发存在，但无交互 SSH 探测返回 `Permission denied (publickey,password)`。
- 已正常关闭该虚拟机；没有猜测密码、读取私有凭据或绕过来宾登录。
- Windows 已确认拒绝交叉生成最终包：`tools/build_native_release.py --platform steamos` 必须在 SteamOS 中执行。

### 当前阻塞：macOS 原生重建

- 已定位 macOS VMware 虚拟机配置，来宾为 Darwin 24，当前未运行；未发现已启用的 SSH 端口转发或可用的非交互来宾命令执行通道。
- `tools/build_native_release.py --platform macos` 已确认只能在 macOS 原生环境中执行；现有 `dist` 中的 macOS 包早于本次活动目录同步，不能作为本轮最终候选。
- 未改动 VMware / macOS 配置，未猜测任何登录信息或读取私有凭据。

### 结论与下一步

- Windows `0.2.0` 客户端与完整更新包已完成本轮重建；SteamOS、macOS 的旧 `0.2.0` 产物不能与 Windows 产物共同构成最终三端候选。
- 因 SteamOS / macOS 缺少合法的无交互接管或人工协作通道，三端构建**实际阻塞**。在两个原生来宾分别提供可执行通道前，不得生成最终三端双源更新清单、上传资产或宣称跨平台发布完成。
- 恢复后应仅同步构建所需工作区（排除 `.git`、`.venv`、`build`、`dist`、`publisher-workspace`、`config/publisher.local.json`、缓存与字节码），在各自原生系统执行：
  - SteamOS：`python3 tools/build_native_release.py --platform steamos`
  - macOS：`python3 tools/build_native_release.py --platform macos`
- 两端回传后核验包内 `app/versions/0.2.0`、平台标识、大小与 SHA-256；macOS 还需完成既定的 DLC 下载/哈希、补丁、权限/哈希与失败恢复人工验收。完成前不推送 Git。


## 2026-08-18：客户端“设置”页内部结构优化（待人工界面验收）

### 当前目标

在不改变客户端顶部、左侧导航、整体色板、圆角、页面宽度和视觉语言的前提下，将“设置”页从多张独立大卡片改为更紧凑、有层级的单列设置中心。

### 已完成改动

- `app/versions/0.1.0/app_entry.py`：将原有六张设置大卡片归并为三个单列分组卡片：
  - **下载与网络**：下载源、网络测速、超时检测；
  - **程序与存储**：程序更新、缓存管理；
  - **常规设置**：公告提醒，并预留后续普通偏好项的位置。
- 新增紧凑组标题、设置行和分隔线辅助布局：左侧呈现名称与简短说明，右侧承载下拉框、按钮、状态或开关；保留原有控件对象和事件处理，避免改变下载源、测速、更新、缓存、公告的业务逻辑。
- 缓存类操作调整为较弱的描边/浅色操作，检查更新和开始测速保留更明确的主操作层级；开关仅在右侧显示，说明在左侧。
- `tests/test_ui_theme.py`：更新布局断言以覆盖新的三组结构，并同步更改下载源链接文案断言。

### 验证（2026-08-18）

- `./.venv/Scripts/python.exe -m py_compile app/versions/0.1.0/app_entry.py tests/test_ui_theme.py`：通过。
- `./.venv/Scripts/python.exe -m pytest tests/test_ui_theme.py tests/test_user_settings.py -q`：50 项通过。
- `git diff --check`：通过。
- 未启动客户端进行人工 GUI 验收；未构建 EXE，未提交、未推送，未进行下载、更新或远端访问。

### 下一步

1. 仅启动源码客户端，人工检查设置页在常规与较窄窗口宽度下的显示：三组卡片、分隔线、右侧缓存按钮与程序更新操作区均不应溢出或拥挤。
2. 确认后由用户决定是否提交当前改动；不要同步到发布版本目录或构建安装包，除非后续明确进入版本构建流程。


## 2026-08-18：客户端“游戏检测”可搜索选择器（待人工界面验收）

### 当前目标

在不改动“游戏检测”卡片、主页面布局、整体色板和主要游戏操作的前提下，让“当前游戏”在未来支持更多游戏时仍可快速检索与选择。

### 已完成改动

- `app/versions/0.1.0/app_entry.py`：将原生 `CTkComboBox` 替换为保持原尺寸和输入框边框风格的选择按钮；未展开时仅显示当前游戏及下拉提示，主页面不常驻搜索框。
- 点击选择按钮后临时打开同风格的无边框 `CTkToplevel` 选择区域：顶部有搜索输入框，列表使用固定高度的 `CTkScrollableFrame`，游戏数量增加不会撑高页面或弹层。
- 搜索不区分大小写，匹配选择名、展示名和 `game_id`，因此可覆盖中文名称、英文名称及游戏标识；无搜索词时显示完整支持列表。
- 当前游戏以浅蓝底和“✓ 当前选择”标记；无匹配时提示可尝试中文名、英文名或游戏标识；按 `Escape`、失焦、选择游戏或关闭客户端时均关闭临时选择区。
- 继续复用既有 `_select_game()`、卡带懒加载、下载/安装任务阻止切换和修复流程的状态锁定逻辑；选中成功后同步更新选择按钮文本。
- “导出支持列表”保留原功能，但改为较窄的描边透明辅助按钮，降低相对“启动游戏”等主操作的视觉权重。
- `tests/test_ui_theme.py`：更新下拉数量断言，并新增选择器、搜索浮层、滚动列表、中英文/标识匹配、当前选择与空状态、辅助导出样式的源码级覆盖。

### 验证（2026-08-18）

- `./.venv/Scripts/python.exe -m py_compile app/versions/0.1.0/app_entry.py`：通过。
- `./.venv/Scripts/python.exe -m pytest tests/test_ui_theme.py tests/test_user_settings.py -q`：50 项通过。
- `./.venv/Scripts/python.exe -m ruff check app/versions/0.1.0/app_entry.py tests/test_ui_theme.py`：未通过，但唯一报错为 `app/versions/0.1.0/app_entry.py:6851` 的既有未使用局部变量 `cartridge`；该行已存在于 `HEAD`，本轮未改动，未为避免扩大范围而处理。
- 尚未启动客户端进行人工 GUI 验收；未构建 EXE，未提交、未推送，未进行下载、更新或远端访问。

### 下一步

1. 仅启动源码客户端，检查“游戏检测”区域未展开时仍保持现有布局；展开时确认搜索、滚动、当前选择高亮、空状态、点击外部关闭和 `Escape` 关闭均符合预期。
2. 检查窗口靠近屏幕底部时，选择区会自动显示到选择按钮上方且不越出屏幕。
3. 人工确认后由用户决定是否提交当前客户端与此前设置页改动；不要同步到发布版本目录或构建安装包，除非后续明确进入版本构建流程。

---

> 最后更新：2026-08-17（Asia/Shanghai）
> 分支：`main`
> HEAD：`a57c43ca5690ac4e4e304754a975ab34b029cb41`（`a57c43c feat: 重构原生库生命周期并完善项目技能`）
> 上游状态：`main` 相对 `origin/main` 领先 3、落后 0；仍不得在发布资产上传并核验前推送
> 工作区：本轮新增 `docs/publisher-refactor-plan.md`，并修改 `docs/agent/DECISIONS.md`、`docs/agent/HANDOFF.md`；未修改业务代码，未重置、清理、提交或推送。

## 当前有效结论

- `0.2.0` 的统一问题中心、稳定错误分类、下载状态持久化、补丁 SHA-256 强制校验、应用前后复验、异常恢复及疑似安全软件拦截处理已完成，并包含在本地提交 `930b435`（`feat: 完成 0.2.0 问题中心与补丁健壮性优化`）中。
- 启动器的模块加载、更新下载/应用、自动回滚和致命错误已接入共享问题记录；问题动作只使用代码内允许列表，问题存储失败不得遮蔽主业务成功结果。
- `app/versions/0.1.0/` 已同步到 Git 忽略的 `app/versions/0.2.0/`，目标模块元数据为 `version=0.2.0`、`api_version=3`；`publisher-workspace/update-notes.json` 已包含对应中文更新说明。
- 当前只有 Windows 包是基于本轮代码重建的候选；旧 macOS/SteamOS 包早于本轮代码，已从当前平台清单排除，不能作为最终 `0.2.0` 候选。
- macOS `0.2.0` 不再以游戏内运行作为发布门槛。原生重建后只手动验收 DLC 下载及大小/SHA-256、补丁安装、目标文件权限/哈希、失败恢复，并可选确认卸载/原版恢复；必须明确标注“游戏内兼容性未纳入验收范围”。
- 当前线上正式版本仍为 `0.1.7`；`0.2.0` 已本地提交，但尚未上传发布资产或推送代码，不能宣称三平台发布就绪。

## 修改范围

本地提交 `930b435` 包含 39 个受控文件，主要范围如下：

- 客户端问题中心与下载/补丁健壮性：`app/versions/0.1.0/app_entry.py` 及 `app/versions/0.1.0/signriver_app/` 下相关 domain、application、downloads、persistence、diagnostics 文件。
- 共享问题模型：`src/signriver_common/problems.py`、`src/signriver_common/__init__.py`。
- 启动器问题记录与更新/回滚：`src/signriver_launcher/problem_reporting.py`、`api.py`、`full_update_helper.py`、`main.py`、`updater.py`。
- 构建可重复性：`tools/build_release.py`、`tools/build_native_release.py`，显式排除未使用的 NumPy。
- 回归测试：问题模型、客户端问题中心、启动器问题记录、API，以及下载、持久化、诊断、更新、UI、构建和发布源测试。
- 发布元数据与说明：`config/module-archives.json`、`docs/current-progress.md`、`docs/macos-virtual-machine-setup.md` 和 agent 文档。
- Git 忽略但后续发布必须保留并复核：`app/versions/0.2.0/`、`publisher-workspace/update-notes.json`、`dist/`。

## 最新验证

2026-08-17 在 `main@930b435` 上重新执行：

- `python -m pytest -q`：完整测试套件通过。
- `python -m ruff check .`：通过。
- `python -m compileall -q src app/versions/0.1.0 app/versions/0.2.0`：通过。
- `git diff --check`：通过。
- 验证前 `git status --short` 为空；`main` 相对 `origin/main` 为 `ahead 1`。

## 已知失败路线与安全边界

- 不得从问题记录执行命令、脚本或任意 URL；只解析固定动作 ID。
- 不得关闭或暂停 Defender、自动添加排除目录、自动恢复隔离文件；只能引导用户核对来源与哈希后在系统界面手动处理。
- 疑似安全软件拦截后不得复用 `.part` 文件或无限重试；用户确认处理后必须从头下载并重新校验。
- Windows frozen 进程不能直接覆盖正在运行的 EXE；延迟 helper 或超过 onefile 父进程生命周期的子进程必须设置 `PYINSTALLER_RESET_ENVIRONMENT=1`。
- 构建机可选依赖会改变 PyInstaller 分析；项目未引入 NumPy 前必须保留 `--exclude-module numpy` 及其回归测试，不能靠临时卸载依赖控制包体积。
- 三平台清单不能分三次写入同一输出位置；三个原生包齐备后必须在一次 `prepare_update_release.py` 调用中同时传入三个 `--platform-package`。
- PowerShell 直接传中文 notes 可能乱码；继续由 Python 以 UTF-8 读取 JSON，并用 `subprocess.run([...])` 传参。
- Git 忽略的历史版本目录可能污染原生候选包；只可在一次性复制工作区中清理并重建受控版本集合，不得清理主工作区或用户安装目录。

## 风险

1. macOS Intel x64 与 SteamOS x64 尚未从 `930b435` 对应源码重新构建和验收；现存旧包不可复用。
2. 当前双源清单只包含 `windows-x64`，三平台清单、首装包和线上资产仍不完整。
3. 在模块归档和各平台发布包上传并核验前推送，会触发 CI 从 GitLink 恢复归档，可能因线上资产缺失或 SHA-256 不匹配失败。
4. macOS 的退化验收只能证明下载、校验和补丁文件流程，不能证明 Steam/Paradox Launcher 或游戏本体的运行兼容性。

## 下一步

1. 在 macOS Intel x64 与 SteamOS x64 原生主机上，从当前提交对应源码重新构建 `0.2.0` 全量更新包和必要首装包。
2. 按平台执行下载、大小/SHA-256、补丁安装、目标文件权限/哈希和失败恢复验收；macOS 按退化范围记录结果，不做游戏内兼容性声明。
3. 三个平台的新包齐备后，一次性生成双源清单，并核对 URL、size、SHA-256、平台集合和中文 notes。
4. 按“先上传并核验模块归档与所有发布包，最后上传清单”的顺序准备发布；资产就绪后再由用户决定何时执行 `git push origin main`。
5. 新任务开始前先检查 `git status --short`；交接旧记录中“只存在本交接文档改动”的说法已失效，必须保留并核对 `DECISIONS.md`、`HANDOFF.md` 和 4 个未跟踪项目技能目录，不得重置或覆盖。

## 本次补充：上下文切换技能

- 已新增项目技能 `.agents/skills/project-context-switch/SKILL.md`，可使用 `/project-context-switch` 替代重复粘贴上下文切换核对提示。
- 技能会读取 `AGENTS.md` 和 `docs/agent/` 交接文档，核对分支、HEAD、Git 状态、上游差异与相关验证，并在任何改动前报告文档与真实工作区是否冲突。
- 本次只新增技能文件，并在 `DECISIONS.md`、`HANDOFF.md` 追加长期流程记录；未重置或覆盖既有未提交内容。
- 验证：`SKILL.md` 已检查 YAML front matter、文件引用和 Markdown 结构；未执行专门自动化测试（仅文档/技能改动）。

- 上下文工作流已拆分为两个项目技能：`project-context-switch`（进入新对话/新任务）和 `project-handoff`（结束任务/转出对话）；二者都支持自然语言触发，斜杠命令仅是可选简写。

## 本次补充：运行当前源码技能与验证异常

- 已新增 `.agents/skills/run-current-client/SKILL.md`：自然语言“运行/启动当前客户端程序”会以项目虚拟环境优先运行 `launcher.py`，不构建或启动旧的 `dist` 产物。
- 已新增 `.agents/skills/run-current-publisher/SKILL.md`：自然语言“运行/启动当前服务端程序”默认运行内部发布器 `publisher.py`；本项目没有独立 Web 服务端，若用户指其他服务必须先澄清。
- 2026-08-17 在 `main@0af58d7` 执行完整 `python -m pytest -q` 时，`tests/test_publisher_acceptance.py::test_patch_preparation_refuses_environment_changed_after_baseline` 因 Windows `PermissionError [WinError 5]`（临时 baseline 目录 `Path.replace`）失败；`python -m ruff check .` 与 `python -m compileall -q src app/versions/0.1.0 app/versions/0.2.0` 通过。此前“完整 pytest 通过”的记录与本次真实结果不一致，后续应先复现并定位该权限失败。

- 已新增 `commit-current-changes`（仅本地提交）和 `commit-and-push`（用户明确要求时提交并推送）两个项目技能；后者对发布链路改动会要求先确认线上资产已上传并核验。

## 本次补充：Git 提交技能

- 已新增 `.agents/skills/commit-current-changes/SKILL.md`：用户以自然语言“进行一次提交”“提交当前改动”等触发时，仅做精确暂存后的本地提交，绝不自动推送。
- 已新增 `.agents/skills/commit-and-push/SKILL.md`：仅在用户明确说“提交并推送”等时触发；发布链路改动必须先确认线上模块归档、更新包与清单均已上传并核验，才允许普通推送。
- 两个技能均禁止盲目暂存、强推、重写历史、重置或覆盖其他未提交改动；斜杠命令是可选简写，自然语言同样可触发。
- 验证：已检查两个 `SKILL.md` 的 YAML front matter、命名、描述、行数和 Markdown 结构；`python -m pytest -q tests/test_publisher_acceptance.py::test_patch_preparation_refuses_environment_changed_after_baseline` 本次复跑通过。完整 `python -m pytest -q` 的最近一次结果仍有一次 Windows `WinError 5` 失败记录，尚待稳定复现和定位。

## 本次补充：Skill 执行效率优化

- 已将 `run-current-client` 与 `run-current-publisher` 改为动作优先：对单纯“运行/启动”请求，读取 Skill 后首个工具调用直接启动 GUI 并返回 PID，不再预读项目文档、Git、入口文件或虚拟环境，也不等待、轮询或跑测试。
- 仅在直接启动失败，或用户明确要求诊断、构建、测试时，才做一次性诊断或进入扩展流程。
- 已审计其余 Skill：上下文切换、交接、提交与推送所列核对直接承担工作区一致性、精确暂存和发布资产保护职责，未将其删减为不安全的“无检查执行”。
- 验证：全部 6 个项目 Skill 的 YAML front matter、名称、描述与行数校验通过；`git diff --check` 通过。未启动额外 GUI 实例验证，以避免在用户当前已打开客户端时重复启动。
## 本次交接补充：项目技能与云端资源结论

- 未提交的项目技能共 4 个目录：`.agents/skills/run-current-client/`、`.agents/skills/run-current-publisher/`、`.agents/skills/commit-current-changes/`、`.agents/skills/commit-and-push/`；此前已提交的上下文技能由 `0af58d7` 引入。运行类技能已明确采用“动作优先”：对仅要求启动的消息，读取 Skill 后首个工具调用直接 `Start-Process`，不做无关预检。
- 本轮仅核对并说明云端资源架构，未改动业务代码、发布配置或云端资产：客户端使用 GitLink/GitHub 双源镜像的 Release 静态资产；更新清单按 `windows-x64`、`steamos-x64`、`macos-x64` 选择各自原生更新包。通用、已获授权的数据资源可跨平台复用；依赖系统加载机制的原生组件必须按平台区分。
- 涉及第三方付费 DLC、授权绕过或 DRM 规避的资源，不得在后续工作中设计、整理或下发其具体二进制排列；如需演进资源架构，仅限合法自有/获授权内容，并以静态目录、大小和 SHA-256 校验管理。

## 本次验证

- `git diff --check`：通过（仅出现 LF→CRLF 工作区警告）。
- 本次未运行 pytest、Ruff、构建或 GUI；不得将本轮视为业务功能已验证。
- 完整 pytest 的最近已知结果仍存在一次 Windows `PermissionError [WinError 5]` 间歇失败；目标用例曾单独复跑通过，尚未定位根因。

## 下个上下文的优先事项

1. 先使用 `project-context-switch` 核对交接与实际 Git 状态；重点确认 4 个未跟踪 Skill 目录和两个 agent 文档改动仍存在。
2. 若用户要求提交 Skill 改动，只精确暂存这 6 个项目 Skill 与必要 agent 文档，先审阅 diff；除非用户明确要求，不得推送。
3. 若继续三平台发布工作，仍按本文件前述的原生构建、资产上传、清单核验和后续推送顺序执行。
4. 如处理测试稳定性，优先复现并定位 `tests/test_publisher_acceptance.py::test_patch_preparation_refuses_environment_changed_after_baseline` 的 Windows 文件替换权限异常。

## 本次交接补充：三平台原生库生命周期重构

- 已将客户端和发布器补丁合同从三资产改为“代理库 + AppInfo”两资产；旧 Release 的原生库资产保持可读但被新客户端忽略，卡带字段迁移为 `runtime_original_library_name` 并兼容旧字段别名。
- 已新增持久原生库保险库、PE/ELF/Mach-O x86_64 校验、安装身份与跨进程锁、schema 2 安装凭据、schema 1 迁移、事务化应用/恢复/`repair_patch()` 和持久修复日志。
- 一键修复已改为先完成资源与原生库预检，再原地修复补丁并逐项事务重装 DLC；不再调用 `reset()`，不再预先批量删除 DLC。修复中断后由用户再次点击一键修复，从安全预检阶段幂等重放。
- 已新增 `docs/original-library-lifecycle.md`，并同步更新 `docs/publisher-guide.md` 与 `docs/cross-platform-patch.md`；发布器验收界面不再使用“原版备份 DLL”发布资产术语。

### 本次验证

- `python -m compileall -q app/versions/0.1.0 src/signriver_publisher`：通过。
- `python -m pytest -q tests/test_patch_engine.py tests/test_patch_platforms.py tests/test_repair_journal.py --tb=short`：48 passed。
- 客户端目录、卡带、问题中心、原版恢复和主题相关定向测试：全部通过。
- 发布器工作区、验收和 UI 线程相关定向测试：全部通过；旧术语收尾后再次运行 `tests/test_publisher_acceptance.py tests/test_publisher_ui_threading.py`，全部通过。
- `git diff --check`：通过，仅有现有换行符转换警告。

### 未执行与后续

- 未运行完整 pytest，未构建客户端、发布器、模块归档或更新包，未修改版本号，未提交，未推送。
- 尚未在合法的 Windows x64、SteamOS x64、macOS Intel x64 游戏安装中执行真实启停、应用、修复和恢复验收；发布前必须按 `docs/original-library-lifecycle.md` 的平台清单完成。
- 真实平台验收必须重点确认：任何失败路径不删除唯一可信原生库；Windows 文件占用时阻断；SteamOS 权限位和符号链接处理正确；macOS 不修改或重签用户原生库。
## 2026-08-17 切换对话前最终状态

- 当前分支：`main`。
- 当前 HEAD：`a57c43c`（`feat: 重构原生库生命周期并完善项目技能`）。
- 原生库生命周期重构、相关测试/文档以及 4 个项目 Skill 已纳入该本地提交；本节覆盖上文“尚未提交 Skill”和“本轮未提交”的旧进度描述。
- `main` 相对 `origin/main` 领先 3 个提交，尚未推送。除本次交接对 `docs/agent/HANDOFF.md` 的更新外，提交后工作区原本为空。

### 已验证

- 补丁引擎、三平台路径与格式、修复日志测试：48 passed。
- 客户端目录、卡带、问题中心、原版恢复和主题相关定向测试：全部通过。
- 发布器工作区、验收和 UI 线程相关定向测试：全部通过。
- Python 编译检查和 `git diff --check`：通过；仅有换行符转换警告。

### 下一窗口直接执行

1. 先运行 `project-context-switch`，核对 `main@a57c43c`、工作区和本交接内容。
2. 若继续发布准备，先完成合法 Windows x64、SteamOS x64、macOS Intel x64 安装上的真实应用、修复、恢复验收；当前不能宣称真实三平台游戏验收完成。
3. 尚未运行完整 pytest，尚未构建客户端、发布器、模块归档或更新包，也未修改版本号。
4. 在发布资产上传并核验前不得推送；只有用户明确要求“推送”或“提交并推送”后才可执行 `git push origin main`。

## 2026-08-17：发布器重构规划交接

### 本轮结论与文档

- 本轮只完成发布器现状调研、目标架构确认和实施计划落文档，没有修改任何业务代码、测试代码、版本号、构建产物或远端资源。
- 完整计划已写入 `docs/publisher-refactor-plan.md`，内容覆盖四区任务导航、三类独立流水线、持久化发布批次、分级硬门禁、双源安全顺序、重启恢复、模块边界、分阶段迁移和验收矩阵。
- 长期方案已同步到 `docs/agent/DECISIONS.md`：三端原生构建、Windows 汇总发布、数据包先就绪再切换清单、任务式导航、高风险功能隔离和分阶段替换。
- 当前发布器“臃肿”的核心判断是界面信息架构和控制层职责过度集中，而不是现有业务能力应被大幅删除。

### 已确认的实施边界

- 一键发布采用受控流水线：自动预检、校验、双源上传和清单切换，真正发布前保留一次集中确认，不做完全无人值守。
- Windows、SteamOS x64、macOS Intel x64 包继续在各自原生环境构建；Windows 发布器只负责汇总、严格校验和统一发布。
- 程序版本、游戏内容、Hub 与公告使用三类独立流水线；主界面重组为发布中心、内容与卡带、验收中心、高级维护。
- 发布批次保存输入指纹、预检、阶段检查点、错误和审计事件，但不保存凭据，也不长期复制三端大包。
- 版本、平台、架构、包结构、哈希、三端一致性和双源配置是硬门禁；人工验收仅作参考，未完整通过只显示警告，不阻止确认或执行；验收快照变化仍会使预检和确认失效。
- 单源发布、远程删除、采用远端附件和手动修复保留在高级维护，不进入普通发布主路径。

### 本轮验证

以下发布器专项测试在规划调研阶段已运行并通过：

- `tests/test_publisher_main.py`
- `tests/test_publisher_workspace.py`
- `tests/test_publisher_updates.py`
- `tests/test_publisher_github.py`
- `tests/test_publisher_announcements.py`
- `tests/test_publisher_acceptance.py`
- `tests/test_publisher_ui_threading.py`

本轮未运行完整 pytest、Ruff、客户端/发布器构建、模块归档构建、更新包构建或 GUI 人工验收。不得将本轮文档规划视为重构功能已经实现或发布就绪。

### 下一窗口直接执行

1. 必须先运行项目 `project-context-switch`，重新读取项目规则和本交接，并核对实际分支、HEAD、工作区和相关测试；以真实 Git 与可重复测试为准。
2. 首个实施阶段只建立发布批次领域模型、集中状态转换、`ReleaseStore`、事件记录、基础预检和编排/远端接口骨架；不要先大改 UI，也不要移动或删除旧实现。
3. 将首批改动拆成可独立验证的小步，优先覆盖序列化、原子保存、非法状态转换、输入指纹失效和 `running` 重启后转 `interrupted`。
4. 保留现有发布能力和七个发布器专项测试；新路径达到测试对等并完成人工验收前，不删除旧入口。
5. 首轮不实现远程 VM、共享目录监听、CI 构建调度或跨平台交叉构建。
6. 除非用户明确要求，不执行提交；任何提交后也不得自动推送。发布资产上传并核验前尤其不得执行 `git push`。


## 2026-08-17：发布器重构阶段 1 实施交接

### 已完成

- 已新增 `release_models.py`：批次、产物、预检、阶段、事件、顶层状态枚举，以及集中状态转换和冻结输入失效逻辑。
- 已新增 `release_store.py`：按批次目录保存 `plan.json`、`artifacts.json`、`preflight.json`、`stages.json`，采用临时文件与 `os.replace` 原子写入；`events.jsonl` 追加写入并按敏感键脱敏。
- `ReleaseStore` 支持活动索引、损坏批次隔离，以及启动时把遗留 `running` 批次转为 `interrupted` 并记录恢复事件。
- 已新增 `artifact_collector.py` 和 `release_preflight.py`：发现 Windows、SteamOS x64、macOS Intel x64 程序包，冻结大小、mtime 与 SHA-256，检查路径、指纹、双源配置、三端齐全、版本一致和更新说明。
- 已新增 `release_interfaces.py` 与 `release_orchestrator.py`：定义远端源和流水线阶段边界；编排器可执行预检、集中确认、持久化阶段检查点、失败记录、重试入口和完成状态，不依赖 GUI 或真实网络。
- 旧 UI、旧按钮和现有远端实现均未改动；没有删除或移动旧流程。

### 验证

- `python -m pytest -q tests/test_publisher_release_batches.py`：9 项通过。
- 七个原有发布器专项测试加新增批次测试：全部通过（140 项）。
- 新增文件定向 `python -m ruff check ...`：通过。
- `python -m compileall -q src/signriver_publisher tests/test_publisher_release_batches.py`：通过。
- 未运行完整 pytest、全项目 Ruff、发布器构建、模块/更新包构建、GUI 人工验收或真实 GitLink/GitHub 测试。

### 当前状态与风险

- 当前分支仍为 `main`，HEAD 仍为 `a57c43c`；本轮未提交、未推送。
- 上一轮三个规划文档改动仍保留，并叠加本轮新增实现和测试。
- 新基础设施尚未接入 `PublisherApplication` 启动流程，因此不会自动扫描并恢复批次；这应在新发布中心接入时完成。
- 当前编排器是阶段 1 骨架，尚未表达“双源数据包全部核验后才切换清单”的具体程序流水线，也未适配暂停请求和 degraded 补齐动作；不得视为可替代现有正式发布流程。

### 下一窗口直接执行

1. 先运行 `project-context-switch`，核对本交接、未提交文件和新增测试。
2. 进入阶段 2：为程序版本定义明确阶段（收集/预检/确认、GitLink 包上传、GitHub 包上传、双源回读、GitLink 清单、GitHub 清单、最终回读），把“清单最后切换”编码为不可越过的阶段依赖。
3. 通过适配器复用现有 `updates.py`、`github.py`、`gitlink.py`，不要在新编排器中复制 HTTP/CLI 细节；先用 fake provider 写顺序、重试、已核验附件复用和 degraded 测试，再接真实实现。
4. 新路径达到测试对等并完成人工验收前，继续保留旧 UI 和旧发布入口。
5. 除非用户明确要求，不提交；任何提交后也不得自动推送。


## 2026-08-17：发布器重构本地闭环与阶段 6 阻塞交接

### 当前目标与结果

- 持续目标仍为 active：按 `docs/publisher-refactor-plan.md` 连续推进发布器流程化与模块化重构，不在阶段边界等待确认。
- 阶段 1～5 的本地代码与自动化闭环已完成；阶段 6 已完成当前不依赖真实远端和人工验收的安全结构收尾。
- 旧“构建与发布（兼容）”入口仍保留，因为真实双源演练、故障恢复演练和新旧 UI 对等验收尚未完成；不得宣称整体重构完成。

### 本轮改动范围

- `release_audit.py` 将高级维护改为授权、真实成功、真实失败三段生命周期；精确文本确认只记录 `maintenance_authorized`。
- `ui.py` 要求所有高级维护操作关联当前批次，并在真实 worker 回调中记录 `maintenance_completed` 或 `maintenance_failed`。
- 已覆盖远端单个/全部删除、采用远端附件、GitLink/GitHub 单源发布程序内容、程序更新、模块归档和卡带中心等高风险入口。
- 已审计暂停与恢复语义：安全暂停保留原授权并在继续后的最终回调完成；不可恢复失败消费授权并清除恢复上下文，重新发起必须重新确认。
- 已修正 `docs/publisher-refactor-plan.md` 的完成度表述，将长期授权策略写入 `docs/agent/DECISIONS.md`，并同步更新 `docs/publisher-guide.md` 与 `docs/program-update-release-guide.md` 的任务式导航和受控批次操作说明。
- 已新增 `docs/publisher-compatibility-map.md` 和 `docs/publisher-refactor-acceptance.md`，固化新旧入口能力映射、受控回退边界、真实三端双源发布、故障恢复和 UI 对等验收步骤。
- 已将发布中心、批次动作、Tk 运行时、验收中心、远端维护、公告编辑、卡带管理、本地内容管理和旧兼容发布控制流依次提取到 `release_center_ui.py`、`release_actions_ui.py`、`ui_runtime.py`、`acceptance_ui.py`、`remote_maintenance_ui.py`、`announcement_ui.py`、`cartridge_management_ui.py`、`content_management_ui.py` 与 `compatibility_publish_ui.py`。`PublisherApplication` 通过窄 mixin 接入，`ui.py` 已收敛为 463 行应用壳和共享小工具；旧兼容入口的行为与可见性仍保留。

### 验证

- `python -m pytest -q` 运行全部 `tests/test_publisher*.py`：168 项通过。
- `python -m ruff check` 定向检查本轮相关实现与测试：通过。
- `python -m compileall -q src/signriver_publisher tests`：通过。
- `git diff --check`：通过；仅有文档换行提示时不视为内容错误。
- 提取 `release_center_ui.py`、`release_actions_ui.py` 和 `ui_runtime.py` 后，定向运行 `tests/test_publisher_ui_threading.py`、`tests/test_publisher_release_service.py`、`tests/test_publisher_release_audit.py` 与 `tests/test_publisher_content_pipelines.py`：通过；相关 Ruff、`compileall` 与 `git diff --check`：通过。
- 继续提取 `acceptance_ui.py` 与 `remote_maintenance_ui.py` 后，定向运行 `tests/test_publisher_ui_threading.py` 和 `tests/test_publisher_acceptance.py`：38 项通过；相关 Ruff、`compileall`、继承方法解析检查与 `git diff --check`：通过。
- 继续提取 `announcement_ui.py`、`cartridge_management_ui.py`、`content_management_ui.py` 与 `compatibility_publish_ui.py` 后，修正 worker 源码检查以覆盖 `PublisherApplication.__mro__` 中全部项目 mixin；定向运行 `tests/test_publisher_ui_threading.py`、`tests/test_publisher_updates.py` 和 `tests/test_publisher_github.py`：43 项通过；相关 `compileall`、Ruff 与 `git diff --check`：通过。
- 最终模块拆分完成后重新运行全部 `tests/test_publisher*.py`：168 项通过；随后再次运行 `compileall`、全发布器源码/测试 Ruff 与 `git diff --check`：通过。
- 补齐程序包结构机器硬门禁：预检会打开三端 ZIP，校验根 `release-manifest.json`、schema、版本、`kind=full`、角色对应平台和 `x64` 架构；新增非 ZIP、非对象 manifest、内嵌平台错配负向测试。修复合法测试夹具后，全部 `tests/test_publisher*.py` 更新为 171 项通过，定向 Ruff、`compileall` 与 `git diff --check` 通过。
- 使用虚构非敏感双源目标对 `dist/updates` 中真实 `0.2.0` Windows、SteamOS、macOS 三端 ZIP 执行纯本地预检：收集到 3 个候选，所有硬门禁（含 `program.package_structure`）通过，状态为 `awaiting_confirmation`；未发起任何远端连接。
- 本轮未连接真实 GitLink/GitHub，未执行发布器 EXE 构建、真实发布、真实故障恢复或人工 GUI 验收。

### 当前真实外部阻塞

1. 本地已有并通过结构预检的 `0.2.0` Windows x64、SteamOS x64、macOS Intel x64 三端候选；仍需要真实 GitLink/GitHub 凭据与受控测试目标，完成一次双源发布演练。
2. 需要人工执行故障注入、发布器重启和安全恢复演练。
3. 需要人工完成新旧 UI 功能对等验收。
4. 上述前置条件未满足前，阶段 6 的旧入口删除和兼容适配器清理不得执行。

### Git 与下一步

- 当前分支 `main`，基线 HEAD 为 `a57c43ca5690ac4e4e304754a975ab34b029cb41`；所有发布器重构改动仍未提交、未推送。
- 不得重置、清理或覆盖现有未提交改动。
- 外部条件齐备后直接继续三项真实验收；通过后再分批删除旧入口、重复状态和兼容适配器，并运行对应回归。
- 除非用户明确要求，不执行 commit 或 push。


## 2026-08-17：发布器重构本地实现收敛交接

### 目标与本轮改动

- 连续收敛 `docs/publisher-refactor-plan.md` 中所有不依赖真实凭据和人工操作的阶段 1～6 工作，未删除兼容入口。
- 补强内容与 Hub/公告双源 provider 门禁：必须恰好为 `gitlink`、`github`，且映射键与 `source_id` 一致。
- 增加 `human.acceptance` 软预检与确认审计；未完整验收只显示警告、不阻止确认或执行，`release_confirmed` 记录验收结果、快照状态与 `acceptance_reference_only=True`。
- `ReleaseStore` 支持 schema 0 到 1 显式迁移并原子回写，未知 schema 继续拒绝；程序执行入口在生成准备产物前校验批次类型。
- 内容/Hub 的 `degraded` 恢复先核验主表，已匹配的源不重复切换，只补失败源。
- 三类批次只保存非敏感远端目标摘要；递归发现凭据类字段时拒绝创建，避免秘密进入持久化批次。

### 验证结果

- 全部 `tests/test_publisher*.py`：182 项通过。
- `python -m ruff check src/signriver_publisher tests`：通过。
- `python -m compileall -q src/signriver_publisher tests`：通过。
- `git diff --check`：通过；`docs/publisher-guide.md` 仅有既有 LF/CRLF 转换提示。
- `python tools/build_publisher.py --upx-dir C:\\Users\\32173\\AppData\\Local\\tools\\upx\\upx-5.0.2-win64`：成功；生成 `dist/publisher/SignRiver-Publisher.exe`，大小 172,508,671 字节，SHA-256 `D15458BEF01BB61483791A73CD4308D5886857571AEFA367AEFA865DE40557D1`。
- 构建日志中的不可压缩 DLL 与未使用 Intel MPI/SYCL 依赖为 PyInstaller/UPX 警告，构建最终正常完成。
- 未重复运行完整回归；最终仅做产物、文档差异和工作区状态核对。

### 外部阻塞与下一步

- 仍需真实 GitLink/GitHub 凭据和受控目标，完成三端双源发布演练。
- 仍需人工故障注入、发布器重启/恢复演练，以及新旧 UI 功能对等验收。
- 上述验收通过前不得删除“构建与发布（兼容）”入口或兼容 provider/adapter，不得宣称整体已正式发布验收完成。
- 当前分支 `main`，基线 HEAD `a57c43ca5690ac4e4e304754a975ab34b029cb41`；改动未提交、未推送。除非用户明确要求，不执行 commit 或 push。

## 2026-08-18：发布器流程化收尾（本地）

### 已完成

- 修复模块归档收件：程序批次扫描收件根目录及 `modules/` 子目录中的合法 `SignRiver-DLC-Hub-module-v<版本>.zip`，以归档内 `module.json` 的版本与入口校验为准；模块归档在专用 `modules` Release 完成 GitLink/GitHub 双源上传与回读后，程序更新清单才允许切换。
- 发布中心默认将三端收件目录指向 `publisher-workspace/updates`，并预填当前 `LAUNCHER_VERSION`；版本切换可载入、保存 `publisher-workspace/update-notes.json` 草稿，仍可手动调整目录。
- 增加“刷新收件目录”“读取远端基线（只读）”“导出基线 JSON”操作。基线读取不启动后台发布锁、不创建上传控制器；GitLink 基线保存 `display_size`，避免把仅展示用的附件大小伪装成字节数。
- 人工验收已明确调整为发布参考：未完整通过只产生警告，确认审计记录结果、快照附加状态和 `acceptance_reference_only=True`；验收快照变化仍会使预检与确认失效。
- 未连接真实 GitLink/GitHub，未读取或写入 `config/publisher.local.json`，未执行真实发布、commit、push、reset 或 clean。

### 本地验证（2026-08-18）

- `python -m pytest tests/test_publisher_release_batches.py tests/test_publisher_release_service.py tests/test_publisher_release_providers.py tests/test_publisher_content_pipelines.py tests/test_publisher_release_audit.py tests/test_publisher_ui_threading.py -q`：76 项通过。
- `python -m pytest tests/test_publisher_release_service.py tests/test_publisher_release_providers.py -q`：12 项通过。
- `python -m pytest -q`：全量通过。
- `python -m ruff check src/signriver_publisher tests`：通过。
- `python -m compileall -q src/signriver_publisher tests`：通过。
- `git diff --check`：通过；`docs/publisher-guide.md` 仅有既有 LF/CRLF 转换提示。
- 已将发布器体积回归固化为构建门禁：`tools/build_publisher.py` 显式排除未使用的 `numpy`（防止 Pillow 的可选依赖链带入 Conda 的 MKL/OpenMP 运行时）；先在 `build/publisher-artifact` 暂存构建，仅在产物通过检查后替换 `dist/publisher/SignRiver-Publisher.exe`。检查会拒绝超过 25 MiB 的 EXE，以及包含 NumPy、Intel MKL、OpenMP target 或 Microsoft MPI 标记的归档，避免异常包覆盖上一份可用产物。重新执行 `python tools/build_publisher.py --upx-dir C:\Users\32173\AppData\Local\tools\upx\upx-5.0.2-win64` 成功，产物大小 15,568,672 字节，SHA-256 `A2756E65A665D27FCC4846A9F431610512A0A11D7543EA53645DE890100B8C35`；`python -m ruff check tools/build_publisher.py` 与 `git diff --check` 通过（后者仅有既有 `docs/publisher-guide.md` LF/CRLF 提示）。

### 下一步与外部边界

1. 完成全量本地验证并重建发布器 EXE；不构建或上传客户端发布包。
2. 若进行测试仓库真实演练，必须先向用户给出版本、Release tag、文件名、SHA-256、大小和更新清单影响的完整清单，获得一次明确总确认后，才允许对 GitLink/GitHub 写入。
3. 完成真实双源、故障恢复和 UI 对等验收前，继续保留兼容入口及适配器。

## 2026-08-18：发布中心可用性修复（本地）

### 已完成

- “读取远端基线（只读）”现在会立即显示“读取中…”，完成后恢复按钮、刷新批次历史、明确弹出成功提示，并说明该操作未上传或改动远端；失败也会恢复按钮并显示错误。
- “导出基线 JSON”现在自动预填 `signriver-remote-baseline-v<版本>.json`，不再要求操作员先自行构思文件名。
- 相同程序版本与同一收件目录的未执行批次会被自动打开，不会因反复点击创建按钮产生重复批次；需要重新开始时可显式使用“归档 / 移除草稿”。
- “归档 / 移除草稿”仅允许处理尚未执行的草稿、预检失败或待确认批次；实际文件移入本地 `_archived`，保留审计记录，不做不可恢复删除。已有执行记录的批次继续保留，用于恢复与追溯。
- 批次历史改为“目标｜类型｜中文状态｜更新时间”；批次看板改为面向操作员的发布说明、下一步、收件文件、更新说明、远端基线、预检结果、执行进度。批次 ID 仅保留为支持与排障信息。

### 本轮验证（2026-08-18）

- `python -m pytest tests/test_publisher_release_batches.py tests/test_publisher_ui_threading.py -q`：54 项通过。
- `python -m ruff check src/signriver_publisher/release_center.py src/signriver_publisher/release_center_ui.py src/signriver_publisher/release_service.py src/signriver_publisher/release_store.py tests/test_publisher_release_batches.py tests/test_publisher_ui_threading.py`：通过。
- `python -m compileall -q src/signriver_publisher`：通过。
- `git diff --check`：通过；仅仍有既有 `docs/publisher-guide.md` 的 LF/CRLF 提示。

### 未执行

- 已重建 `dist/publisher/SignRiver-Publisher.exe`；构建门禁通过，产物为 15,576,048 字节，SHA-256 `3D2704B277A5C63C932D6FC110A96DF686E38B0BCEE7733F2E0E76D5599DE878`。尚未进行人工 GUI 验收。
- 未读取或写入 `config/publisher.local.json`，未连接 GitLink/GitHub，未执行真实发布、commit、push、reset 或 clean。

## 2026-08-18：发布器启动回归修复（本地）

### 已修复

- 修复验收中心路径摘要的实例方法签名：`_acceptance_display_path` 先前遗漏 `self`，定时刷新把 `WindowsPath` 误传入长度参数，导致 `TypeError: '<=' not supported between instances of 'int' and 'WindowsPath'`。现已恢复正确实例方法签名。
- 修复发布中心批次历史按钮：当前 CustomTkinter 的 `CTkButton` 不支持 `justify` 参数，初始化时会抛出 `ValueError`；保留左侧锚定，移除不兼容参数。
- 修复构建日志 SHA-256 与实际 EXE 不一致：运行时标记检测仍使用小写副本，但摘要改为原始字节计算；复制到 `dist/publisher` 后会再次验证大小、禁止运行时标记及 SHA-256 一致性，复制异常会停止构建。

### 本轮验证（2026-08-18）

- `.\.venv\Scripts\python.exe -m pytest tests\test_publisher_acceptance.py tests\test_publisher_release_batches.py tests\test_publisher_ui_threading.py -q`：69 项通过。
- `.\.venv\Scripts\python.exe -m ruff check src\signriver_publisher\acceptance_ui.py src\signriver_publisher\release_center.py tests\test_publisher_acceptance.py tests\test_publisher_ui_threading.py`：通过。
- `.\.venv\Scripts\python.exe -m compileall -q src\signriver_publisher`：通过。
- 构建工具 SHA-256 原始字节校验脚本、`ruff` 与 `compileall`：通过。
- `python tools\build_publisher.py --upx-dir C:\Users\32173\AppData\Local\tools\upx\upx-5.0.2-win64`：成功；最终 `dist/publisher/SignRiver-Publisher.exe` 为 15,451,413 字节，SHA-256 `A8C44017379312EAB8F53D639A138EC5009337652C763285DBC0FA2516763D62`，通过 25 MiB 体积及禁止运行时门禁。
- `git diff --check`：通过；仅有既有 `docs/publisher-guide.md` LF/CRLF 提示。

### 外部边界与下一步

- 未读取或写入 `config/publisher.local.json`，未连接 GitLink/GitHub，未执行真实发布、commit、push、reset 或 clean。
- 请从 `dist/publisher/SignRiver-Publisher.exe` 启动新版发布器验证界面；源码启动命令 `./.venv/Scripts/python.exe publisher.py` 也应不再出现上述两种异常。

## 2026-08-18：发布中心专项页导航与信息密度重排

### 已完成

- `src/signriver_publisher/release_center.py` 已从单页堆叠布局改为“发布中心主页 + 页面内覆盖式专项页”。切换通过同一容器的 `grid_remove()` / `grid()` 完成，不会打开新窗口；所有专项页均提供“← 返回发布中心”。
- 主页面仅保留当前批次摘要、创建/打开本次批次和六个清晰入口：收件与准备、批次历史、远端基线、预检与确认、执行与恢复、操作顺序说明；避免把大量操作按钮挤在同一行。
- “收件与准备”独立显示版本、默认三端收件目录（仍可手动选择）、150px 高的更新说明编辑区、草稿保存、刷新收件目录和三端包替换操作，修复原更新说明区域过窄、内容易被截断的问题。
- 点击批次历史项后会进入“批次历史与看板”专项页；历史列表与详情改为约 2:5 的横向空间比例，右侧看板有更大的阅读空间，不再在主页固定挤占两列。
- 远端基线、预检冻结、执行恢复分别移入专项页；现有批次状态、基线说明、预检结果、执行阶段、归档和安全暂停语义均保留。人工验收仍只是参考提醒，不作为冻结或执行阻塞条件。
- 已在 `tests/test_publisher_ui_threading.py` 增加页面容器、专项页创建、覆盖式切换、批次选择跳转及更新说明编辑高度的源码级回归断言。

### 验证（2026-08-18）

- `python -m pytest tests/test_publisher_release_batches.py tests/test_publisher_ui_threading.py -q`：55 项通过。
- `python -m pytest tests/test_publisher_acceptance.py -q`：15 项通过。
- 首次组合运行时，`test_patch_test_environment_can_be_previewed_applied_and_restored` 在验收基线临时目录 `os.replace` 处遇到 Windows `PermissionError`；未改动该逻辑，随后单独复跑该文件通过，判定为测试临时目录的瞬态文件占用。
- `python -m py_compile src/signriver_publisher/release_center.py`：通过。
- `git diff --check`：通过。
- 未启动 GUI 做人工视觉验收，未构建发布器 EXE，未连接真实 GitLink/GitHub，未读取或写入 `config/publisher.local.json`，未执行真实发布、commit、push、reset 或 clean。

### 人工验收重点与下一步

1. 启动源码发布器，进入“发布中心”，检查主页面在当前窗口宽度下不再出现中部按钮截断。
2. 进入“收件与准备”，确认更新说明可完整阅读和编辑、默认收件目录正确、返回主页后流程无中断。
3. 从“批次历史”选择一个批次，确认进入专项看板，左右空间明显偏向详情；使用返回按钮回主页。
4. 分别打开远端基线、预检与确认、执行与恢复，确认无新窗口且各自状态摘要正确。
5. UI 人工验收通过后，如后续还要优化文字密度或卡片尺寸，仅调整 `release_center.py` 的视图层，不回退既有服务层和批次语义。

## 2026-08-18：发布中心布局稳定性与关闭体验修复（本地）

### 已完成

- 发布中心主页、专项入口、返回入口及批次历史条目均扩大了点击热区和字号；主要入口高度为 40–44 px，批次历史条目提高到 66 px。
- “批次历史与看板”改为固定 360 px 的左侧历史栏，右侧看板独占剩余宽度；历史卡片禁止由内部控件反向传播尺寸，因此选择前后或切换不同批次时不再因长文本改变左右栏比例。
- 正常退出在全部退出保护检查通过后，先标记关闭、立即隐藏根窗口，再停止 UI 事件泵并销毁控件；后台线程在关闭期无法继续投递界面回调或进度，避免关闭瞬间暴露 CustomTkinter 的中间重绘布局。
- 未读取或写入 `config/publisher.local.json`，未连接真实 GitLink/GitHub，未执行真实发布、构建 EXE、commit、push、reset 或 clean。

### 本地验证（2026-08-18）

- `.\.venv\Scripts\python.exe -m py_compile src\signriver_publisher\release_center.py src\signriver_publisher\ui.py src\signriver_publisher\ui_runtime.py`：通过。
- `.\.venv\Scripts\python.exe -m pytest tests\test_publisher_ui_threading.py -q`：34 项通过。
- `git diff --check`：通过；仅出现既有文档的 LF/CRLF 工作树提示。
- 未启动 GUI 做人工视觉复验；需要下次启动源码发布器后重点确认 1240×800 及最小窗口宽度下的固定侧栏、放大按钮与正常关闭观感。

## 2026-08-18：发布中心首页入口与批次管理可见性微调

### 已完成

- 首页五个蓝色专项入口统一放大为 `270 × 52 px`，字号提升至 16 px；保留右侧对齐与卡片留白，使其在宽屏页面上更易点击和辨识。
- “批次历史与看板”右上角固定提供“归档 / 移除当前草稿”，下方看板内容可独立滚动，避免长更新说明遮蔽管理入口。

### 本地验证（2026-08-18）

- `./.venv/Scripts/python.exe -m py_compile src/signriver_publisher/release_center.py`：通过。
- `./.venv/Scripts/python.exe -m pytest tests/test_publisher_ui_threading.py -q`：34 项通过。
- `git diff --check`：通过；仅有既有 `docs/publisher-guide.md` LF/CRLF 提示。
- 未构建 EXE、未启动 GUI 做人工视觉复验，未读取或写入本地发布凭据，未执行真实发布、commit、push、reset 或 clean。

## 2026-08-18：归档后保留批次看板

- 归档 / 移除草稿成功后，不再跳回发布中心主页；页面保持在“批次历史与看板”，右侧显示空状态提示，操作员可立即选择其他批次或继续创建新批次。
- 验证：`./.venv/Scripts/python.exe -m py_compile src/signriver_publisher/release_center.py`、`./.venv/Scripts/python.exe -m pytest tests/test_publisher_ui_threading.py -q`（35 项通过）及 `git diff --check` 均通过；未构建 EXE、未进行真实发布、commit 或 push。

## 2026-08-18：目录选择器沿用当前收件目录

- “选择目录”按钮现在会读取界面中当前的“三端包收件目录”路径，并将其作为文件夹选择器的 `initialdir`；如果当前路径不存在，则回退到配置的默认收件目录。
- 验证：发布中心 UI 测试 36 项通过，源码编译与 `git diff --check` 通过；未构建 EXE、未执行真实发布、commit 或 push。

## 2026-08-18：准备发布器三端候选包

### 已完成

- 已确认当前 `0.2.0` 三端全量更新包存在于 `dist/updates/`，无需重新构建或连接虚拟机。
- 已将三个包复制到发布器当前默认“三端包收件目录” `publisher-workspace/output/updates/`：
  - `SignRiver-DLC-Hub-full-v0.2.0-windows-x64.zip`
  - `SignRiver-DLC-Hub-full-v0.2.0-steamos-x64.zip`
  - `SignRiver-DLC-Hub-full-v0.2.0-macos-x64.zip`
- 三个 ZIP 已完成完整性检查、`release-manifest.json` 检查和三端产物识别检查；版本均为 `0.2.0`，架构均为 `x64`。
- 已记录包大小与 SHA-256：Windows `18,791,906` 字节 / `16683e3e80cf75ff287b5194d3c32ddeeb0105e2c357169e10cf94b6a5f554bc`；SteamOS `35,508,372` 字节 / `91bb1fd54d452b34bae521ccd6e1830317547a51d8c276cfc3da45d9bfef1c6e`；macOS `21,596,182` 字节 / `95c81026a782297e9dfe0e2f081ed83aed5dcc22dbe454bc5fdebaab4820fad3`。

### 验证与边界

- `tests/test_publisher_ui_threading.py`：36 项通过。
- `py_compile` 与 `git diff --check`：通过；后者仅保留项目已有文档换行提示。
- 未读取或写入 `config/publisher.local.json`，未连接真实 GitLink/GitHub，未执行真实发布、commit、push、reset 或 clean。

### 下一步

- 重新打开或刷新发布器的“收件与准备”，确认三端包被识别后再进行人工发布流程。
- 若只是继续本地界面验收，无需重新构建 EXE；若要给用户使用，再按项目规则构建发布器 EXE。

## 2026-08-18：发布器页面分块信息架构研究（未实施）

- 根据当前发布中心截图、现有七个顶层页签、兼容能力映射和批次流程，已新增 `docs/publisher-information-architecture.md`。
- 文档确认当前问题是“业务对象、发布阶段和风险等级”在同一层混排；建议后续以“发布工作台、内容准备、核对与验收、执行与恢复、高级维护”五个任务/风险工作区重组。
- 明确批次历史、远端基线、预检确认和执行恢复应属于同一批次连续流程；人工验收仅作为参考并可附加到批次，不得成为发布硬门禁；兼容单源和远端删除等动作应沉入高级维护。
- 本次未修改 `src/signriver_publisher/` 代码、未移动/删除现有功能、未构建、未运行 GUI 或远端发布；后续需先由用户确认分块方案再实施。

## 2026-08-18：发布器任务型信息架构已实施（未构建 EXE）

### 已完成

- 发布器顶层导航已从按历史功能拆分的七个页签，收敛为五个工作区：`发布工作台`、`内容准备`、`核对与验收`、`执行与恢复`、`高级维护`。
- `内容准备`以内嵌页签保留原有“本地资源 / 游戏内容 / 卡带与 Hub”能力；`高级维护`以内嵌页签保留“兼容发布（回退 / 修复）/ 远端维护”。没有删除底层功能或改变发布服务逻辑。
- `核对与验收`将远端基线、预检确认与人工验收归于同一工作区，并明确人工验收仅供参考、可附加到批次、不会阻塞发布。
- `执行与恢复`提供清晰的当前批次执行入口；实际执行面板仍复用发布工作台中的覆盖式子页面，不会打开新窗口。
- 发布工作台首页已移除原先六张彼此割裂的等权卡片，改为“当前任务 + 同一批次操作顺序（准备、核对、确认、执行、回读）+ 批次历史”结构。
- 兼容发布页已明确标记为“回退 / 修复”用途，并增加不得与同一批次标准流程并行执行的提示；其“打开卡带管理”入口已适配新的内容准备工作区。

### 验证与边界

- 已执行 `./.venv/Scripts/python.exe -m py_compile src/signriver_publisher/ui.py src/signriver_publisher/release_center.py src/signriver_publisher/compatibility_publish_ui.py`：通过。
- 已执行 `./.venv/Scripts/python.exe -m pytest tests/test_publisher_ui_threading.py tests/test_publisher_acceptance.py -q`：51 项通过。
- 已执行 `git diff --check`：通过；仅显示项目已有文档 CRLF 转换提示。
- 未读取、展示或修改 `config/publisher.local.json`；未连接远端、未进行真实发布、未构建 EXE、未进行 GUI 人工视觉验收、未 commit 或 push。

### 后续

- 下次可直接启动源码发布器进行一次人工界面验收，重点观察五个顶层入口在实际窗口宽度下的可读性，以及“核对与验收 / 执行与恢复”跳转后是否符合操作习惯。
- 若确认视觉与流程无误，再按需要构建发布器 EXE；构建前无需重新生成已准备好的 0.2.0 三端候选包。

## 2026-08-18：发布器执行进度与安全暂停可用性修复（未构建 EXE）

### 已完成

- `ReleaseCenter` 在“执行 / 恢复”启动后每 450ms 读取已落盘的当前批次状态并刷新执行页；运行中会显示“当前正在执行：第 x/y 步 <阶段名称>”及每一步的完成状态，不再等到整批任务结束才更新界面。
- “安全暂停”在后台任务真正进入 `RUNNING` 状态后自动可用；点击后立即改为“已请求安全暂停…”，并明确提示会在下一个安全检查点暂停，避免用户误以为必须强制结束程序。
- 执行完成、失败或关闭执行回调时会停止轮询并恢复“执行 / 恢复”按钮，避免遗留定时刷新。
- 增补了发布中心执行轮询、运行中暂停可用、暂停请求提示和租约启动失败恢复按钮的最小测试覆盖。

### 验证与边界

- 已执行 `./.venv/Scripts/python.exe -m py_compile src/signriver_publisher/release_center.py`：通过。
- 已执行 `./.venv/Scripts/python.exe -m pytest tests/test_publisher_ui_threading.py tests/test_publisher_acceptance.py -q`：54 项通过。
- 已执行 `git diff --check`：通过；仅有既有文档的 LF/CRLF 提示。
- 未读取、展示或修改 `config/publisher.local.json`；未连接远端、未进行真实发布、未构建 EXE、未 commit 或 push。

### 下一步

- 重新启动源码发布器，在一个已确认的批次上做人工界面验收：确认任务进入“正在发布”后安全暂停可点击、阶段文本持续刷新；不要用真实远端发布来验证。
- “读取远端基线”详情展开仍是独立可用性事项：后端已有结果，但当前卡片只显示读取时间和来源，后续可按 GitHub/GitLink 分别展示 Release、标签、附件数量和更新清单结论。

## 2026-08-18：发布目标可见性与冻结执行整改（未执行远端操作）

### 事故结论与边界

- 操作员原意是向测试仓库进行 `0.2.0` 演练：GitLink `signriver/signriver-test`、GitHub `sign-river/SignRiver-Test`；但操作员已发现测试 GitHub 仓库未出现预期 Release，而 `0.2.0` 三端更新包及 `update-manifest.json` 已误进入正式资产 Release。该既有远端副作用不在本轮自动删除、回滚或补发范围内。
- 本轮未读取、展示或修改 `config/publisher.local.json` 的凭据内容；未连接 GitLink/GitHub，未验证令牌身份、未写入远端、未构建 EXE、未 commit 或 push。

### 已完成

- 新增顶层“账号与发布目标（发布前必看）”页，同时列出 GitLink 与 GitHub 的配置所有者、精确目标仓库、仓库 URL 和凭据是否已配置；令牌始终隐藏。页面明确提示：配置的所有者不是远端令牌身份验证结果。
- 发布工作台主页在尚未创建批次时显示“下次创建批次将使用的发布目标”；批次看板和确认弹窗显示“本批次实际发布目标（创建时已冻结）”，并逐端写出 `owner/repository`，不再只显示笼统的“双源发布”。
- 修复严重目标漂移：执行发布时，GitLink/GitHub provider 只读取 `plan.remote_targets` 中创建批次时冻结的 owner/repository；不会因之后修改本地配置而转投别的仓库。旧批次如缺少完整冻结目标，会拒绝执行并要求重新创建批次；token 仅从当前内存设置取得，不写入批次。

### 验证（2026-08-18）

- `./.venv/Scripts/python.exe -m py_compile src/signriver_publisher/ui.py src/signriver_publisher/release_center.py src/signriver_publisher/release_center_ui.py src/signriver_publisher/publisher_targets_ui.py`：通过。
- `./.venv/Scripts/python.exe -m pytest tests/test_publisher_ui_threading.py tests/test_publisher_acceptance.py -q`：57 项通过。
- `git diff --check`：通过；仅有既有文档 LF/CRLF 提示。

### 下一步

1. 仅启动源码发布器做人工 UI 验收：核对“账号与发布目标”页、主页和批次看板展示的两端仓库是否与当前测试意图一致；不得执行发布。
2. 用户明确核对每个目标仓库、将上传的文件和是否允许远端写入后，才可创建新的测试批次并发布。任何远端删除、正式库回滚或补发，都必须获得单独且明确的授权。

## 2026-08-18：执行页显示单文件上传进度与实时速度

### 已完成

- “执行与恢复”页新增当前文件的上传状态区：显示正在写入的源站（GitLink / GitHub）、该批次创建时冻结的 `owner/repository`、当前文件名、已传输字节、百分比及实时速度。
- 上传结束而批次仍在运行时，界面明确显示“上传已提交，正在远端回读校验…”，不把 SHA-256 / 清单回读校验误显示为上传进度。
- GitHub 与 GitLink provider 均将既有的字节回调上报给发布服务；服务层以同一个编排中的 `ReleasePlan` 实例持久化节流后的状态，避免回调重新加载批次并覆盖编排状态。
- 进度数据只记录源站、文件名、已传输字节、总字节、速度与更新时间；不记录 URL、令牌或任何发布凭据。

### 本地验证

- `./.venv/Scripts/python.exe -m py_compile src/signriver_publisher/remote_release_providers.py src/signriver_publisher/release_service.py src/signriver_publisher/release_center.py tests/test_publisher_release_providers.py tests/test_publisher_release_service.py`：通过。
- `./.venv/Scripts/python.exe -m pytest tests/test_publisher_release_providers.py tests/test_publisher_release_service.py tests/test_publisher_ui_threading.py -q`：56 项通过。
- `git diff --check`：通过；仅保留既有文档 LF/CRLF 提示。
- 未构建 EXE、未启动 GUI、未读取或写入 `config/publisher.local.json`，未连接 GitLink/GitHub，未执行真实发布、commit、push、reset 或 clean。

## 2026-08-18：移除发布工作台重复的批次历史入口

- 发布工作台首页已移除底部“查看批次历史”提示卡与按钮；批次看板仍由创建 / 打开批次后的既有流程进入，避免首页再提供同一目的地的重复入口。
- 验证：`./.venv/Scripts/python.exe -m py_compile src/signriver_publisher/release_center.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_publisher_ui_threading.py -q` 42 项通过；`git diff --check` 通过（仅保留既有文档 LF/CRLF 提示）。未构建 EXE、未启动 GUI、未执行真实发布、commit 或 push。

## 2026-08-18：DLC / 补丁发布统一批次流水线

### 已完成

- 将常规 DLC、补丁与 AppInfo 的远端发布入口收敛到“发布工作台”的 `GAME_CONTENT` 批次：创建批次时由当前已选游戏的已构建输出自动收集文件，不再要求人工分别选择附件和 `catalog.json`。
- 创建内容批次前调用 `workspace.publish_files(profile)` 校验本地构建并生成最终 `catalog.json`；批次将附件先上传并回读校验，最后才切换 `catalog.json`，沿用双源、进度、速度、安全暂停、恢复、远端基线、预检、冻结和归档能力。
- 发布工作台主页增加“DLC / 补丁发布”入口；内容准备页的入口改为“进入 DLC / 补丁发布流水线”，本地输出列表不再提供逐文件直接上传作为常规路径。
- 兼容发布页的“发布当前游戏”常规入口改为跳转统一内容批次；底层兼容修复能力保留给高级维护，不作为日常上传流程。
- 内容批次按游戏 ID、Release 标签和本地输出目录复用未执行批次（草稿、预检失败、待确认），避免用户重复点击产生大量同一构建的批次；批次记录冻结的输出目录、附件数量和 `catalog.json` 名称，便于看板追溯。

### 验证（2026-08-18）

- `./.venv/Scripts/python.exe -m py_compile src/signriver_publisher/release_service.py src/signriver_publisher/release_center.py src/signriver_publisher/release_center_ui.py src/signriver_publisher/release_actions_ui.py src/signriver_publisher/content_management_ui.py src/signriver_publisher/compatibility_publish_ui.py tests/test_publisher_release_service.py tests/test_ui_theme.py`：通过。
- `./.venv/Scripts/python.exe -m pytest tests/test_publisher_content_pipelines.py tests/test_publisher_release_service.py tests/test_publisher_ui_threading.py tests/test_ui_theme.py -q`：109 项通过。
- `git diff --check`：通过；仅仍有既有 `docs/publisher-guide.md` 的 LF/CRLF 提示。

### 外部边界与后续验收

- 本轮未读取或写入本地凭据，未连接 GitLink/GitHub，未执行真实发布、构建 EXE、commit、push、reset 或 clean。
- 后续人工验收只需选择一个已构建游戏，依次从“内容准备”“发布工作台主页”和“兼容发布”三个入口进入，均应打开同一个未执行内容批次，且不应再弹出附件或 `catalog.json` 文件选择框；真实双源执行需用户另行明确授权。

## 2026-08-18：账号与发布目标改为独立工作区

### 已完成

- 顶层“账号与发布目标”现在是独立工作区，不再作为跳转到“高级维护”的只读入口。
- 本页集中展示 GitLink、GitHub 的实际 `owner/repository`、仓库地址与凭据是否已配置；不会显示、读取或记录令牌内容。
- 本页可分别保存 GitLink、GitHub 的所有者和仓库名；保存坐标时保留原有令牌。修改只影响后续新建批次，已有批次继续使用创建时冻结的目标。
- “高级维护”仍只承担兼容发布和低频远端维护，不再承担日常账号配置入口。

### 验证（2026-08-18）

- `./.venv/Scripts/python.exe -m py_compile src/signriver_publisher/publisher_targets_ui.py tests/test_publisher_ui_threading.py`：通过。
- `./.venv/Scripts/python.exe -m pytest tests/test_publisher_ui_threading.py tests/test_ui_theme.py -q`：90 项通过。
- 本轮未构建 EXE、未启动 GUI、未读取或写入 `config/publisher.local.json` 中的凭据内容，未连接 GitLink/GitHub，未执行真实发布、commit、push、reset 或 clean。

## 2026-08-18：顶层“核对与验收”调整为最后一个入口

### 已完成

- 发布器顶层工作区顺序现为：`发布工作台`、`内容准备`、`执行与恢复`、`账号与发布目标`、`高级维护`、`核对与验收`。
- “核对与验收”的人工验收（参考）与公告能力未删减，也不改变其“不阻塞发布”的边界；仅调整入口位置，使低频核对动作位于日常发布与维护操作之后。
- 模块化 UI 壳补回安全关闭实现：只有实际登记的后台写操作才会阻止退出；遗留的暂停控制对象不再被误判为上传仍在执行。关闭时先隐藏窗口，再停止 UI 事件泵并销毁窗口，避免退出瞬间暴露控件重排。
- 滚动列表的重置辅助函数归入 `ui_runtime.py`，与模块化 UI mixin 共用；对应测试改为读取组成发布器界面的模块源码，而不是假设全部实现仍在 `ui.py` 单文件中。

### 验证（2026-08-18）

- `./.venv/Scripts/python.exe -m py_compile src/signriver_publisher/ui.py src/signriver_publisher/ui_runtime.py src/signriver_publisher/legacy_ui.py tests/test_publisher_ui_threading.py tests/test_ui_theme.py`：通过。
- `./.venv/Scripts/python.exe -m pytest tests/test_publisher_ui_threading.py tests/test_ui_theme.py -q`：90 项通过。
- 未启动 GUI、未构建 EXE、未读取或写入 `config/publisher.local.json`、未连接 GitLink/GitHub，未执行真实发布、commit、push、reset 或 clean。

### 后续

- 如需继续，可仅启动源码发布器做一次人工视觉验收，确认六个顶层入口在目标窗口宽度下均可读；不需要再改动发布流程本身。

## 2026-08-18：移除重复的“执行与恢复”顶层页

- “执行与恢复”不再作为顶层标签；批次执行、进度、上传速度、安全暂停与恢复统一保留在“发布工作台”的现有执行面板中。
- 顶层顺序现为：`发布工作台`、`内容准备`、`账号与发布目标`、`高级维护`、`核对与验收`。
- 批次状态文案改为指向“发布工作台的执行面板”，不再提示前往一个不存在的独立页。

## 2026-08-18：远端核对并入批次看板（未执行远端操作）

### 已完成

- 删除发布工作台内独立的“远端基线”覆盖页与其工作流跳转；流程第 ② 步现直接进入“批次历史与看板”。
- 在批次看板右侧新增固定的“远端核对（只读）”卡片：选中批次后可原地读取远端基线、查看读取状态与来源，并在已有基线时导出 JSON。
- 未选择批次时两个核对按钮保持禁用；选中批次后才允许读取，导出按钮仅在已保存基线时可用。
- 读取完成后的回调继续原地刷新当前批次看板与左侧历史，不再要求操作员切换到额外页面；读取操作仍明确为不上传、不修改远端。
- 批次历史左栏的固定宽度和看板详情列布局未变，避免恢复此前按批次切换时的横向比例抖动。

### 验证（2026-08-18）

- `./.venv/Scripts/python.exe -m py_compile src/signriver_publisher/release_center.py src/signriver_publisher/release_center_ui.py tests/test_publisher_ui_threading.py tests/test_ui_theme.py`：通过。
- `./.venv/Scripts/python.exe -m pytest tests/test_publisher_ui_threading.py tests/test_ui_theme.py -q`：90 项通过。
- `git diff --check`：通过；仅有既有 `docs/publisher-guide.md` 的 LF/CRLF 提示。
- 未启动 GUI、未构建 EXE、未读取或修改 `config/publisher.local.json`、未连接 GitLink/GitHub，未执行真实读取、发布、删除、回滚、commit 或 push。

### 下一步

- 如需人工验收，仅启动源码发布器：选中一个已有批次，确认“远端核对（只读）”在批次看板内显示、无批次时按钮禁用、已有基线后导出按钮可用；不需要执行真实远端读取。

## 2026-08-18：游戏选择收敛至 DLC / 补丁发布包页面

### 已完成

- 移除当前发布器顶层界面对游戏选择器的依赖：游戏选择器现仅在“内容准备 → DLC / 补丁发布”子页面显示，不再作为所有发布器功能的顶层开关。
- 新增游戏作用域明确的“DLC / 补丁发布包”页：选择当前游戏后会说明新批次将冻结游戏、Release 标签与双源目标；页面同时显示当前游戏的 `catalog.json` / 附件准备状态。
- “发布工作台 → DLC / 补丁发布”以及旧的内容发布入口均改为先打开上述发布包页；操作员确认当前游戏与发布包状态后，再点击“创建 / 打开本游戏发布批次”。
- 既有批次仍使用创建时冻结的目标；切换当前游戏只影响未来创建或复用的内容批次。
- 修正从内容发布包页打开批次时的顶层页名称，使其回到实际存在的“发布工作台”。

### 验证（2026-08-18）

- `./.venv/Scripts/python.exe -m py_compile src/signriver_publisher/ui.py src/signriver_publisher/content_management_ui.py src/signriver_publisher/release_actions_ui.py src/signriver_publisher/release_center.py src/signriver_publisher/release_center_ui.py tests/test_publisher_ui_threading.py tests/test_ui_theme.py`：通过。
- `./.venv/Scripts/python.exe -m pytest tests/test_publisher_ui_threading.py tests/test_ui_theme.py -q`：90 项通过。
- `git diff --check`：通过；仅保留既有文档 LF/CRLF 提示。
- 未启动 GUI、未构建 EXE、未读取或修改 `config/publisher.local.json`，未连接 GitLink/GitHub，未执行真实读取、发布、删除、回滚、commit 或 push。

### 后续人工验收

- 启动源码发布器后确认顶部标题栏无游戏下拉框；从“发布工作台 → DLC / 补丁发布”进入“内容准备 → DLC / 补丁发布”，确认可先选择游戏、查看本地包状态，再创建或打开批次。
# 当前目标（2026-08-20）

已开始 Windows 确定性补丁部署迁移：发布器输出改为 `unlocker.dll` / `original.dll`，客户端目录解析与下载任务增加原生库角色，0.1.0 引擎主路径使用发布的原生库，不再推断用户 DLL。发布器内容批次增加远端多余附件检测与二次确认后的镜像删除，catalog 仍最后发布。

验证已通过：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_publisher_workspace.py tests/test_dlc_catalog.py tests/test_client_problem_center.py tests/test_cartridge_catalog.py tests/test_publisher_release_service.py tests/test_publisher_release_providers.py -q
```

结果：117 项通过。`git diff --check` 仍只报既有 `src/signriver_publisher/ui.py:155` 文件末尾空行；未修改该文件。未构建、未真实发布、未 commit 或 push。

## 2026-08-20：客户端缓存管理存储概览

- 设置页“缓存管理”改为展示总缓存用量、当前游戏缓存、其他游戏缓存及容量比例条；用量继续在后台线程统计，不会阻塞 Tk 界面。
- 操作顺序调整为“清理当前游戏 → 打开目录 → 清理全部缓存”，其中全量清理保留危险操作样式。
- 已同步到运行中的 `app/versions/0.2.0/app_entry.py`；未启动 GUI 进行人工视觉验收。

验证：

```powershell
.\.venv\Scripts\python.exe -m py_compile app\versions\0.1.0\app_entry.py app\versions\0.2.0\app_entry.py
.\.venv\Scripts\python.exe -m pytest tests\test_ui_theme.py tests\test_ui_units_mandatory.py tests\test_dlc_catalog.py -q
```

结果：65 项通过。未构建、未执行真实缓存清理、未 commit 或 push。

## 2026-08-20：下载源下拉框视觉优化

- “下载源”选择器改为白色统一表面，取消独立蓝色箭头区；悬停时仅以蓝色边框与浅蓝箭头区提示可操作。
- 该样式仅用于下载源设置，不影响游戏、筛选等仍需醒目状态的其他下拉框。

验证：`python -m py_compile`（0.1.0 与 0.2.0）及 `tests/test_ui_theme.py`，49 项通过；未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：游戏选择框未同步的运行版本修复

- 已定位根因：`app/versions/0.2.0/app_entry.py` 的 `_apply_selected_cartridge()` 在切换时更新了内部 `selected_game_name`、游戏路径和目录，却遗漏 `_set_game_selector_text(display_name)`；因此实际游戏已切换，但可见组合框保留旧的群星名称。
- 运行版本已补齐该同步；选择器在异步加载完成后恢复为只读状态，避免被当作普通可编辑输入框。
- `tests/test_ui_theme.py` 新增回归断言，确保基线的卡带应用逻辑必须同步可见选择器。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，62 项通过；`git diff --check` 通过（仅有既有 LF/CRLF 提示）。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：隐藏游戏加载的内部术语

- 所有面向用户的“卡带”文案调整为“游戏支持数据”，包括加载中、成功提示、失败状态和启动错误；内部类型与目录名保持不变。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，62 项通过；未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：DLC 首页操作区收敛

- 已提交上一轮待提交内容：`7a8de1b feat: add deterministic patch deployment and UI refinements`，未推送。
- DLC 首页移除搜索与状态筛选；二者移入“逐项管理 DLC”。首页保留“全选”、唯一主操作“一键解锁”及可展开的“更多操作”，后者收纳取消下载、移除补丁、移除本程序安装内容和一键修复。
- 顶部反馈入口文案改为“资源有遗漏？反馈更新 →”。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，62 项通过；未启动 GUI、未构建或推送。

## 2026-08-20：恢复下载源选择器原生样式

- 下载源下拉框已恢复原有的 CustomTkinter 组合框样式；此前为扁平化而重绑内部 canvas 的逻辑已完全移除，避免边框异常。

验证：`python -m py_compile`（0.1.0 与 0.2.0）及 `tests/test_ui_theme.py`，49 项通过；未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：补足 DLC 首页主操作区

- 将原先位于标题行右侧的“逐项管理 DLC”和“刷新目录”移入 DLC 首页操作栏；同栏依次提供逐项管理、刷新、全选、取消全部下载和“更多操作”。
- “取消全部下载”从折叠菜单提升为可见危险操作；“更多操作”只保留一键移除补丁、移除本程序安装内容和一键修复。
- “一键解锁”仍固定在操作栏右侧，继续作为唯一大号主操作，避免操作层级混乱。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，62 项通过；`git diff --check` 通过。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：DLC 首页可用性状态与工具栏压缩

- “全选”改为“全选 DLC”，在全部可选项已选中时仍显示“取消全选”。
- “取消全部下载”根据下载队列是否有可取消任务自动启用；空闲时禁用，避免让用户误以为当前有任务。
- 缺少补丁资产时，一键解锁按钮显示“补丁资源缺失”并禁用；资源说明行以橙色强调“补丁资源缺失，暂无法一键解锁”。
- 将首页工具栏的上下留白和主按钮高度压缩，保留原有操作层级。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，62 项通过；`git diff --check` 通过。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：游戏选择器当前项单行化

- 游戏选择弹层的当前项状态由第二行“✓ 当前选择”改为紧跟在游戏名后的单行标记，避免选中条目额外增高。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，62 项通过；`git diff --check` 通过。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：游戏检测行移除重复游戏名

- 游戏名称已由左侧选择器表达；完成路径验证后，右侧状态仅显示“版本 <版本号>”，无版本数据时显示“路径已验证”，不再重复游戏名称。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，62 项通过；`git diff --check` 通过。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：补丁资源缺失提示直达解决方案

- DLC 列表的“补丁资源缺失，暂无法一键解锁。”提示改为橙色带下划线链接；点击直接打开“DLC 或补丁异常”解决方案详情页。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，62 项通过；`git diff --check` 通过。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：DLC 首页操作顺序与取消下载可见性

- 首页工具栏按“全选 DLC → 逐项管理 DLC → 刷新目录 → 更多操作 → 主操作”重排；一键解锁继续固定在右侧。
- “取消全部下载”不再常驻：仅当下载队列存在可取消项目且当前流程允许取消时，才以危险按钮显示在“更多操作”前；其余时间隐藏。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，62 项通过；`git diff --check` 通过。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：更多操作预渲染

- DLC 首页的“更多操作”区域在页面构建阶段已完成一次布局、控件测量与渲染后再隐藏；点击时只展示已就绪的部件树，避免边框、文字和按钮分批出现。
- 展开时先更新“收起操作”文案再显示内容，收起时先恢复“更多操作”文案再隐藏内容，降低状态与画面不同步的可见概率。
- 修复展开瞬间 DLC 行与操作区重叠：原因是点击回调中的 `update_idletasks()` 先单独绘制了新增行，而外层卡片尚未完成将列表下移的几何计算。预渲染移至窗口构建阶段；点击时不再强制局部重绘，统一交由本轮 Tk 布局提交。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，62 项通过；`git diff --check` 通过。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：统一游戏检测状态文案

- 安装成功后统一显示“路径已验证”，不再仅因群星适配器提供 `rawVersion` 元数据而显示版本号。
- 未发现安装时状态改为“未检测到有效安装”，不再与左侧已选游戏名称重复。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，62 项通过；`git diff --check` 通过。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：补丁资源缺失专用解决方案

- “补丁资源缺失”提示不再跳转至泛用的“DLC 或补丁异常”，而是直接打开同名专用方案。
- 专用方案说明：先返回 DLC 列表刷新目录；若仍缺失，说明云端资源未完整上传或暂时不可用，用户侧无需反复验证文件或重装游戏，应附游戏名称和截图通过 QQ 群或视频评论区反馈。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，62 项通过；`git diff --check` 通过。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：游戏选择弹层延迟聚焦安全修复

- 根因：游戏选择弹层打开时安排的 `after_idle` / `after` 搜索框聚焦回调，可能在用户点击关闭后才执行，对已销毁的 Tk 输入框调用 `focus_force()`，导致 `bad window path name` 回调错误。
- 所有延迟聚焦统一改为安全方法：先确认弹层和输入框仍是当前实例且仍存在，再执行聚焦；聚焦与销毁之间的竞态由 `TclError` 安静处理。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，62 项通过；`git diff --check` 通过。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：补丁资源缺失反馈入口

- “补丁资源缺失”解决方案末尾新增“加入 QQ 群”和“前往 B 站评论区”两个浅色链接按钮。
- QQ 入口复用已有群链接与群号兜底逻辑；B 站入口复用预先允许的官方空间链接。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，62 项通过；`git diff --check` 通过。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：解决方案搜索

- “解决方案”列表新增标题、现象和处理方法的搜索框，以及“模糊匹配 / 精确匹配”选择器，默认模糊匹配。
- 模糊匹配按字符顺序做子序列检索：关键词的字符可以分散在不同位置，只要顺序一致即可命中；精确匹配要求规范化文本中连续出现关键词。
- 无匹配时显示明确的缩短关键词或切换匹配方式提示；`tests/test_ui_theme.py` 已增加搜索行为结构的回归断言。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，62 项通过；`git diff --check` 通过。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：游戏安装状态回调的遗留变量修复

- 根因：统一游戏检测状态文案时删除了 `version_text` 的定义，但顶部状态条仍拼接该变量；路径扫描完成的异步 UI 回调因此稳定触发 `NameError`。
- 顶部状态条统一为“<游戏名> · 路径正常”，彻底移除 `version_text`；新增测试断言防止该遗留变量再次出现。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，63 项通过；`git diff --check` 通过。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：隐藏游戏列表同步的内部来源标识

- 游戏列表同步成功提示不再显示 `remote` / `cache` 等内部索引来源，只保留同步成功和游戏数量。

验证：`python -m py_compile`（0.1.0 与 0.2.0）和 `python -m pytest tests/test_ui_theme.py tests/test_dlc_catalog.py -q`，63 项通过；`git diff --check` 通过。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：缓存操作独立成底部一行

- 缓存概览现在横跨整行；“清理当前游戏 / 打开目录 / 清理全部缓存”统一移到概览下方的同一行，不再占据说明区域右侧。

验证：`python -m py_compile`（0.1.0 与 0.2.0）及 `tests/test_ui_theme.py`，49 项通过；未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：下载源箭头区强制扁平化

- 初次白底样式未在运行时生效：CustomTkinter 5.2 会在箭头区域的 canvas hover 事件中重新套用主题蓝色。
- 下载源选择器现直接重绑该内部 canvas 的 hover 绘制，默认箭头区与输入区同为白色，悬停才显示浅蓝；保留原组件的点击和下拉行为。

验证：`python -m py_compile`（0.1.0 与 0.2.0）及 `tests/test_ui_theme.py`，49 项通过；未启动 GUI、未构建、未 commit 或 push。

## 2026-08-20：发布器资源上传队列与四工作区重整

- 发布器一级入口重整为“发布包与归档 / 资源管理 / 游戏支持数据 / 账户与测试”；原“高级维护”和“核对与验收”收进“账户与测试”的子页，卡带与公告从资源管理移入游戏支持数据。
- 新增持久化 `ContentUploadQueue`：同一游戏在排队、上传、暂停、失败或需重构状态下禁止重复加入；支持 FIFO、上移/下移、删除、暂停、继续、失败后重试，并在程序重启后将上传中的项目安全恢复为“已暂停”。
- DLC / 补丁发布页现在先读取双端远端目录差异，展示将删除的多余附件并二次确认，随后才加入队列；队列上传复用既有附件回读、双源校验、catalog 最后发布和本地构建凭证预检逻辑。
- 队列界面显示当前项目、双源累计进度、文件名、速度、大小和状态；单项失败后自动继续后续排队项目，暂停则停止后续自动开始。
- 进度轮询只更新当前行的文本与进度条，不会销毁并重建整张队列表，避免大文件上传期间产生可见的列表闪烁。
- 内容流水线的远端目录读取改为镜像删除确认后的显式能力，避免不支持远端快照的基础上传 provider 被强制调用 `read_baseline()`。

验证（2026-08-20）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_publisher_upload_queue.py tests\test_publisher_content_pipelines.py tests\test_publisher_release_service.py tests\test_publisher_ui_threading.py -q
$files = Get-ChildItem src\signriver_publisher\*.py | ForEach-Object { $_.FullName }
.\.venv\Scripts\python.exe -c "import py_compile, sys; [py_compile.compile(path, doraise=True) for path in sys.argv[1:]]" @files
.\.venv\Scripts\python.exe -m ruff check src\signriver_publisher\upload_queue.py src\signriver_publisher\upload_queue_ui.py src\signriver_publisher\ui.py src\signriver_publisher\content_management_ui.py src\signriver_publisher\content_release_pipeline.py src\signriver_publisher\release_service.py tests\test_publisher_upload_queue.py tests\test_publisher_ui_threading.py
```

结果：相关测试通过，`py_compile` 与 Ruff 通过；未启动 GUI 做人工验收，未连接 GitLink/GitHub，未真实上传、构建、commit 或 push。

### 收尾补充（2026-08-20）

- 队列现在严格按 FIFO 启动：不能手动启动仍有“待上传 / 已暂停 / 需重新构建”前序项的后续项目；失败项允许暂时跳过，避免单次网络失败阻塞整夜队列。
- 执行镜像删除前会再次比对远端目录与已确认的差异清单；若确认后远端目录发生变化，停止发布并要求重新读取差异、重新确认，避免删除未展示给操作人的新文件。
- DLC / 补丁的内部执行记录不再出现在“发布包与归档”的历史列表；用户只在“上传队列”管理资源发布。
- 远端差异读取失败时会恢复资源页的正常说明，避免页面长期停在“正在读取”状态。

最终验证：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_publisher_workspace.py tests\test_publisher_release_service.py tests\test_publisher_release_providers.py tests\test_publisher_ui_threading.py tests\test_publisher_content_pipelines.py tests\test_publisher_announcements.py tests\test_publisher_acceptance.py tests\test_publisher_upload_queue.py -q
.\.venv\Scripts\python.exe -m ruff check src\signriver_publisher\upload_queue.py src\signriver_publisher\upload_queue_ui.py src\signriver_publisher\ui.py src\signriver_publisher\content_management_ui.py src\signriver_publisher\content_release_pipeline.py src\signriver_publisher\release_center.py src\signriver_publisher\release_center_ui.py src\signriver_publisher\release_service.py src\signriver_publisher\publisher_targets_ui.py tests\test_publisher_upload_queue.py tests\test_publisher_content_pipelines.py tests\test_publisher_ui_threading.py tests\test_publisher_acceptance.py
```

结果：166 项发布器相关测试通过，Ruff 通过；`src/signriver_publisher` 全部模块 `py_compile` 与 `git diff --check` 通过。已成功构建 `dist/publisher/SignRiver-Publisher.exe`（15,608,640 B，SHA-256 `794BE76AE16BCD1D7E34AB23BAD9B03EA0A78F03EDFCA7DC99051DB37542984F`）；未进行真实双源上传、未 commit 或 push。明天建议先启动 `publisher.py` 对四个工作区和上传队列做人工 UI 验收。

## 2026-08-20：程序发布日志与实际上传进度

- 已将“发布文件”页改为独立的总体进度、单文件进度和可滚动执行日志三部分；日志逐行列出自动预检结果与持久化的执行事件，避免此前只有阶段摘要而看不到预检结论。
- 已定位“第 1/5 步运行但一直等待上传”的真实原因：程序发布流水线在上传前会对远端同名大包执行完整下载哈希校验，以判断是否可复用；该读取没有上传进度回调，导致数分钟无可见反馈。实际记录显示该步骤从 05:57 持续到用户请求安全暂停后的 06:01。
- 程序更新包和模块归档改为同名文件直接替换并随后回读校验，不再预先下载远端包判断复用；这与“本地新增、同名替换、远端旧文件保留”的发布语义一致，且上传开始后会立即显示文件名、字节进度和速度。
- 若处于发布步骤但还未收到传输字节回调，界面明确显示“正在准备远端传输并核验已有文件”，不再错误显示“等待上传任务开始”。

验证（2026-08-20）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_publisher_release_service.py tests\test_publisher_content_pipelines.py tests\test_publisher_ui_threading.py -q
.\.venv\Scripts\python.exe -m py_compile src\signriver_publisher\program_release_pipeline.py src\signriver_publisher\release_center.py src\signriver_publisher\release_service.py
.\.venv\Scripts\python.exe -m ruff check src\signriver_publisher\program_release_pipeline.py src\signriver_publisher\release_center.py src\signriver_publisher\release_service.py tests\test_publisher_release_service.py tests\test_publisher_ui_threading.py
git diff --check
```

结果：62 项通过，`py_compile`、Ruff 和 diff 检查通过（仅现有 CRLF 提示）。未重启发布器、未执行真实上传、未构建、未 commit 或 push。

## 2026-08-20：程序发布安全暂停响应优化

- 根因进一步确认：暂停请求已传入 GitLink/GitHub 上传器，但远端回读校验没有检查暂停信号；同时上传和校验网络调用的单次超时为 120 秒。网络对端停止接收或回读等待响应时，用户只能等当前调用返回，造成“点了安全暂停几分钟没反应”。
- 远端校验读取现在在开始前和每 256 KiB 读取后检查暂停；已请求暂停时立即以 `ReleasePauseRequested` 结束当前可恢复步骤，保留完整性校验语义。
- GitHub/GitLink 上传块由 1 MiB 改为 256 KiB，暂停粒度相应缩短；上传与远端读取的停滞连接超时由 120 秒收敛为 20 秒。若超时发生时已请求暂停，转换为安全暂停而非失败。
- 程序更新包和模块包此前已移除“上传前下载远端大文件判重复”的步骤；实际发布会直接替换同名文件，随后仍做完整回读校验。因此新版下，安全暂停通常会在一个 256 KiB 块结束后生效；仅在底层网络调用完全无响应时最多等待约 20 秒。

验证（2026-08-20）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_publisher_github.py tests\test_publisher_release_providers.py tests\test_publisher_release_service.py tests\test_publisher_content_pipelines.py tests\test_publisher_ui_threading.py -q
.\.venv\Scripts\python.exe -m py_compile src\signriver_publisher\remote_release_providers.py src\signriver_publisher\github.py src\signriver_publisher\gitlink.py
.\.venv\Scripts\python.exe -m ruff check src\signriver_publisher\remote_release_providers.py src\signriver_publisher\github.py src\signriver_publisher\gitlink.py tests\test_publisher_github.py tests\test_publisher_release_providers.py
git diff --check
```

结果：77 项通过，`py_compile`、Ruff 和 diff 检查通过（仅现有 CRLF 提示）。未重启发布器、未执行真实上传、未构建、未 commit 或 push。

## 2026-08-20：发布目标仓库连通性测试

- “账户与测试 → 发布目标”的 GitLink 与 GitHub 卡片各新增“测试连通性”；测试读取当前表单中的所有者、仓库和已保存令牌，不会保存表单、上传文件或修改远端内容。
- GitHub 通过只读仓库信息 API 检查；GitLink 通过只读发布列表 API 检查。结果直接显示在对应卡片底部，区分已连接、令牌缺失、仓库不存在/无权限和网络错误。
- 连通性请求运行于后台线程，避免网络缓慢时冻结发布器界面；窗口关闭后 UI 事件泵会丢弃回调。

验证（2026-08-20）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_publisher_ui_threading.py tests\test_publisher_github.py tests\test_publisher_workspace.py -q
.\.venv\Scripts\python.exe -m py_compile src\signriver_publisher\publisher_targets_ui.py
.\.venv\Scripts\python.exe -m ruff check src\signriver_publisher\publisher_targets_ui.py tests\test_publisher_ui_threading.py
git diff --check
```

结果：121 项通过，`py_compile`、Ruff 和 diff 检查通过（仅现有 CRLF 提示）。未启动 GUI、未连接真实仓库、未构建、未 commit 或 push。

## 2026-08-20：程序发布同时纳入模块归档

- “发布包与归档 → 本地发布文件”新增独立的“模块归档目录”选择；创建、复用和刷新程序发布记录时都会保存并读取该目录，而不是仅从三端更新包目录推测模块位置。
- 本地与云端差异读取扩展为两个分组：更新包使用更新 Release，模块归档使用模块 Release；两组都会读取 GitLink 与 GitHub 的只读基线。
- 预检新增模块归档硬门禁：必须存在当前版本、可解析的模块归档；模块文件在确认后被删除或修改也会使冻结输入失效，不能继续发布。点击“发布文件”后既有流水线会一并上传、回读校验三端更新包和模块归档。

验证（2026-08-20）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_publisher_release_service.py tests\test_publisher_ui_threading.py tests\test_publisher_release_providers.py tests\test_publisher_content_pipelines.py -q
.\.venv\Scripts\python.exe -m py_compile src\signriver_publisher\artifact_collector.py src\signriver_publisher\release_service.py src\signriver_publisher\release_preflight.py src\signriver_publisher\release_center.py src\signriver_publisher\release_center_ui.py
.\.venv\Scripts\python.exe -m ruff check src\signriver_publisher\artifact_collector.py src\signriver_publisher\release_service.py src\signriver_publisher\release_preflight.py src\signriver_publisher\release_center.py src\signriver_publisher\release_center_ui.py tests\test_publisher_release_service.py
git diff --check
```

结果：72 项测试通过，`py_compile`、Ruff 和 diff 检查通过（仅现有 CRLF 提示）。未启动 GUI、未连接真实 GitLink/GitHub、未实际上传、未构建、未 commit 或 push。

## 2026-08-20：DLC / 补丁发布仓库自动创建

- 已确认原实现只会在仓库已存在时创建或复用对应的 Release；目标仓库不存在会直接失败。
- 现在只有 `GAME_CONTENT`（DLC / 补丁）发布在读取远端差异或开始上传前确保冻结目标仓库存在：已有仓库直接复用；GitHub 缺失时会按配置的个人账户或组织创建公开仓库；GitLink 缺失时会先确认 `gitlink-cli` 的当前登录账户就是目标所有者，再创建并回读确认，避免错误地在其他账户创建同名仓库。
- 程序更新和模块归档发布保持原有行为，不会因本次逻辑自动创建仓库。

验证（2026-08-20）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_publisher_github.py tests\test_publisher_release_providers.py tests\test_publisher_content_pipelines.py tests\test_publisher_upload_queue.py tests\test_publisher_ui_threading.py -q
.\.venv\Scripts\python.exe -m py_compile src\signriver_publisher\github.py src\signriver_publisher\gitlink.py src\signriver_publisher\remote_release_providers.py src\signriver_publisher\release_center_ui.py
.\.venv\Scripts\python.exe -m ruff check src\signriver_publisher\github.py src\signriver_publisher\gitlink.py src\signriver_publisher\remote_release_providers.py src\signriver_publisher\release_center_ui.py tests\test_publisher_github.py tests\test_publisher_release_providers.py
git diff --check
```

结果：78 项测试通过，`py_compile`、Ruff 与 diff 检查通过（仅现有 CRLF 提示）。未启动 GUI、未连接真实 GitLink/GitHub、未真实创建仓库或上传、未构建、未 commit 或 push。

## 2026-08-20：移除兼容发布工作区

- 已逐项核对旧“兼容发布（回退 / 修复）”页面：DLC/补丁构建与 Steam 数据刷新由“资源管理 → 本地资源 / DLC / 补丁发布”承载；程序更新与模块归档由“发布包与归档 → 本地发布文件”承载；卡带中心由“游戏支持数据 → 卡带与公告”双源发布承载；远端资源维护位于“资源管理 → 远端维护”。该页没有剩余的独立能力。
- 已从“账户与测试”移除“兼容发布”二级入口、页面创建和 `CompatibilityPublishUiMixin` 的运行时组装；旧单源控制不再能通过 GUI 进入。保留未接线的兼容实现文件与旧父类方法，避免在当前大量未提交的发布器重构中进行无关的大规模删除。

验证（2026-08-20）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_publisher_ui_threading.py tests\test_ui_theme.py tests\test_publisher_content_pipelines.py tests\test_publisher_upload_queue.py tests\test_publisher_release_service.py -q
.\.venv\Scripts\python.exe -m py_compile src\signriver_publisher\ui.py src\signriver_publisher\content_management_ui.py src\signriver_publisher\release_center_ui.py
.\.venv\Scripts\python.exe -m ruff check src\signriver_publisher\ui.py tests\test_publisher_ui_threading.py tests\test_ui_theme.py
git diff --check
```

结果：118 项测试通过，`py_compile`、Ruff 与 diff 检查通过（仅现有 CRLF 提示）。未启动 GUI、未构建、未 commit 或 push。

### 启动修复补充（2026-08-20）

- 移除“兼容发布”页面后，遗留基类初始化仍会调用旧的发布目标同步方法，而该方法读取已被移除的 `publish_target_menu`，导致发布器启动即报 `AttributeError`。
- `PublisherApplication` 现在直接从 `PublisherSettings.publish_target` 取得发布目标，并将仅服务于旧兼容页面的控件同步改为安全空操作；新的“发布目标”页面仍会自行重建界面。
- 验证：`tests/test_publisher_ui_threading.py`、`tests/test_ui_theme.py` 共 87 项通过，`py_compile`、Ruff 与 `git diff --check` 通过。未启动 GUI、未构建、未 commit 或 push。

## 2026-08-21：DLC / 补丁发布包操作日志

- “资源管理 → DLC / 补丁发布”页面在发布包状态下方新增只读、自动滚动的“操作日志”框；每行带本地时间戳，最多保留最近 500 条，防止长时间运行导致界面日志无限增长。
- 当前页面的用户操作（切换游戏、查看资源/队列、加入或移除构建项、加入上传、导入/清理本地资源、保存或新增卡带、刷新 Steam/远端资源）以及构建、上传、远端维护等后台任务的开始、进度、成功、失败和“同游戏保留最新提交”的重排结果，均统一写入该日志。
- 所有后台日志都沿用已有的 `_post_ui` 回调回到 Tk 主线程后输出；日志控件不存在或页面尚未创建时安全忽略，避免影响后台任务和窗口关闭。

验证（2026-08-21）：

```powershell
python -m pytest -q
python -m ruff check src/signriver_publisher/content_management_ui.py src/signriver_publisher/upload_queue_ui.py src/signriver_publisher/remote_maintenance_ui.py tests/test_publisher_ui_threading.py
python -m py_compile src/signriver_publisher/content_management_ui.py src/signriver_publisher/upload_queue_ui.py src/signriver_publisher/remote_maintenance_ui.py
python tools/build_publisher.py --upx-dir C:\Users\32173\AppData\Local\tools\upx\upx-5.0.2-win64
```

结果：全量 pytest 通过；Ruff 与 `py_compile` 通过。已重建 `dist/publisher/SignRiver-Publisher.exe`（15,727,262 bytes，SHA-256 `5ED437285D267895BAC159E5C39B62C8197862CA8055D189C041580D32A113F9`）。构建中 UPX 对 `_uuid.pyd` 报“不可压缩”警告，PyInstaller 自动保留原文件，构建仍成功。未启动 GUI、未执行真实远端操作、未 commit 或 push。

### 后续验证约定（2026-08-21）

- 用户已确认：日常发布器开发默认直接运行 `\.venv\Scripts\python.exe publisher.py` 并执行相关测试；不再因每次发布器源码改动自动重建 EXE。仅在用户明确要求构建、需要交付 EXE 或准备正式发布时才运行 `tools/build_publisher.py`。

### 操作日志无滚动条调整（2026-08-21）

- 用户要求移除 DLC / 补丁发布页的滚动条。该页现改用普通容器，不再创建外层滚动条；日志文本框也关闭自身滚动条。
- 日志框初始仅一行，并随最新日志自适应增长；页面仅展示最近 8 条，避免空白区域或大量日志把页面撑出可视区域。完整内存日志仍保留最近 500 条，供后续写入时取最新 8 条显示。
- 验证：`python -m pytest tests/test_publisher_ui_threading.py tests/test_publisher_upload_queue.py -q`（53 项通过）、Ruff 与 `py_compile` 通过。按用户确认的日常验证约定，未重新构建 EXE。

### 同游戏提交覆盖日志（2026-08-21）

- 构建与上传队列在接受提交前读取同游戏已有项，并在操作日志明确输出实际队列决策：新增项、覆盖非运行旧项，或运行中项保留新提交并在当前安全步骤/构建结束后重新执行。
- 日志不再以“同游戏保留最新提交”的泛化文案掩盖实际行为，方便操作员逐步核对后台队列执行了什么。
- 验证：`python -m pytest tests/test_publisher_ui_threading.py tests/test_publisher_upload_queue.py -q`（53 项通过）、Ruff 与 `py_compile` 通过。未重新构建 EXE。

### 构建队列运行项高度修复（2026-08-21）

- 根因：正在构建的项目没有可用操作，但仍创建了空的 `CTkFrame` 操作容器；CustomTkinter 空框保留默认高度，网格布局因此把整项撑大。
- 运行项现在不创建操作容器，仅展示名称、状态和进度说明；完成、等待和失败项仍保留相应按钮，卡片统一保持紧凑两行高度。
- 验证：`python -m pytest tests/test_publisher_ui_threading.py tests/test_publisher_upload_queue.py -q`（54 项通过）、Ruff 与 `py_compile` 通过。未重新构建 EXE。

### 操作日志历史滚动（2026-08-21）

- 按用户最新要求，DLC / 补丁发布页仍没有外层页面滚动条，但操作日志框恢复内部滚动条。日志框高度仅按最近 8 行自适应，框内则完整渲染并可翻阅最近 500 条记录；每次新增事件仍自动定位到最新行。
- 验证：`python -m pytest tests/test_publisher_ui_threading.py tests/test_publisher_upload_queue.py -q`（54 项通过）、Ruff 与 `py_compile` 通过。未重新构建 EXE。

### 移除远端维护页旧审计入口（2026-08-21）

- “批次诊断”只汇总当前发布批次状态/事件，“导出审计”只导出 JSON 留档；两者不参与远端刷新、上传或资源维护，且当前操作日志和发布记录已满足日常查看需求。
- 已从“远端资源维护”工具栏移除两个入口，并保留底层审计服务与测试，避免影响既有批次历史或排障能力。
- 验证：`python -m pytest tests/test_publisher_ui_threading.py tests/test_publisher_release_audit.py -q`（51 项通过）、Ruff 与 `py_compile` 通过。未重新构建 EXE。

### DLC / 补丁云端变更预览（2026-08-21）

- “远端资源维护 → 刷新远程”现在同步渲染本地发布文件与远端附件的元数据差异：本地文件标记“将新增到云端”或“将替换云端同名文件”；远端附件标记“将被同名文件替换”或“云端保留（批量镜像发布时将删除）”。
- 差异只读取本地目录和远端附件列表/元数据，明确不下载远端附件；手动维护页面本身不会删除云端仅有文件，删除仅会发生在已有二次确认的批量镜像上传流程中。
- 验证：`python -m pytest tests/test_publisher_ui_threading.py tests/test_publisher_content_pipelines.py tests/test_publisher_upload_queue.py -q`（66 项通过）、Ruff 与 `py_compile` 通过。未重新构建 EXE。

### DLC / 补丁按已验证构建缓存复用（2026-08-21）

- 纠正此前错误地把 DLC / 补丁同名文件预览为“必须替换”的逻辑。内容发布与程序发布不同：DLC / 补丁附件只有在本地 SHA-256、大小与此前成功回读验证所保存的同源缓存一致，并且当前远端列表仍存在该附件时，才复用并跳过上传；缺失、缓存不一致或远端附件标识变化时才上传替换。`catalog.json` 仍始终最后发布。
- 每次成功的游戏内容发布都会把双源经回读验证的附件哈希、大小和远端标识写入发布批次阶段结果；创建下一批同游戏内容时自动带入。旧 GitLink `.publish-state.json` 也会迁移性地作为首轮缓存来源，避免旧工作区被迫全量重传。
- 云端检测预览现在显示“云端缓存一致，将跳过上传 / 将保留”；上传完成的操作日志会汇总实际复用数量。复用决策只读取远端目录元数据和本地已验证缓存，不下载附件；对缓存未覆盖或不可信的附件仍上传后完整回读校验。
- 验证：`python -m pytest tests/test_publisher_content_pipelines.py tests/test_publisher_upload_queue.py tests/test_publisher_ui_threading.py -q`（68 项通过）、Ruff 与 `py_compile` 通过。未重新构建 EXE。

### DLC 不变资源分类与显式云端信任（2026-08-21）

- 分类规则已收紧：只有文件名为 `dlc*.zip`（含 DLC 分卷）的不可变 DLC 附件可以按缓存复用；补丁、DLL、其他附件均视为可变内容，即使同名且存在缓存也会每次上传替换；`catalog.json` 继续固定最后发布。
- “远端资源维护”新增“信任云端 DLC”按钮。用户确认后，程序仅对当前远端列表中与本地同名的 DLC ZIP 写入 `.content-reuse-cache.json`（保存本地 SHA-256、大小和远端附件标识），不下载、不上传、不删除任何附件；下一批发布即可跳过这些 DLC。成功上传的验证缓存也会同步写入该文件。
- 差异预览明确区分“DLC 缓存一致，将跳过上传”和“每次更新，将替换云端同名文件”。
- 验证：`python -m pytest -q`（全量通过）、Ruff 与 `py_compile` 通过。未重新构建 EXE。

### 远端资源维护差异清单重排（2026-08-21）

- 远端维护页不再并排重复展示本地与远端的大量文件。顶部新增“发布差异摘要”，显示跳过上传、需要更新、新增和云端多余的计数。
- 内容区改为“变更清单 / 云端详情”页签：默认变更清单按“需要发布”和“可复用 DLC”分组，以紧凑的文件名、分类、动作标签展示；云端附件、大小与删除按钮移至云端详情页，仍保留所有维护能力。
- 验证：`python -m pytest tests/test_publisher_ui_threading.py tests/test_publisher_content_pipelines.py tests/test_publisher_upload_queue.py -q`（71 项通过）、Ruff 与 `py_compile` 通过。未重新构建 EXE。

### 游戏卡带配置自适应滚动布局（2026-08-21）

- 表单保持紧凑行距与 32 px 输入控件，但新增“额外补丁目录”后已无法保证所有窗口高度都容纳完整内容；“游戏支持数据 → 游戏配置”现使用独立的内部 `CTkScrollableFrame`，确保底部新增/保存按钮始终可达。
- 验证：`python -m pytest tests/test_publisher_ui_threading.py tests/test_publisher_workspace.py -q`（120 项通过）、Ruff 与 `py_compile` 通过。未重新构建 EXE。
- 滚动恢复后的复核（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_ui_threading.py tests\test_publisher_workspace.py -q`、Ruff、`compileall` 与 `git diff --check` 通过；未启动 GUI、未构建 EXE、未 commit 或 push。

### 远端资源维护详情侧边栏（2026-08-21）

- “远端资源维护”的“变更清单 / 云端详情”不再使用位于内容中央的分段页签；内容卡片改为左侧紧凑导航栏、右侧详情区域，默认打开“变更清单”。
- 两个页面仍复用原有的差异清单、云端附件列表和删除控件，仅调整导航与布局，不改变远端读取、缓存复用或维护行为。
- 验证：` .\.venv\Scripts\python.exe -m pytest tests/test_publisher_ui_threading.py tests/test_publisher_content_pipelines.py tests/test_publisher_upload_queue.py -q`、Ruff、`py_compile` 与 `git diff --check` 通过（仅已有 CRLF 提示）。未重新构建 EXE、未启动 GUI、未执行真实远端操作、未 commit 或 push。

### 群星 DLC 统一为通用目录包（2026-08-21）

- 已先提交此前发布器队列、远端维护和 UI 改动：`f39210d feat(publisher): 优化内容发布队列与远端维护`；按规则未 push。
- 群星发布器内置卡带、现有工作区迁移、Hub 卡带 JSON 与其索引 SHA-256/大小均改为 `package_inspector=directory`，发布器界面不再提供“Stellaris ZIP 描述包”选项。已有工作区中的旧 `stellaris_zip` 值在初始化时自动迁移。
- 客户端的群星默认卡带、安装引擎与安装服务均使用通用目录校验；旧远端/缓存卡带标签 `stellaris_zip` 仍被解析，但明确映射到通用校验，避免客户端因旧卡带崩溃。通用校验保留正式附件名检查，并仅兼容旧离线 `dlcNNN.zip` 短名。
- 验证：客户端安装引擎、安装服务、卡带目录、群星旧卡带兼容、多游戏校验、发布器工作区与 UI 的针对性 pytest 通过；随后使用短路径独立测试根运行 ` .\.venv\Scripts\python.exe -m pytest -q --basetemp C:\ctXXXX` 全量通过，Ruff、`compileall` 与 `git diff --check` 通过。未构建发布包、未启动 GUI、未执行真实上传或 push。

### 多目录补丁目标（2026-08-21）

- 客户端 `PatchProfile`、远端卡带文档及发布器 `PublisherCartridge` 新增额外补丁目录字段；主目录字段继续保留以兼容已有卡带。补丁引擎将同一套代理库、原生库和配置文件作为一次事务写入所有目录，审计、还原和移除同样逐一覆盖；任一环节失败会整体回滚。
- 《奇迹时代4》已配置游戏根目录与 `launcher-se/resources/app.asar.unpacked/node_modules/greenworks/lib` 两个目标；已有发布器工作区初始化时会自动迁移该卡带。发布器“游戏卡带配置”可用分号填写“额外补丁目录”；Hub JSON 与索引哈希/大小已同步。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest -q`、` .\.venv\Scripts\python.exe -m ruff check .`、` .\.venv\Scripts\python.exe -m compileall -q src app\versions\0.1.0` 与 `git diff --check` 均通过（仅既有 CRLF 提示）。未启动 GUI、未执行真实游戏/远端操作、未构建 EXE、未 commit 或 push。

### 构建队列统一兼容发布策略（2026-08-21）

- “兼容发布：保留云端仅有文件”已从远端维护页移至“资源构建队列”操作栏。它是发布器全局设置，批量或单项将已构建内容加入上传队列时统一读取当前值，并冻结到各自的 `GAME_CONTENT` 计划；修改开关后不会篡改已经入上传队列的计划。
- 设置保存在发布器根目录 `.content-publish-options.json`。初始化会迁移旧版各游戏目录下的同名设置：任意一个旧值为开启，即迁移为全局开启。远端维护仅按当前全局策略显示差异，不再提供重复开关。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest -q`、` .\.venv\Scripts\python.exe -m ruff check .`、` .\.venv\Scripts\python.exe -m compileall -q src app\versions\0.1.0` 与 `git diff --check` 均通过（仅既有 CRLF 提示）。未启动 GUI、未执行真实远端操作、未构建 EXE、未 commit 或 push。
# 2026-08-21：DLC 自动导入编号以当前目录为准

- 自动编号不再把 `.dlc-import-state.json` 的历史高水位当作下限；该文件仅保留为可观测状态。单项删除 DLC 后会立即同步当前编号，发布器重启后也以仍存在的 `dlcNNN_*` 目录重新计算。
- 已补充覆盖“导入、删除、重启、再导入”的工作区测试，预期新目录重新从 `dlc001_` 开始（若仍有其他编号目录，则从当前最大编号后的下一个开始）。

### 发布目录直接校验与 GitLink 短暂故障处理（2026-08-21）

- 已移除“完整构建凭证”作为内容上传入队门禁：`PublisherWorkspace.publish_assets()` 直接校验当前发布目录的必需文件、分卷、大小和 SHA-256；`.build-complete.json` 仍可作为构建诊断快照，但不存在或过期不再阻塞入队。旧的完成构建产物也可继续发布；源文件随后变化不会自动混入已有产物，需显式重建才会更新输出。
- GitLink Release 元数据读取仅对幂等 GET 请求以 10 秒超时最多重试 3 次；发布写操作不重试。批量加入上传队列会继续预检其余项目，并在确认框明确列出因读取双端差异失败而未入队的项目，不再第一项失败就让整批消失。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_workspace.py tests\test_publisher_content_pipelines.py tests\test_publisher_upload_queue.py tests\test_publisher_ui_threading.py tests\test_publisher_release_providers.py -q`（166 项通过）、` .\.venv\Scripts\python.exe -m ruff check src\signriver_publisher\workspace.py src\signriver_publisher\gitlink.py src\signriver_publisher\content_management_ui.py tests\test_publisher_workspace.py`、` .\.venv\Scripts\python.exe -m compileall -q src\signriver_publisher` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未启动 GUI、未执行真实上传、未构建 EXE、未 commit 或 push。
- 当前分支 `main`，HEAD `f39210d`，工作区保留此前整批未提交改动；GitLink 真实网络可用性尚未再次人工验证，仍取决于服务端当时状态。

### 一键加入上传队列的可见预检进度（2026-08-21）

- “一键加入上传队列”进入后台预检时，按钮会显示“正在读取云端差异…”，构建队列摘要实时显示第几项、当前游戏和读取状态，不再只有灰色禁用按钮。
- 若首个项目确认 GitLink 不可达，后续项目会明确标记为跳过，不再逐项重复等待超时；结束后恢复按钮并显示未入队的原因。
- 验证：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_ui_threading.py tests\test_publisher_content_pipelines.py tests\test_publisher_upload_queue.py -q`（78 项通过）、Ruff、`compileall` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未启动 GUI、未构建 EXE、未 commit 或 push。

### 远端预检延后至队列实际执行（2026-08-21）

- 用户指出“一键加入上传队列”必须是本地排队操作，不能为每个游戏先做远端网络预检。现单项和批量加入都只创建/覆盖本地 FIFO 项；远端差异在该项轮到上传时才读取。
- 严格镜像模式在该项开始上传前展示当次远端多余文件并要求确认；取消则暂停该项。兼容发布仍在实际执行前读取远端目录，但不请求删除确认。上传队列页明确说明此时序。
- 验证：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_ui_threading.py tests\test_publisher_upload_queue.py tests\test_publisher_content_pipelines.py tests\test_publisher_workspace.py -q`（159 项通过）、Ruff、`compileall` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未启动 GUI、未执行真实远端操作、未构建 EXE、未 commit 或 push。

### 一键加入上传队列不再阻塞界面（2026-08-21）

- 根因：远端预检虽已延后，但“一键加入上传队列”仍在 Tk 主线程逐项校验发布目录、计算附件哈希并创建本地发布记录；资源包较大或完成项较多时，事件循环无法响应，表现为发布器卡死。
- 已按操作语义调整：一键或单项“加入上传队列”只立即写入本地 FIFO，直接使用构建任务已有的文件数与大小，不再显示“正在准备上传队列”、重算哈希或创建发布记录。实际轮到上传时，后台才校验本地发布文件、创建/复用发布记录并读取云端差异；本地文件已变化会在此时安全标记为需重新构建。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_ui_threading.py tests\test_publisher_upload_queue.py tests\test_publisher_content_pipelines.py tests\test_publisher_workspace.py -q` 通过；` .\.venv\Scripts\python.exe -m ruff check src\signriver_publisher\content_management_ui.py src\signriver_publisher\upload_queue.py src\signriver_publisher\upload_queue_ui.py tests\test_publisher_ui_threading.py` 与 `py_compile` 通过。未启动 GUI、未执行真实远端操作、未构建 EXE、未 commit 或 push。

### 上传队列一键清空（2026-08-21）

- 上传队列工具栏新增红色描边“一键清空队列”按钮，位于“暂停当前项”和“刷新”之间。确认后仅删除全部本地队列记录，不删除任何已构建的本地发布文件。
- 队列存在运行项时，底层操作会拒绝清空并提示先安全暂停，避免中断上传或留下不一致状态。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_ui_threading.py tests\test_publisher_upload_queue.py tests\test_publisher_content_pipelines.py tests\test_publisher_workspace.py -q` 通过；Ruff、`py_compile` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未启动 GUI、未执行真实远端操作、未构建 EXE、未 commit 或 push。

### GitLink 游戏内容附件回读使用正确的 Release 标签（2026-08-21）

- 根因：GitLink 游戏内容上传正确使用当前游戏的 Release 标签，但上传后 `inspect()` 生成下载 URL 时错误固定为程序更新 Release 标签，导致它从另一份 Release 下载同名附件并产生 SHA-256 不匹配，例如 `original.dll` 和 `<game>_appinfo.json`。
- `release_asset_url()` 现在可接收 Release 标签，GitLink provider 回读时显式使用自身当前标签；程序更新现有调用维持默认更新标签不变。上传成功仍需完整回读校验，未发布 `catalog.json` 的中途失败附件不会成为客户端可用内容。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_release_providers.py tests\test_publisher_content_pipelines.py tests\test_publisher_upload_queue.py tests\test_publisher_ui_threading.py -q`、Ruff 与 `py_compile` 通过。未启动 GUI、未执行真实远端操作、未构建 EXE、未 commit 或 push。

### 上传队列日志输出完整发布细节（2026-08-21）

- 每项远端预检结束后，操作日志逐一列出本地发布快照的文件名、大小和 SHA-256，并分别列出 GitLink/GitHub 的云端仅有文件及其“保留”或“校验成功后删除”处理方式。
- 上传完成后，日志按来源和附件逐项记录“上传并 SHA-256 回读通过”或“复用已验证云端附件”，同时记录远端多余文件删除结果与最后 `catalog.json` 的发布/回读结果。日志框保持内部滚动，可查看完整近期记录。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_ui_threading.py tests\test_publisher_upload_queue.py tests\test_publisher_content_pipelines.py tests\test_publisher_workspace.py -q`、Ruff 与 `py_compile` 通过。未启动 GUI、未执行真实远端操作、未构建 EXE、未 commit 或 push。

### 当前文件传输进度条与完成日志（2026-08-21）

- DLC / 补丁发布页的操作日志下方新增“当前文件传输”卡片。它只表示当前一个上传或云端回读文件，显示操作、源站、文件名、0–100% 进度、已传输大小、总大小与实时速度；切换下一个文件时进度重新从零开始，不能再把整个队列总量伪装成单文件进度。
- GitLink 和 GitHub 的完整附件回读均在流式读取时上报进度；上传和回读的每个文件完成后，上传队列轮询会在操作日志记录一条完成事件。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_release_providers.py tests\test_publisher_ui_threading.py tests\test_publisher_upload_queue.py tests\test_publisher_content_pipelines.py tests\test_publisher_workspace.py -q`、Ruff 与 `py_compile` 通过。未启动 GUI、未执行真实远端操作、未构建 EXE、未 commit 或 push。

### GitHub Release 元数据读取超时重试与准确提示（2026-08-21）

- 根因：GitHub 目标的连通性测试与上传队列预检使用的都是同一份仓库/令牌配置；前者成功而后者失败时，失败点是 Release 元数据响应体读取发生瞬时超时。旧实现只重试“建立请求”阶段，未覆盖 `response.read()`，且把超时统一包装成“GitHub 连接失败”。
- GitHub API 的只读 GET 现在把建立连接和读取响应体一并纳入最多 3 次自动重试；写请求不因本次修复重试，避免不确定的重复写入。三次均超时时日志会明确显示“GitHub API 读取超时，已自动重试 3 次”，不再误导为账号、令牌或仓库配置失败。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_github.py tests\test_publisher_release_providers.py tests\test_publisher_upload_queue.py tests\test_publisher_ui_threading.py -q`（88 项通过）、` .\.venv\Scripts\python.exe -m ruff check src\signriver_publisher\github.py tests\test_publisher_github.py`、`py_compile` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未启动 GUI、未执行真实远端操作、未构建 EXE、未 commit 或 push。

### 发布后附件 ID / 大小可信记录，取消远端 SHA-256 回读（2026-08-21）

- 用户当前网络只能勉强完成上传，无法稳定下载 Release 附件。因此 GitHub/GitLink provider 的 `upload()` 不再调用 `inspect()` 下载附件并计算远端 SHA-256；GitHub 直接使用上传响应的附件 ID/大小，GitLink 使用上传结果的附件 ID 与本地上传大小（旧兼容实现缺少返回值时只读取 Release 元数据，不读取附件）。
- 所有上传门禁改为“上传成功、远端附件 ID 存在、大小匹配”。本地 SHA-256 继续保存到内容复用记录，作为下一次检测本地文件是否改变的依据；不可变 DLC 还必须确认当前远端元数据中的附件 ID 不变才能复用。补丁与 catalog 仍每次直接替换。程序更新的最终清单核对也只检查远端附件 ID 未变。
- 上传队列页面、确认文案和详细日志均已改为“记录远端附件 ID 与大小”，不再声称执行了云端 SHA-256 回读；“当前文件传输”仅显示上传，不再出现云端回读下载进度。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_github.py tests\test_publisher_release_providers.py tests\test_publisher_content_pipelines.py tests\test_publisher_release_batches.py tests\test_publisher_release_service.py tests\test_publisher_upload_queue.py tests\test_publisher_ui_threading.py tests\test_publisher_workspace.py -q`（219 项通过）、Ruff、`py_compile` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未启动 GUI、未执行真实远端操作、未构建 EXE、未 commit 或 push。

### 上传失败日志诊断（2026-08-21）

- 用户提供的是取消附件回读与 GitHub GET 重试改动之前的运行日志，因此不能用其中旧的“GitHub 连接失败”文案判断当前源码是否生效。首项裸露的 `The read operation timed out` 对应旧版附件回读链路，现已移除。
- 配置页的连通性测试仅请求仓库/Release 元数据；GitHub 实际附件上传走独立上传端点，GitLink 实际文件上传走 `POST /api/attachments.json` 的 TLS 长连接。因此“测试已连接”不能证明上传端点、代理规则或长连接稳定性。
- 当前剩余的系统性可用性问题在于：每个文件必须依次完成 GitLink 和 GitHub 双端上传，任一端一次失败就使该游戏失败；GitLink 附件上传路径以 20 秒 socket 停滞为硬失败且不重试，日志中的 `SSL: UNEXPECTED_EOF_WHILE_READING` 正来自这一条路径。GitHub 元数据 GET 已有重试，但上传端点及 GitLink 附件上传仍需要面向“结果未知”的幂等恢复方案，不能盲目重试写操作。
- 本次仅完成代码与日志链路诊断，未执行真实网络操作、未修改上传重试策略、未构建 EXE、未 commit 或 push。

### 双源上传结果未知恢复（2026-08-21）

- 内容附件上传阶段现在在每个源/文件完成后，把远端附件 ID 与大小保存到该阶段的持久化进度。一个源之后失败时，重试同一发布计划会先读取双端 Release 元数据，已记录 ID 仍存在的源直接跳过，只补未完成的源；不会重传已成功的一端。
- 上传调用发生超时、EOF 或响应丢失后，程序会立即从 Release 元数据中查找同名附件：若有附件 ID，且可获得的远端大小与本地一致，即视为服务端已接收并继续。队列详情日志会明确显示“上传响应丢失，已从远端附件记录恢复”或“沿用本批此前已成功的上传端”。
- GitHub 上传响应丢失时先查 Release 内同名同大小附件，不再先删除潜在已成功的上传。GitLink 绑定已上传附件到 Release 的更新请求使用同一附件 ID/完整列表有限重试；最终结果未知时不删除新附件，保留给下一次元数据恢复确认。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_content_pipelines.py tests\test_publisher_github.py tests\test_publisher_upload_queue.py tests\test_publisher_ui_threading.py tests\test_publisher_workspace.py -q`（176 项通过）；随后全量 ` .\.venv\Scripts\python.exe -m pytest -q`、` .\.venv\Scripts\python.exe -m ruff check .` 与 ` .\.venv\Scripts\python.exe -m compileall -q src app\versions\0.1.0 tools tests` 均通过。未启动 GUI、未执行真实远端操作、未构建 EXE。

### 切换窗口检查点（2026-08-21）

- 已完成并本地提交当前连续改动：`84defad feat: 强化发布队列与双源恢复`。提交包含客户端卡带/补丁改动、发布器构建与上传队列、取消附件回读、双源结果未知恢复、测试与交接文档。
- 当前分支 `main`，HEAD `84defadfe360643221fc373fa560f3245f91eff2`；相对 `origin/main` 为 `0 9`（本地领先 9 个提交）。交接文档此次更新尚未提交；除此之外工作区无未提交改动。
- 未构建发布器 EXE、未执行真实远端上传、未上传模块归档/更新包，也未 push。后续若准备发布，先按 AGENTS 维护版本与 `publisher-workspace/update-notes.json`、构建并上传/核验发布资产，然后由用户决定是否 `git push origin main`。

### 上传队列操作日志持久化与逐文件结果（2026-08-21）

- 发布器的 DLC / 补丁发布页操作日志现保存为发布器工作区的 `operation-log.jsonl`，仅保留最近 500 条无凭据的用户可见文本；重启后自动恢复，不再因关闭程序清空。
- 内容发布流水线会在每个源站、每个附件实际上传成功、复用可信记录或从上传响应丢失中恢复时立即把结果写入阶段安全检查点；上传队列轮询即时展示该结果，游戏完成时明确记录“全部文件已成功上传并发布 catalog.json”。修复了 UI 错把实际 `content.upload_snapshot` / `content.publish_index` 阶段名写为 `game_content.*`、因而漏掉逐项成功明细的缺陷。
- GitLink 上传在建立网络请求前会对本地发布文件的短暂 Windows 占用做三次读取重试；持续占用会提示关闭占用程序后重试，避免把有效发布包错误标为必须重建。奇迹时代 4 的“本地发布文件变化或不完整”仍是正确的安全门禁，必须重新构建。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest -q tests\test_publisher_content_pipelines.py tests\test_publisher_release_providers.py tests\test_publisher_upload_queue.py tests\test_publisher_ui_threading.py tests\test_publisher_operation_log.py`（92 项通过）、对应 Ruff、` .\.venv\Scripts\python.exe -m compileall -q src\signriver_publisher` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未启动 GUI、未构建 EXE、未执行真实上传、未 commit 或 push。

### 构建队列单项加入上传队列刷新（2026-08-21）

- 根因：构建队列单项“加入上传队列”调用已持久化入队方法后直接返回，未刷新上传队列或构建队列，也没有成功提示、自动跳转或异常提示。因此日志会重复出现“将…加入”而界面仍停留在旧状态。
- 单项入队现在成功后立即刷新两份队列、日志记录队列位置和文件数并切换到“上传队列”；写入失败会写入失败日志并显示错误框，避免静默失败。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest -q tests\test_publisher_ui_threading.py tests\test_publisher_upload_queue.py tests\test_publisher_operation_log.py`（69 项通过）、对应 Ruff、` .\.venv\Scripts\python.exe -m compileall -q src\signriver_publisher` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未启动 GUI、未构建 EXE、未执行真实上传、未 commit 或 push。

### 过期发布记录不再阻塞后续上传（2026-08-21）

- 实际工作区的奇迹时代 4 队列项关联 `04:14` 创建的旧发布记录，而本地发布产物于 `10:45` 重建；预检准确检测到旧记录冻结的 SHA-256 / 修改时间与当前文件不一致，并非刚构建产物必然损坏。若已完成构建，应从构建队列再次点击“加入上传队列”以替换旧记录，无需重复构建。
- 队列现在允许跳过前序 `failed` / `needs_rebuild` 项，继续上传后面仍为 `queued` 的游戏；只有尚待处理、运行中或用户主动暂停的前序项保留 FIFO 阻塞。失败提示改为明确指向“旧发布记录不一致”和重新加入路径。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest -q tests\test_publisher_upload_queue.py tests\test_publisher_ui_threading.py tests\test_publisher_content_pipelines.py`（85 项通过）、对应 Ruff、` .\.venv\Scripts\python.exe -m compileall -q src\signriver_publisher` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未启动 GUI、未构建 EXE、未执行真实上传、未 commit 或 push。

### 重建自动更新已有上传队列项（2026-08-21）

- 运行时持久化时间使用 UTC；用户界面操作日志为本地北京时间。因而构建记录 `10:45 UTC` 与日志 `18:45` 是同一时刻，不能误判为早上旧构建；此前对应的旧发布计划 `04:14 UTC` 才是北京时间 `12:14` 的过期记录。
- 当游戏已经存在活动上传队列项（包括 `needs_rebuild`）时，该游戏完成新的本地构建会自动把队列项更新为最新构建、清空旧 Release ID。下一次开始上传将创建新发布记录；若上传正在进行，现有安全步骤结束后会自动改传最新构建。没有既有上传项时，构建仍不自动加入上传队列。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest -q tests\test_publisher_ui_threading.py tests\test_publisher_upload_queue.py tests\test_publisher_content_pipelines.py`（86 项通过）、对应 Ruff、` .\.venv\Scripts\python.exe -m compileall -q src\signriver_publisher` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未启动 GUI、未构建 EXE、未执行真实上传、未 commit 或 push。

### 过期上传项“使用当前构建”即时修复（2026-08-21）

- 已存在的 `needs_rebuild` 项不可能由之后新增的“构建完成自动替换”逻辑回溯修复。上传队列卡片现在为该状态提供“使用当前构建”按钮：仅当构建队列存在同游戏的 `completed` 项时，按钮才将该上传项替换为当前构建、清空旧 Release ID 并重新变为 `queued`；没有已完成构建则明确提示先构建。
- 用户工作区的奇迹时代 4 旧项已通过同一队列 API 修复：状态为 `queued`、关联旧 Release ID 已清空、保留当前构建的 19 个文件和 7.6 MiB；下一次开始上传会创建新发布记录。
- 验证（2026-08-21）：` .\.venv\Scripts\python.exe -m pytest -q tests\test_publisher_ui_threading.py tests\test_publisher_upload_queue.py tests\test_publisher_content_pipelines.py tests\test_publisher_operation_log.py`（88 项通过）、对应 Ruff、` .\.venv\Scripts\python.exe -m compileall -q src\signriver_publisher` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未启动 GUI、未构建 EXE、未执行真实上传、未 commit 或 push。

### 修复内容发布失败记录被反复复用（2026-08-21）

- 用户确认“使用当前构建”是无效旁路。真实根因是 `find_reusable_game_content_batch()` 把 `preflight_failed` 的旧记录继续当成可复用记录，却没有核对其中冻结的附件指纹。上传项清空 Release ID 后，下一次执行仍会重新捡回同一份旧记录，所以再次误报需要重新构建。
- 奇迹时代4现场旧记录 `51b96a…` 创建于 `04:14 UTC`，其中 AppInfo SHA-256 为 `cab132…`；当前构建的 AppInfo SHA-256 为 `5fd809…`。构建本身有效，失败来自旧快照复用。
- 内容发布记录现在只有在全部冻结产物仍与当前文件一致时才会复用；任何路径、大小、修改时间或 SHA-256 变化都会跳过旧记录并由当前发布目录创建新记录。上传前若文件在新快照创建后真实变化，预检仍会安全失败。
- 已从上传队列移除“使用当前构建”按钮、处理方法及 `BuildQueueStatus` 依赖，不再提供绕过失败状态的假修复。
- 验证：专项 ` .\.venv\Scripts\python.exe -m pytest -q tests\test_publisher_release_service.py tests\test_publisher_ui_threading.py tests\test_publisher_upload_queue.py tests\test_publisher_content_pipelines.py tests\test_publisher_operation_log.py` 通过（103 项）；真实工作区只读检查确认奇迹时代4旧记录返回 `reusable_batch=None`；全量 ` .\.venv\Scripts\python.exe -m pytest -q` 通过（736 项），全项目 Ruff、`compileall -q src app\versions\0.1.0 tools tests` 与 `git diff --check` 通过（仅 CRLF 提示）。未启动 GUI、未构建发布器 EXE、未执行真实上传、未 commit 或 push。

### 修复大文件上传时阶段记录固定触发 WinError 5（2026-08-21）

- Victoria 3 在 `dlc004_voice_of_the_people.zip.part001-of-002` 处显示“上传失败”，但完整错误为发布批次目录内 `.stages.json.<pid>.tmp -> stages.json` 的 `[WinError 5] 拒绝访问`；前三个附件已上传并持久化成功，280 MiB 分卷本身也能读取。失败点是本地恢复检查点，不是网络或发布分卷。
- 根因：上传进度回调高频 `ReleaseStore.save()`，UI 每 350 ms `load()` 同一批次；旧存储层无读写协调，Windows 的短暂读取句柄会阻止目标文件被 `os.replace()`。同时临时文件名只含 PID，同进程并发保存还会争用同一个临时文件。
- `ReleaseStore` 现在用 `RLock` 串行化整批多文档保存、加载和事件追加；每次原子 JSON 写入使用 UUID 唯一临时文件；`os.replace()` 遇到 `PermissionError` 最多进行 4 次短暂指数退避尝试，持续失败仍正常上抛并清理临时文件。
- 新增回归覆盖前两次原子替换被拒后恢复成功，以及上传进度保存与 UI 轮询共 90 次交错读写。专项 ` .\.venv\Scripts\python.exe -m pytest -q tests\test_publisher_release_batches.py tests\test_publisher_release_service.py tests\test_publisher_content_pipelines.py tests\test_publisher_upload_queue.py tests\test_publisher_ui_threading.py tests\test_publisher_operation_log.py tests\test_publisher_release_providers.py` 通过（137 项）；全量 pytest 通过（738 项），全项目 Ruff、`compileall -q src app\versions\0.1.0 tools tests` 与 `git diff --check` 通过（仅 CRLF 提示）。
- 当前 Victoria 3 队列项保留 `failed` 状态和原发布记录 `fd9dd5…`，未重置、删除或重建。重启最新源码发布器后直接点击“重试”；流水线会按已保存的远端附件 ID 沿用前三个成功附件，并对第四个附件先做结果未知恢复判断。未启动 GUI、未构建发布器 EXE、未执行新的真实上传、未 commit 或 push。

### 全游戏静态目录补丁别名紧急兼容（2026-08-21）

- 根因：群星 Release 虽保留 `steam_api64.dll` 与 `steam_api64_o.dll`，但发布器生成的 `catalog.json` 只列稳定名 `unlocker.dll` / `original.dll`。采用静态目录的旧客户端因而看不到旧名补丁；不能把“保留云端仅有附件”当作静态目录兼容。
- 发布器现在以全局生命周期策略处理所有游戏：默认开启时，构建会从稳定名生成该游戏卡带声明的两份旧 DLL 名别名，并纳入构建清单与 `catalog.json`；新客户端仍使用稳定名，旧客户端可继续按旧名发现同一内容。构建队列提供“旧版补丁名兼容”全局开关，未来关闭后对之后重建的所有游戏同时生效。
- 已执行真实双源紧急修复：发布批次 `531ed31fa5c545008431b54d0296653d` 仅上传两份别名并最后切换 `catalog.json`，兼容模式保留全部既有云端附件。GitLink 与 GitHub 均完成；公网读取确认两端目录均列出 `unlocker.dll`、`original.dll`、`steam_api64.dll`、`steam_api64_o.dll` 和 `stellaris_appinfo.json`。
- 验证：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_workspace.py tests\test_publisher_ui_threading.py -q`（143 项通过）、对应 Ruff、`compileall -q src\signriver_publisher` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未构建发布器 EXE、未 commit 或 push。

### 上传队列故障态可暂停与自动解除占用（2026-08-21）

- 根因：上传队列在远端预检期间已显示“正在上传”，但关联发布记录仍可能是 `draft`；网络异常后记录还可能先变为 `failed`，而 UI 回调尚未回来。旧暂停 API 只接受 `running`，因此故障场景点击暂停会弹出英文内部错误并永久占用关闭锁。
- 暂停请求现在覆盖整个未完成生命周期。处于真实附件传输的 `running` 记录仍由安全检查点中断；预检、失败、降级或中断记录会立即持久化暂停请求，队列同步标为“已暂停”并释放后台占用。延迟到达的成功/失败回调不会覆盖该暂停状态。
- 队列每 350 ms 轮询持久化发布记录；一旦检测到记录已离开 `running`（暂停、失败、降级、中断或完成），立即同步队列终态并解除窗口关闭锁，不再吞掉异常后无限显示“正在上传”。
- 验证：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_release_batches.py tests\test_publisher_upload_queue.py tests\test_publisher_ui_threading.py -q`（173 项通过）、对应 Ruff、`compileall -q src\signriver_publisher` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未启动发布器、未执行真实上传、未构建 EXE、未 commit 或 push。

### 构建队列显式批量构建（2026-08-21）

- 构建队列顶部新增“全部加入构建队列”和“开始全部构建”。前者按当前所有游戏的本地资源创建或更新构建请求；后者才会按 FIFO 串行执行全部待构建项。
- DLC / 补丁发布页原有的单游戏“加入构建队列”保留，但现在只入队、不再隐式开始构建。构建完成或失败后仅在同一次“开始全部构建”会话中继续处理下一项；重启后不会自行续跑，需用户再次明确点击开始。
- 验证：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_upload_queue.py tests\test_publisher_ui_threading.py -q`（76 项通过）、` .\.venv\Scripts\python.exe -m ruff check src\signriver_publisher\content_management_ui.py tests\test_publisher_ui_threading.py`、`compileall -q src\signriver_publisher\content_management_ui.py` 与 `git diff --check` 通过。未启动 GUI、未构建 EXE、未执行真实上传、未 commit 或 push。

### 发布页小窗口纵向滚动（2026-08-21）

- DLC / 补丁发布页现在作为可滚动的页面路由容器创建；窗口高度不足时可滚动查看“当前文件传输”及其进度条。操作日志内部原有滚动保持不变。
- 验证：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_ui_threading.py -q`（65 项通过）、` .\.venv\Scripts\python.exe -m ruff check src\signriver_publisher\ui.py tests\test_publisher_ui_threading.py`、`compileall -q src\signriver_publisher\ui.py` 与 `git diff --check` 通过。未启动 GUI、未构建 EXE、未执行真实上传、未 commit 或 push。

### 构建与上传缓存命中说明（2026-08-21）

- DLC 构建日志现在先写“检查构建缓存”，随后明确显示“构建缓存命中（未重新压缩）”、旧版本 ZIP 被接管或“构建缓存未命中（将重新压缩）”；AppInfo 与补丁也明确说明其每次刷新/整理、不走该构建缓存。
- 远端预览和上传日志统一使用“云端缓存命中”说明可信 DLC 附件被复用而未重复上传，并保留上传响应恢复、同批继续上传等不同于缓存的原因。
- 验证：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_workspace.py tests\test_publisher_ui_threading.py tests\test_publisher_upload_queue.py -q`（159 项通过）、对应 Ruff、`compileall -q` 与 `git diff --check` 通过。未启动 GUI、未构建 EXE、未执行真实上传、未 commit 或 push。

### 批量上传队列启动不阻塞界面（2026-08-21）

- 根因：由“全部加入上传队列”产生的项起初没有 `release_id`。开始队列时旧 UI 在 Tk 回调内同步写入运行状态并立即轮询空发布记录；当 Windows 文件检查点短暂被占用时，按钮回调会失去响应。
- FIFO 运行状态的持久化、首项本地发布快照、远端差异预检仍在同一后台工作线程内；Tk 仅在持久化成功后刷新卡片。快照尚未生成 Release ID 时不再轮询空记录，因此“开始队列”立即返回界面事件循环。
- 此新增准备阶段也可暂停：暂停会保持原队列项为 `paused`、不读写远端；迟到的快照线程会丢弃结果，不能把暂停项改回运行。

### 修复卡带中心双端发布引用已删除控件（2026-08-22）

- 根因：模块化发布器已将发布目标配置迁移到 `PublisherSettings`，但“一键双端发布卡带”仍调用继承自旧 UI 的 `_save_active_settings()`；该实现读取已不存在的 `owner_entry`、`repo_entry`、`token_entry`，点击后在网络操作开始前触发 Tk `AttributeError`。
- `PublisherTargetsUiMixin` 现在覆盖该兼容保存钩子，只持久化当前 `self.settings`；卡带双端发布以及仍复用该钩子的现代界面操作不再依赖旧输入框。未触发真实远端发布。
- 后续实测还触发旧 `_set_publish_buttons_available()`，它同样会访问已删除的 `publish_button`。该兼容方法现只更新模块化界面实际存在的 `hub_publish_button`，覆盖双端发布开始、成功和失败时的按钮恢复路径。
- 已在模块化 MRO 中显式隔离未接线的旧单源发布、模块归档、单源卡带发布和“采用远端附件”方法；即使后续有误调用，也只显示“入口已移除”，不会再回落访问 `owner_entry`、`publish_button` 等已删除控件。唯一保留的发布范围是当前 UI 实际接线的卡带双端镜像范围；其暂停/恢复仍使用 `hub_publish_*` 控件。
- 卡带列表摘要也已改为直接读取 `PublisherSettings`，不再在模块化 UI 中探测旧仓库输入框。
- 验证（2026-08-22）：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_ui_threading.py tests\test_publisher_workspace.py tests\test_publisher_upload_queue.py tests\test_publisher_release_batches.py -q`（191 项通过）、`compileall -q src\signriver_publisher` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未启动 GUI、未构建 EXE、未执行真实上传、未 commit 或 push。

### 上传队列重试自动解除旧暂停（2026-08-22）

- 根因：故障态点击暂停会按设计保留内存和持久化的暂停请求。旧“重试”没有清除该请求，第一次点击会立即再次进入暂停并在执行收尾时才清理，因此用户必须再点一次。
- 现在上传队列在同一次“重试/继续”的后台启动中，先清除该发布记录遗留的暂停请求及恢复字段，再进入远端预检和执行；操作日志会明确记录“已解除上次暂停留下的执行锁，直接开始重试”。
- 验证（2026-08-22）：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_release_batches.py tests\test_publisher_upload_queue.py tests\test_publisher_ui_threading.py -q`（105 项通过）、对应 Ruff、`compileall -q src\signriver_publisher` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未启动 GUI、未构建 EXE、未执行真实上传、未 commit 或 push。

### GitLink 大文件停滞超时与安全暂停（2026-08-22）

- 实际上传队列中仅 Victoria 3 的 `dlc010_ep1.zip.part001-of-002` 失败，界面显示“上传超时”。GitLink 附件客户端原先将任一次 socket 无进展限制为 20 秒；这不是整个文件的总时长，但对大分卷的服务端接收间歇或上传完成后的响应等待过于激进。
- 附件上传的无进展超时已调整为 90 秒。暂停不再依赖短超时：`UploadControl.request_pause()` 会立即关闭已登记的活动 HTTPS 连接，使阻塞的发送或响应读取尽快以可恢复的 `UploadPaused` 结束。
- 验证（2026-08-22）：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_workspace.py tests\test_publisher_ui_threading.py tests\test_publisher_upload_queue.py -q`（161 项通过）、` .\.venv\Scripts\python.exe -m ruff check src\signriver_publisher\gitlink.py tests\test_publisher_workspace.py`、`compileall -q src\signriver_publisher\gitlink.py` 与 `git diff --check` 通过（仅既有 CRLF 提示）。未启动 GUI、未构建 EXE、未执行真实上传、未 commit 或 push。
- 验证：` .\.venv\Scripts\python.exe -m pytest tests\test_publisher_release_batches.py tests\test_publisher_upload_queue.py tests\test_publisher_ui_threading.py -q`（104 项通过）、对应 Ruff、`compileall -q src\signriver_publisher\upload_queue_ui.py` 与 `git diff --check` 通过。未启动 GUI、未构建 EXE、未执行真实上传、未 commit 或 push。

### 0.2.0 SteamOS / macOS 原生构建与关键验收（2026-08-22）

- SteamOS x64：在 `/mnt/games/signriver-src-20260822` 使用 `/home/deck/venv/bin/python` 成功构建 `SignRiver-DLC-Hub-v0.2.0-steamos-x64.tar.gz`（SHA-256：`b29badab9a96c75f5d944851232595b488cf15b74fb1b1525d8a87437d4ff2bb`）和 `SignRiver-DLC-Hub-full-v0.2.0-steamos-x64.zip`（SHA-256：`2f46d85d67a46d04ebbf62c3819afe2477eb3402910dbc482133b58940065620`）。ELF x86-64、包结构与 ZIP 完整性均验证通过；冻结程序在隔离 XDG 目录中启动存活后正常停止。
- macOS Intel：系统仅有 Python 3.9，不能导入源码所需的 `enum.StrEnum`。已在 `/tmp/py312` 解压 Python Build Standalone 3.12.14（不修改系统、不需管理员权限），安装构建依赖后构建成功；首次交付格式为 `dist/SignRiver-DLC-Hub.app`（不是 DMG），更新包为 `dist/updates/SignRiver-DLC-Hub-full-v0.2.0-macos-x64.zip`（SHA-256：`a7fb2d1cbb8e7270dcbddd62690c055b22500946362f867c5d5aec9ab4d21a5f`）。应用二进制为 macOS 原生可执行文件，更新 ZIP 完整性通过；冻结应用在隔离 `HOME` 下存活 8 秒后被正常停止。
- 两端均通过跨平台/补丁和更新恢复关键测试。SteamOS：`tests/test_update_config.py tests/test_updater.py tests/test_full_update.py tests/test_patch_engine.py tests/test_patch_platforms.py`（79 通过、1 跳过）；macOS：再加 `tests/test_macos_update_helper.py`，共 100% 通过。此前两端的 `test_cross_platform_runtime.py`、`test_patch_platforms.py`、`test_build_native_release.py` 也通过；macOS 同时通过 Ruff 和 compileall。
- 未上传任何构建产物、未执行线上发布、未提交或推送。Windows 工作区仅有既有未提交改动与本次 SteamOS 配置文档改动；macOS / SteamOS 构建资源均保留在各虚拟机临时目录。后续如需正式发布，须由用户自行将相应平台包上传至双源并更新清单，之后再按项目流程提交/推送。

### SteamOS 根目录扩容与 KDE 桌面测试模式（2026-08-22）

- 变更前已创建 VirtualBox 快照 `before-btrfs-system-expansion-20260822`。`games` 数据盘保持 128 GiB 动态上限不变；它不会预占全部容量，当前仍约有 75.5 GiB 可用。
- 新增动态 VDI `SteamOS-root-extension-5g.vdi`（5 GiB），在 Guest 中建立 `/dev/sdc1` 并加入根 Btrfs。冷启动验证后根文件系统总容量约 10 GiB、已用约 4.3 GiB、可用约 5.2 GiB，占用率从 98% 降至 46%；Btrfs 两个设备均可被 initramfs/udev 自动识别。新 VDI 当前宿主实际占用约 2 MiB，后续按写入量动态增长。
- 已禁用开机独占显示器的 `signriver-client.service`、`signriver-resolution.service`、`signriver-xorg.service`，保留并启用 `sddm.service`。重启后 `deck` 自动进入 KDE Plasma Wayland，`kwin_wayland`、`Xwayland`、`plasmashell` 均正常，分辨率持久化为 `1600x900`、缩放 100%。
- 桌面新增可执行且通过 `desktop-file-validate` 的 `SignRiver-DLC-Hub.desktop`，从 `/mnt/games/signriver-src-20260822` 使用 `/home/deck/venv/bin/python` 启动源码客户端。按桌面会话环境实测程序持续运行并加载模块 0.2.0；测试时发现 `/home/deck/data/cartridges/cartridge_stellaris.json` 是缺少 macOS 字段的旧本地卡带，程序会忽略该文件，尚未删除或覆盖。
- KDE 与 SignRiver 同时运行时 8 GiB 内存仍有约 6.4 GiB available、Swap 为 0，连续 `vmstat` 采样 CPU idle 约 99%–100%。Host-Only 地址仍为 `192.168.56.2/24`，NAT 默认路由保持不变。未改项目代码、未构建、未上传、未 commit 或 push。

### macOS 用户应用更新（2026-08-22）

- 使用当前仓库已提交源码在 macOS Intel 虚拟机原生重建客户端；因 `0.2.0/module.json` 属于本地生成元数据且未进入 Git 归档，仅在 macOS 临时构建目录补齐，未修改 Windows 工作区。
- 已将新构建的 `~/Applications/SignRiver-DLC-Hub.app` 替换旧应用，并保留备份 `SignRiver-DLC-Hub.before-current-build-20260822.app`。应用内 `app/state.json` 的 `active_version` 为 `0.2.0`。
- 通过 `open` 启动后确认应用进程存活（LaunchServices 状态正常），未执行下载、Steam 操作、上传、发布、commit 或 push。构建产物仍保留在 macOS `~/Downloads/SignRiver-DLC-Hub-current-20260822/dist/`。

### macOS 冻结包 SQLite 依赖修复（2026-08-22）

- macOS 首次替换后的应用弹出 `Unable to import application module: No module named 'sqlite3'`。构建环境 Python 可正常导入 SQLite，根因是 PyInstaller 对动态加载的运行时模块未显式收集标准库 `sqlite3` 与平台扩展 `_sqlite3`。
- `tools/build_release.py` 的通用隐藏导入列表已加入 `sqlite3`、`_sqlite3`；专项构建测试通过（9 项）。在 macOS 重新原生构建并替换应用，保留 `SignRiver-DLC-Hub.before-sqlite-fix-20260822.app` 备份。
- 修复后通过 `open` 启动，LaunchServices 与应用进程均保持运行，未执行下载、上传、发布、commit 或 push。

### macOS 应用包缺少 0.2.0 运行时代码修复（2026-08-22）

- 用户启动 macOS 桌面程序时出现 `Unable to import application module: No module named 'concurrent'`（`APP-MODULE-LOAD-FAILED`）。根因不是 Python 标准库缺失，而是此前用 `git archive HEAD` 同步源码时，`app/versions/*` 被 `.gitignore` 忽略，导致应用包中的 `runtime/app/versions/0.2.0` 只有 `module.json`，没有完整的 `signriver_app/` 运行时代码。
- 已从 Windows 工作区打包完整的本地 `app/versions/0.2.0`，同步到 macOS 临时构建目录，并在 macOS Intel 虚拟机原生重新构建 `SignRiver-DLC-Hub.app`。新包已确认包含 `signriver_app/application/download_queue.py` 等完整模块。
- 已停止旧应用并替换 `/Users/signriver/Applications/SignRiver-DLC-Hub.app`。启动等待 8 秒后进程持续运行，`active_version` 为 `0.2.0`，未出现新的 SignRiver 崩溃报告；临时备份随后删除，应用目录只保留最新版。
- 本次未修改 Windows 源码、未上传、未发布、未 commit 或 push；未执行 Steam、下载或更新操作。

### SteamOS / macOS 原生客户端构建项目 Skill（2026-08-22）

- 新增项目技能 `.agents/skills/build-native-client-releases/`，用于从 Windows 当前工作区准备完整源码，并在 SteamOS x64、macOS Intel x64 虚拟机中原生构建和验证首次安装包与全量更新包。
- `SKILL.md` 统一规定版本元数据、目标版本目录完整性、用户未提交改动保护、禁止单独使用 `git archive HEAD`、不隐式上传/发布/commit/push，以及包结构、架构、SHA-256、8 秒启动存活和模块回退检查。
- SteamOS 与 macOS 的具体命令和验收分别放在 `references/steamos.md`、`references/macos.md`；macOS 流程额外覆盖 `.app` 内运行时完整性和用户可写 `state.json`/`bad_versions` 回退状态。
- 验证：Skill Creator 官方 `quick_validate.py` 在 `PYTHONUTF8=1` 下通过；`SKILL.md` 与 `agents/openai.yaml` 的 UTF-8/YAML 解析通过；无 TODO 占位符，`git diff --check` 通过。未实际构建、未连接虚拟机、未上传、未发布、未 commit 或 push。

### 客户端补丁-only Release 仍允许安装补丁（2026-08-22）

- 修复客户端目录刷新逻辑：当云端 Release 只有完整补丁资源、没有任何 DLC ZIP 时，不再把“一键解锁”按钮误置为“暂无可用 DLC”并禁用；按钮会保持可用，点击后可直接下载/应用补丁。
- 当补丁资源也缺失时仍保持禁用，并显示目录与补丁均不可用的提示；有 DLC 的原有流程不变。
- 修改范围：`app/versions/0.1.0/app_entry.py`，新增源代码回归断言 `tests/test_ui_theme.py::test_patch_only_release_keeps_unlock_button_available`。
- 验证：`pytest -q tests/test_ui_theme.py -k "patch_only_release or catalog_assigns_entries"`（2 项通过）；`python -m py_compile app/versions/0.1.0/app_entry.py` 通过。完整 `tests/test_ui_theme.py` 未全通过，存在工作区既有发布器编码相关失败 `test_bulk_management_speed_test_and_complete_task_cleanup_are_available`，与本次客户端改动无关。
- 未同步忽略的发布版本目录、未构建、未上传、未 commit 或 push。

### 客户端 GitLink 切换 GitHub 失败回滚、乱码与 0.2.0 启动修复（2026-08-22）

- 下载源从 GitLink 切换到 GitHub 且远端主表、本地缓存均加载失败时，现在会恢复原设置，并回滚更新器、卡带主表、公告服务和下拉框；默认卡带兜底异常保留真实失败原因，不再显示 `????????????stellaris`。
- 后续源码启动失败并非 `config/cartridges` 文件缺失：启动器隔离加载确认，本地忽略目录 `app/versions/0.2.0/signriver_app/domain/cartridges.py` 仍只接受旧字段 `original_backup_dll_name`，而当前卡带已经使用 `runtime_original_library_name`，导致所有本地卡带被旧解析器拒绝，启动器再回退到同样不兼容的 `0.1.7`。
- 已保留 `0.2.0` 自身较新的运行时实现，仅在其 `domain/cartridges.py` 增加新字段优先、旧字段回退的兼容映射；没有用 `0.1.0/signriver_app` 整目录覆盖活动版本。`app/state.json` 已恢复为活动版本 `0.2.0`，`previous_version` 为 `0.1.7`，并清空 `bad_versions`。
- 验证：跟踪源码卡带测试 `tests/test_cartridge_catalog.py tests/test_cartridge_default_fallback.py` 共 13 项通过；通过 `ModuleLoader._load_python_module()` 隔离加载 `0.2.0`，Windows、SteamOS、macOS 三个平台均能从本地加载默认 `stellaris`；按启动器真实 `HostContext` 完整创建 `DlcHubApplication` 成功，随后主动销毁隐藏窗口，无残留客户端进程；`compileall -q app/versions/0.2.0` 通过。
- 未构建更新包、未上传、未执行真实 GitLink/GitHub 写操作、未 commit 或 push。`0.2.0` 是 Git 忽略的本地目标目录；正式交付仍需按发布流程选择性同步并重新构建目标版本，不能把此次本地运行时修补误认为已发布。

## 2026-08-22：多端卡带资源筛选与云端报错指南

- 客户端卡带主表新增 `platform_resources`；当前平台只要补丁或 DLC 任一已发布就显示。补丁-only 的内置 DLC 游戏（如《文明 VII》）保持可见，历史主表缺该字段时只兼容 Windows，避免把旧 Windows 资源展示给 SteamOS/macOS。
- 发布器现在导出云端确认的资源状态：已成功发布记录只能保守确认 Windows；SteamOS/macOS 必须在游戏卡带的“已发布平台资源 (JSON)”中明确标为可用。该状态与平台变体声明分离，未上传资源不会因声明而显示。
- 报错指南使用独立 hub 主表与按条目详情；通用指南跨平台显示，脚本工具仅在适用平台显示并按需 HTTPS 下载，用户确认后执行。下载使用临时文件原子替换；不引入额外签名或复杂哈希体系。
- 验证（2026-08-22）：`pytest -q tests/test_platform_content.py tests/test_publisher_content_pipelines.py tests/test_cartridge_catalog.py tests/test_cartridge_default_fallback.py`（35 通过）；`pytest -q tests/test_publisher_ui_threading.py`（69 通过）；`pytest -q tests/test_ui_theme.py -k "patch_only_release or catalog_assigns_entries or active_cartridge_switch"`（3 通过）；`python -m compileall -q app/versions/0.1.0 src`、相关 `ruff check`、`git diff --check` 通过。未同步忽略的 `app/versions/0.2.0`，未构建、未上传、未推送。


### 下载源切换成功提示延后（2026-08-22）

- 下载源切换后，客户端现在先显示“正在重新加载”，只有 Hub 主表和当前默认卡带完成加载、游戏扫描与 DLC 列表刷新后，才提示“下载和程序更新源已切换为 GitHub，卡带已重新加载”。
- 远程主表或卡带只能回退本地缓存时，不再显示成功提示，改为明确的缓存回退警告；原有切换失败回滚逻辑未改变。
- 验证（2026-08-22）：`pytest -q tests\test_ui_theme.py -k "download_source or patch_only_release or active_cartridge_switch"`（5 通过）；`pytest -q tests\test_cartridge_catalog.py tests\test_cartridge_default_fallback.py tests\test_platform_content.py`（21 通过）；后续同步发布器滚动发布页对应断言后，完整 `pytest -q`、相关 Ruff、`compileall` 与 `git diff --check` 均通过。未启动 GUI、未构建、未上传、未推送。

### 一键排错理念已固化为长期决策（2026-08-22）

- 已将“一键排错只做内置非破坏性检查、三端共用通用项、Windows 渐进扩展、SteamOS/macOS 保持简单可靠、修复工具按平台按需下载并经用户确认”的完整理念写入 `docs/agent/DECISIONS.md`，后续 AI 读取长期决策即可获得一致约束。
- 本次仅更新项目记忆，未修改客户端、未构建、未上传、未推送。

## 2026-08-22：报错指南通用化内容筛选参考目录

- 已新增 `docs/error-guide-content-catalog.md`，以桌面 `群星报错指南2026.7.20.docx` 的 `P0000`–`P0619` 为来源，完整覆盖 8 个一级主题和 75 个二级主题；每项都记录来源段落、旧方案摘要、唯一主结论与未来程序落点。
- 文档已将可复用内容拆为通用指南、Hub/DLC 工作流、游戏/启动器特化、一键排错和排除/待验证五类；明确排除学习版、联机加速器、SteamCMD/创意工坊、自动关闭防护、系统设置自动修改、未知脚本与散装 DLL 下载。
- 一键排错参考表固定为网络目录、游戏目录、磁盘空间、适用补丁审计、近期问题记录及两个未实现研究项；所有检查保持只读并以固定指南跳转，不执行修复。
- 验证（2026-08-22）：使用 `python-docx` 读取源 DOCX，断言 8 个一级主题、75 个二级主题均在目录中出现，并断言筛选原则、来源盘点、一键排错、未来内容模型和验收章节存在；`git diff --check` 通过。未运行 pytest（仅文档改动），未启动 GUI、未构建、未上传、未推送。
- 后续实现时应先按目录的 P0/P1/P2 队列，为云端指南 schema、稳定问题码、卡带过滤和 UI 跳转单独制定实现计划与测试，不得把本参考目录当作已上线功能。
