# 当前任务交接

> 最后更新：2026-08-19（Asia/Shanghai）
> 分支：`main`
> HEAD：`9f402e3`（`feat(client): 优化设置页与游戏选择体验`）
> 上游状态：`main` 相对 `origin/main` 领先 5、落后 0；本轮仅更新交接与决策文档，禁止自动提交或推送。
> 工作区：`app/versions/0.1.0/app_entry.py`、`tests/test_ui_theme.py` 有未提交的客户端启动修复；`app/versions/0.2.0/` 是被忽略的活动发布目录，已同步该修复。另有发布器 UI 与交接文档的既有未提交改动，必须保留。未读取、展示或修改 `config/publisher.local.json`，未进行真实发布、上传或远端写入。

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
