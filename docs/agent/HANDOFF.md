# 当前任务交接

## 2026-08-29：整理并提交待处理改动

- 已核对并提交当前工作区待处理的客户端状态、指南索引与 `paradox-launcher-crash-null` 指南资源，以及交接/决策记录。
- 验证：`python -m pytest -q tests/test_platform_content.py tests/test_ui_theme.py`（全部通过）、`python -m ruff check .`、`git diff --check` 通过；未执行构建、上传或推送。
- 实际活动版本为 `0.2.0`；本次未修改版本切换配置，用户查看客户端界面前如进程未重启需重启。

## 2026-08-29：移除图形兼容性自动检测

- 根据实际验证，Windows 11 `dxdiag /t` 无法稳定提供指南所需的加速结论；已从一键排错队列移除图形兼容性检查。
- 图形设备工具不再自动诊断，仅提供打开 `dxdiag.exe`、用户确认后修改固定注册表值、恢复备份；指南改为人工查看“显示”页后再跳转工具。
- 基线 `0.1.0` 已同步活动版本 `0.2.0`；平台内容/UI/图形定向测试、编译、Ruff、空白检查通过。未执行注册表写入、GUI人工验收、构建、上传或推送。

## 2026-08-29：适配 Windows 11 dxdiag 新版文本结构

- 本机实际运行活动版本 `0.2.0` 诊断：dxdiag 约 16 秒成功生成 183KB 文本，但新版输出不包含传统 DirectDraw/Direct3D 加速行；新增显卡 `Card name` 识别，将该情况显示为“未提供传统加速字段”而非 `unknown`。
- 当前真实结果为 `graphics_acceleration_ok`，注册表四项均未设置（使用系统默认值）；基线与活动模块已同步。定向测试、编译、Ruff 和空白检查通过，未执行修复写入或 GUI 人工验收。

## 2026-08-29：修正 dxdiag 状态为 unknown

- 扩大 DirectDraw/Direct3D 状态解析，兼容全角冒号、中文状态文本及无 BOM/含空字节的诊断输出；保留 60 秒超时和自动重试一次策略。
- 基线与活动版本 `0.2.0` 已同步。定向图形兼容性、平台内容、UI 测试及编译/Ruff/空白检查通过；需重启客户端加载。未执行真实 dxdiag、GUI、构建、上传或推送。

## 2026-08-29：优化图形设备 dxdiag 检测重试

- `dxdiag` 超时上限由 20 秒调整为 60 秒；超时、非零退出或未生成文件会清理临时输出并自动重试一次，错误信息明确标识超时/失败原因；同时兼容 UTF-8 与 UTF-16 输出。
- 图形设备详情页的“重新检测”现在会真正启动后台诊断；基线与活动版本 `0.2.0` 已同步，需重启客户端加载。
- 验证：`tests/test_graphics_compatibility.py tests/test_platform_content.py tests/test_ui_theme.py` 全部通过；两个模块编译、Ruff、`git diff --check` 通过。未执行 GUI 人工验收、真实 dxdiag、构建、上传或推送。

## 2026-08-28：接入 Windows 图形设备兼容性诊断与修复

- 基线 `0.1.0` 新增固定四项 DirectDraw/Direct3D 注册表读取、`dxdiag` 状态解析、管理员确认后的备份/修复/回滚服务；一键排错增加后台图形兼容性检查，常用工具增加“图形设备兼容性”详情页。
- 新增 Windows 指南、错误截图资源及工具/UI规范说明；活动版本 `0.2.0` 已定向同步 `app_entry.py`、`guides.py` 和图形兼容性模块，需重启客户端加载。
- 验证：图形兼容性/平台内容/UI 定向 pytest、两个模块 `py_compile`、基线 Ruff 均通过；问题中心仍有工作区既有的 2 项失败（补丁结果字段与返回参数断言），未修改相关逻辑；未执行 GUI、真实注册表写入、构建、上传或推送。

## 2026-08-28：新增 P 社启动器警告与 Steam 通讯错误指南及工具

- 新增 Windows 指南 `paradox-launcher-dlc-warning` 与 `paradox-launcher-steam-error`，加入用户提供的三张演示图和工具跳转。
- 常用工具新增内置“P 社启动器警告清除”和“P 社启动器安装工具”；前者检查运行进程、定位最新完整版本并替换目标 DLL，后者下载官网安装程序、打开安装程序/下载目录并支持卸载本地安装包。
- 基线 `0.1.0` 已同步活动版本 `0.2.0`；指南/UI 定向测试、编译、Ruff 和 `git diff --check` 已通过。未执行真实启动器文件替换或官网下载安装。

## 2026-08-28：接通指南与最新安装包工具往返跳转

- 从指南进入“下载最新安装包”工具时保存当前指南；工具详情返回按钮回到原指南，常用工具列表直接进入时仍返回常用工具列表。
- 基线 `0.1.0` 与活动版本 `0.2.0` 已同步；编译、Ruff、UI/平台定向测试和 `git diff --check` 均通过。

## 2026-08-28：标记最新安装包工具为已就绪

- “下载最新安装包”详情页顶部状态固定显示“已就绪”，表示工具本身可用；下载包状态仍在正文区域单独展示。
- 基线 `0.1.0` 与活动版本 `0.2.0` 已同步；编译、Ruff、UI/平台定向测试和 `git diff --check` 均通过。

## 2026-08-28：完善最新安装包工具说明

- 工具详情说明补充程序更新报错时的备用用途、下载完成后打开文件夹、将压缩包放到任意位置解压即可继续使用的操作步骤。
- 基线 `0.1.0` 与活动版本 `0.2.0` 已同步；编译、Ruff、UI/平台定向测试和 `git diff --check` 均通过。

## 2026-08-28：补齐最新安装包工具操作日志

- 最新安装包工具现记录读取清单、找到版本/文件名、下载完成、下载失败和打开下载文件夹等操作到小日志；原始异常仍只写入详细日志。
- 基线 `0.1.0` 与活动版本 `0.2.0` 已同步；编译、Ruff、UI/平台定向测试和 `git diff --check` 均通过。

## 2026-08-28：新增最新安装包下载工具

- 常见问题指南中的 GitLink/GitHub 直链改为进入“下载最新安装包”工具。
- 客户端新增独立工具：按当前下载源读取更新清单，选择最新 Windows full 安装包并下载到 `latest-installers` 文件夹，提供打开文件夹按钮；不调用程序自动更新流程。
- 基线 `0.1.0` 已同步活动版本 `0.2.0`；UI/平台测试、编译、Ruff 和 `git diff --check` 均通过。未执行真实网络下载和 GUI 人工验收。

## 2026-08-28：修复问题记录解决方案返回路径

- 从问题记录打开解决方案时保存问题记录事件 ID；返回解决方案后回到“问题记录”并重新打开同一条记录。
- 原有一键排错/普通解决方案入口仍使用各自的返回来源，不受影响。基线 `0.1.0` 已同步活动版本 `0.2.0`；编译、Ruff、UI/平台定向测试和 `git diff --check` 均通过。

## 2026-08-28：完善程序更新异常指南

- 更新“程序更新或模块加载异常”指南：常见原因增加程序代码兼容性问题；建议操作改为直接前往 GitLink/GitHub 资源库下载最新安装包或联系开发者修复；删除重复的“仍无法处理时”段落。
- 新增 GitLink 与 GitHub 下载链接，并补充定向内容测试；指南 JSON 校验、UI/平台测试和 `git diff --check` 均通过。

## 2026-08-28：加宽游戏选择弹窗

- 游戏选择弹窗宽度由 410 调整为 520，文本标签换行宽度同步增至 460；保留自动换行，尽量让长名称保持单行显示。
- 基线 `0.1.0` 与活动版本 `0.2.0` 已同步；定向编译、Ruff、UI/平台测试和 `git diff --check` 均通过。

## 2026-08-28：改用文本标签处理游戏选择长名称

- 游戏选择项改为外层可点击容器加内部 `CTkLabel`，由标签的 `wraplength`/左对齐负责换行，避免 `CTkButton` 不支持参数及文本跳动问题。
- 基线 `0.1.0` 与活动版本 `0.2.0` 已同步；编译、Ruff、UI/平台定向测试和 `git diff --check` 均通过。查看效果前需重启客户端。

## 2026-08-28：修复游戏选择弹窗参数兼容性

- 移除 CustomTkinter `CTkButton` 不支持的 `justify`/`wraplength` 参数，改用名称分行并保留左对齐，避免长名称触发控件异常。
- 基线 `0.1.0` 与活动版本 `0.2.0` 已同步；定向测试、编译、Ruff 和 `git diff --check` 均通过。查看效果前需重启客户端。

## 2026-08-28：修复游戏选择弹窗长名称溢出

- 游戏选择项改为左对齐并设置换行宽度，超长名称自动增高，仅从右侧换行显示，避免左右两端溢出。
- 基线 `0.1.0` 已同步到活动版本 `0.2.0`；验证：客户端编译、Ruff、UI/平台定向测试（全部通过）、`git diff --check`。未执行 GUI 人工验收；查看效果前需重启客户端。

## 2026-08-28：恢复模块回退设置开关

- 按用户要求恢复普通设置页中的“启动失败时保留当前模块”开关；开发排错信息清理的其他部分保持不变。
- 基线 `0.1.0` 与活动版本 `0.2.0` 已同步；验证：两个模块编译、基线 Ruff、`pytest -q tests/test_ui_theme.py tests/test_platform_content.py`（全部通过）、`git diff --check`。查看界面前需重启客户端。

## 2026-08-28：清理用户界面中的开发排错信息

- 客户端普通界面隐藏扫描诊断数量、Steam App 编号、模块回退调试开关、问题详情内部字段及启动器错误码/事件 ID；详细内容仍保留在日志、问题记录和用户主动复制/导出的诊断内容中。
- 操作失败提示改为面向用户的重试/排查建议；指南统一改为说明现象并附截图，内部 Release 术语改为云端资源。
- 基线 `0.1.0` 已同步相关改动到活动版本 `0.2.0`（未修改 `app/state.json`）；验证：两个模块与启动器 `py_compile`、Ruff、`pytest -q tests/test_ui_theme.py tests/test_platform_content.py`（全部通过）、`git diff --check`。未执行 GUI 人工验收、构建、上传或推送；查看新界面前需重启客户端。

## 2026-08-28：修复 hub 发布主表先于卡带上传的问题

- `hub_publish_assets()` 不再按文件名重排资源，保持 `cartridges_index.json` 为最后一个发布资源，避免客户端看到新主表但仍拿到旧卡带或未完成传播的卡带文件。
- 验证：`pytest -q tests/test_cartridge_catalog.py::test_publisher_snapshots_complete_hub_as_publish_assets tests/test_publisher_content_pipelines.py tests/test_publisher_ui_threading.py`（全部通过）、发布器 Ruff、`git diff --check`；未执行真实云端上传或 GUI。
- 实际活动客户端版本为 `0.2.0`；本次仅发布器代码，无需客户端同步或重启。

## 2026-08-28：启动时重试远端卡带以应对发布传播延迟

- 启动后的远端卡带刷新现在按 0、2、5、10 秒延迟最多尝试四次，每次重新读取主表和当前卡带；任一尝试成功即可在当前窗口更新游戏数量，不必依赖重启。
- 相同主表的重复重试结果不再重复刷新界面或写入“已同步”提示，避免稳定后看起来持续同步。
- 基线 `0.1.0` 已同步到活动版本 `0.2.0`；验证：两个模块编译、`pytest -q tests/test_ui_theme.py tests/test_platform_content.py`（全部通过）、基线 Ruff、`git diff --check`。未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-28：完善安全软件排查指南流程

- “杀毒软件隔离、拦截或删除文件问题”指南新增进入杀毒软件检测工具按钮，展示检测到的产品并可打开对应安全软件。
- 增加 Windows Defender 保护历史记录排查步骤、两张用户演示图、关闭 Defender 指南跳转，并提醒 360、火绒、艾可菲等其他安全软件也需逐一排查。
- 导航目标 `tool:security-products` 复用现有检测页面；基线与活动版本 `0.2.0` 已同步。验证：`pytest -q tests/test_platform_content.py tests/test_ui_theme.py`（93 项通过）、两个模块编译、Ruff、`git diff --check`；未执行 GUI、构建、上传或推送。

## 2026-08-28：补充开源项目与安全软件误判说明

- “杀毒软件隔离、拦截或删除文件问题”指南的“常见原因”改为说明自研开源程序可能被安全软件误判，并建议用户核对官方来源后手动加入白名单。
- 新增 GitHub 项目仓库链接，并提示访问可能需要代理或国际网络；建议操作原有安全边界保持不变。
- 验证：`pytest -q tests/test_platform_content.py tests/test_ui_theme.py`（93 项通过）、指南 JSON 检查、`git diff --check`；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-28：优化 GitLink 网络提示措辞

- 将网络指南中的“部分地区可能无法正常登录或连接 GitLink”改为“部分运营商提供的网络可能无法正常登录或连接 GitLink”，避免将问题归因于地理区域。
- 验证：`pytest -q tests/test_platform_content.py tests/test_ui_theme.py`（92 项通过）、指南 JSON 检查、`git diff --check`；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-28：补充 GitLink 地区网络提示

- 网络指南建议操作新增提示：部分地区可能无法正常登录或连接 GitLink；确认本地网络正常但仍无法下载时，建议切换手机流量或其他 Wi‑Fi 重试。
- 验证：指南 JSON 检查、`pytest -q tests/test_platform_content.py tests/test_ui_theme.py`（92 项通过）、`git diff --check`；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-28：移除常用工具中的占位样例

- `config/guides/tools_index.json` 已删除“样例跨平台工具”条目，工具索引现在为空；真实工具不受影响。
- 验证：工具索引 JSON 检查、`pytest -q tests/test_platform_content.py tests/test_ui_theme.py`（92 项通过）、`git diff --check`；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-28：替换 Defender 教程第三张演示图

- 已用用户最新提供的截图替换 `config/guides/assets/defender-control.png`；指南 JSON 引用保持不变，仍作为第三张图显示。
- 验证：指南图片顺序与文件存在性检查通过；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-28：移除无效的工具详情按钮

- 删除辅助工具详情页中“查看工具详情”按钮；该按钮会重复当前页面且没有实际操作价值。保留“下载/删除下载”和“启动工具”两个有效操作。
- 基线 `0.1.0` 与活动版本 `0.2.0` 已同步；未修改 `app/state.json`，需重启客户端查看。
- 验证：`pytest -q tests/test_ui_theme.py tests/test_platform_content.py`（92 项通过）、两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-28：为所有发布器游戏配置勾选 Windows 支持

- 已更新 `publisher-workspace/games/*/game.json` 中 10 个游戏配置，全部声明 `published_platform_resources.windows.patch: true`；可下载 DLC 的配置同时保留/设置 `dlc: true`，文明7按当前仅补丁交付保留 `dlc: false`。
- `publisher-workspace/` 为本地发布器工作区且被 Git 忽略，本次修改不会进入客户端模块或 Git 提交；已用 JSON 解析逐项核对 11 个游戏配置（含原已配置的奇迹时代4），均可识别 Windows 支持。
- 未修改 `app/state.json`；无需客户端重启。未执行发布器 GUI、构建、云端上传或推送。

## 2026-08-28：精简游戏同步提示

- DLC 首页同步成功提示改为“已同步 N 款游戏”，N 使用当前平台可用游戏数，不再向用户展示主表总数等内部信息。
- 游戏选择弹窗的辅助统计改为仅显示“当前平台可用 N 款游戏”；基线与活动版本 `0.2.0` 已同步，未修改 `app/state.json`。
- 验证：`pytest -q tests/test_ui_theme.py tests/test_platform_content.py`（92 项通过）、两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-28：补充 Defender 教程演示图与权限提示

- `guide_close_windows_defender.json` 的操作说明新增启动工具后的权限提示；教程现在包含下载按钮、启动按钮和停用按钮的三张演示图（新增 `defender-download.png`、`defender-launch.png`，保留 `defender-control.png`）。
- 实际活动版本为 `0.2.0`；指南配置与图片为共享运行时资源，无需模块同步或修改 `app/state.json`，重启客户端后查看。
- 验证：`pytest -q tests/test_platform_content.py tests/test_ui_theme.py`（92 项通过）、两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-28：修复 Defender 工具详情状态刷新

- 移除 dControl 工具详情中红圈所示的默认描述文字。
- 辅助工具详情页现在按 `HelperToolsService.is_installed()` 重设顶部状态；下载完成、返回页面或重启客户端后，已下载工具显示“已就绪”，未下载工具显示“未下载”。
- 基线 `0.1.0` 与活动版本 `0.2.0` 已同步；未修改 `app/state.json`，需重启客户端查看。
- 验证：`pytest -q tests/test_ui_theme.py tests/test_platform_content.py`（92 项通过）、两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-28：更新关闭 Windows Defender 指南操作步骤

- `config/guides/guide_close_windows_defender.json` 移除“常见原因”和“注意事项”，将“建议操作”改为跳转 dControl 工具、下载、启动并点击“停用 Windows Defender”的顺序，并加入 `config/guides/assets/defender-control.png`（用户提供的截图二）。
- `docs/error-guide-content-catalog.md` 明确“常见原因”可选；新增定向断言覆盖正文顺序、跳转按钮、配图及移除的标题。
- 实际活动版本为 `0.2.0`；本次仅修改共享指南配置与资源，无需模块同步或修改 `app/state.json`，重启客户端后查看。
- 验证（2026-08-28）：指南 JSON/图片引用检查、`pytest -q tests/test_platform_content.py tests/test_ui_theme.py`（92 项通过）、基线与活动模块 `py_compile`、基线 Ruff、`git diff --check` 均通过；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-28：移除发布器指南服务端链路

- 发布器 Hub 生成不再检查或导出指南；工具上传只扫描 `publisher-workspace/tools/assets/`，不读取发布器指南目录或 `tools_index.json`。
- 删除发布器 `client_guides.py`、指南发布测试及兼容入口；客户端 `config/guides/`、指南加载代码和客户端 `tools_index.json` 保留。
- 删除本地 `publisher-workspace/guides/` 与 `publisher-workspace/output/guides/` 样例/缓存目录。未执行云端删除或上传。
- 验证：发布器定向 pytest（工具资产、UI）通过，Ruff、compileall、git diff --check 通过；客户端指南索引 7 项正文均存在。

## 2026-08-28：工具发布改为构建快照驱动

- 工具发布器改为扫描 `publisher-workspace/tools/assets/`，新增“构建工具快照”按钮和本地隐藏 `.tools-build.json`（文件名、大小、SHA-256、构建时间）。上传前强制验证快照未过期。
- 云端上传不再依赖 `tools_index.json`、指南引用或平台字段；GitLink/GitHub 继续按成功状态增量上传，并对远端缺失文件强制补传。客户端工具定义和三端支持不变。
- 验证：发布器模块编译、Ruff、工具资产/UI 定向测试通过；未执行真实云端上传或发布器 GUI 人工验收。

## 2026-08-28：发布器收敛为工具文件上传

- 发布器“扩展指南与工具”页已改为“工具文件上传”，移除指南目录和“本地发布指南与工具项”界面入口，仅保留工具目录与双端工具文件上传。
- 工具上传预检改为只依赖工具快照与工具包，不再因指南目录或 `tools_index.json` 缺失阻塞云端工具载荷上传；指南和工具定义仍通过客户端版本随程序发布，云端不上传。
- 修改范围：`src/signriver_publisher/cartridge_management_ui.py`、`src/signriver_publisher/extension_assets.py`、`src/signriver_publisher/workspace.py`、相关发布器测试与工具模板文档。未修改客户端活动模块或 `app/state.json`。
- 验证（2026-08-28）：发布器相关模块 `py_compile`、Ruff、`pytest -q tests\\test_publisher_extension_assets.py tests\\test_publisher_ui_threading.py`（83 项通过）；未执行发布器 GUI 人工验收、真实云端上传或推送。

## 2026-08-28：优化发布资源统一管理首页布局

- 发布器“发布资源统一管理”首页将“刷新资源概览”从摘要卡第三列移至标题栏右侧，改为紧凑的 128×32 页面级按钮；两张“卡带与公告 / 扩展指南与工具”摘要卡平分内容区，消除右侧竖向大按钮造成的失衡布局。
- 修改范围：`src/signriver_publisher/cartridge_management_ui.py`。发布器无客户端活动模块同步要求；未修改 `app/state.json`。
- 验证（2026-08-28）：`.\\.venv\\Scripts\\python.exe -m py_compile src\\signriver_publisher\\cartridge_management_ui.py`、Ruff、`pytest -q tests\\test_publisher_ui_threading.py`（72 项通过）、`git diff --check`；未执行发布器 GUI 人工验收、构建、上传或推送。

> 本文件只保存“下一位 AI 继续工作所需的当前状态”。历史操作记录见 [`archive/HANDOFF-2026-08-26-history.md`](archive/HANDOFF-2026-08-26-history.md)，不要在新任务中默认全文读取。

## 当前状态（2026-08-26）

- 已修正工具详情页子日志的“清空”按钮：从共享按钮循环中拆出并显式采用浅红底、红字和红色边框，避免在浅色日志工具栏中呈现为普通蓝色按钮；“复制”和“锁定滚屏”保持不变。基线 0.1.0 已按该范围定向同步到活动模块 0.2.0，未修改 app/state.json，需完全退出并重启客户端加载。验证：tests/test_ui_theme.py 与 tests/test_tool_detail_logs.py 共 69 项通过、两个模块 py_compile、基线 Ruff、git diff --check 通过；未执行 GUI 人工验收、构建、上传或推送。

- 已将“杀毒软件检测”页中“可以关闭 Windows Defender”提示卡由浅蓝底改为白色卡面，右侧“查看教程”改为蓝色实心按钮；文案与原有教程跳转不变。基线 `0.1.0` 已按该范围定向同步到活动模块 `0.2.0`，未修改 `app/state.json`，需完全退出并重启客户端加载。验证：`python -m pytest -q tests/test_ui_theme.py tests/test_platform_content.py`（91 项通过）、两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

- 已将“日志资料收集”说明和操作按钮统一为“打开日志收集文件夹”；仍调用原有收集目录打开逻辑。基线 `0.1.0` 已定向同步到活动模块 `0.2.0`，未修改 `app/state.json`，需完全退出并重启客户端加载。验证：`python -m pytest -q tests/test_support_collection_ui.py tests/test_ui_theme.py`（69 项通过）、两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

- 已将侧栏“运行日志”页的“复制当前日志”和问题详情底部“复制详情”提升为蓝色实心主操作；其余复制按钮仍保持原有低强调样式，危险操作未改。基线 `0.1.0` 已定向同步到活动模块 `0.2.0`，未修改 `app/state.json`，需完全退出并重启客户端加载。验证：`python -m pytest -q tests/test_ui_theme.py tests/test_platform_content.py`（91 项通过）、两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

- 已补齐问题记录页动态按钮的危险样式：从详情返回列表时的“清空全部记录”、进入详情后的“删除当前问题记录”都会重新明确应用 `BUTTON_DANGER`，不会仅依赖页面初始化时的样式。基线 `0.1.0` 已定向同步到活动模块 `0.2.0`，未修改 `app/state.json`，需重启客户端加载。验证：`python -m pytest -q tests/test_ui_theme.py tests/test_platform_content.py`（91 项通过）、两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

- 已修正报错指南“杀毒软件检测”详情页的视觉层级：浅蓝提示卡中的“查看教程”现在使用白底描边普通按钮，避免与卡片背景融为一体；各工具详情内嵌运行日志的“清空”已改为红色危险操作，复制仍保持低强调样式。基线 `0.1.0` 已定向同步到活动模块 `0.2.0`，未修改 `app/state.json`，需重启客户端加载。验证：`python -m pytest -q tests/test_ui_theme.py tests/test_platform_content.py`（91 项通过）、两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

- 已统一“报错指南”链路的按钮层级：报错指南首页、解决方案、常用工具、一键排错和问题记录中的主任务使用蓝色实心，查看/返回/打开/刷新/复制/暂停等普通操作使用浅蓝描边，删除/卸载/清空/终止使用红色描边。下载工具和问题记录操作会随当前语义切换对应样式；侧栏“运行日志”和其他大类未改。
- 基线 `app/versions/0.1.0/app_entry.py` 的相关改动已定向同步到实际活动模块 `0.2.0`；未修改 `app/state.json`，需要重启客户端后加载。验证：`python -m pytest -q tests/test_ui_theme.py tests/test_platform_content.py`、两个模块 `py_compile`、基线 Ruff 和 `git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

- 已强化“一键解锁工具”的补丁健康快速路径：当补丁与所选 DLC 已满足原有判断时，仍会扫描当前平台每个补丁写入目录的 `interference_files`；存在时以独立事务备份、清理，失败则不弹“已安装”成功提示。成功提示会列出清理的旧版残留文件；不会重新下载或重写已健康的补丁。基线 `0.1.0` 已定向同步到活动模块 `0.2.0`，需重启客户端后加载。验证：`python -m pytest -q tests/test_patch_engine.py tests/test_ui_theme.py`（103 项通过）、定向 Ruff、两个模块 `py_compile`、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

- 本次移除了 `_show_page()` 在忘记旧页面后调用的 `page_host.update_idletasks()`：该调用会先把空白容器绘制到屏幕，再逐步显示目标内容，是页面切换碎片化的直接原因。现在隐藏旧页面、挂载目标页面、刷新目标内容会在同一 Tk 事件循环回调内完成，最终统一绘制，避免中间帧闪现。
- 基线 `app/versions/0.1.0/app_entry.py` 已按该范围定向同步到实际活动模块 `0.2.0`；未修改 `app/state.json`，需要重启客户端后加载。
- 验证（2026-08-26）：两个模块 `py_compile`、`python -m ruff check app/versions/0.1.0/app_entry.py tests/test_ui_theme.py`、`python -m pytest -q tests/test_ui_theme.py`（63 项通过）、`git diff --check` 均通过；未执行 GUI 人工切换验收、构建、上传或推送。

- 本次统一常用工具卡片简略描述的显示格式：移除末尾中英文句末标点，详情页原文不变；基线 `0.1.0` 已同步到活动模块 `0.2.0`，未修改 `app/state.json`，需重启客户端加载。
- 验证（2026-08-27）：`python -m py_compile app/versions/0.1.0/app_entry.py app/versions/0.2.0/app_entry.py`、`python -m pytest -q tests/test_ui_theme.py tests/test_helper_tools.py`（67 项通过）、基线 Ruff、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

- 本次根据反馈将运行日志“复制/清空”辅助按钮字号调整为 12px（运行日志标题为 13px），保持无边框灰蓝低强调风格和原有按钮尺寸。基线已同步到活动模块 `0.2.0`，未修改 `app/state.json`；其他未提交改动未触碰。
- 验证：`python -m pytest -q tests/test_ui_theme.py tests/test_support_collection_ui.py`（65 项通过）；两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 本次将 `security-interference` 指南标题统一改为“杀毒软件隔离、拦截或删除文件问题”，并同步修改补丁状态指南中的跳转按钮文案；稳定 `guide_id` 保持不变，代码映射和导航引用无需改 ID。活动版本为 `0.2.0`，共享 `config/guides/` 无需模块同步，重启客户端后查看。
- 验证：指南索引/正文 JSON、`tests/test_platform_content.py`、编译、Ruff、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

- 本次将“程序日志”说明进一步改为“唏嘘南溪一键解锁工具日志”，基线与活动模块 `0.2.0` 已同步；需重启客户端加载。提交：`edab2ce`。验证：`tests/test_support_collection_ui.py` 3 项通过，两个模块编译、Ruff、`git diff --check` 通过。

- 本次根据反馈保留运行日志按钮正常字号（11px）和点击尺寸，仅通过无边框、灰蓝文字与轻微悬停底色降低视觉强调；锁定滚屏继续使用中性灰蓝色。基线已同步到活动模块 `0.2.0`，未修改 `app/state.json`。其他未提交改动未触碰。
- 验证：`python -m pytest -q tests/test_ui_theme.py tests/test_support_collection_ui.py`（65 项通过）；两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 本次统一现有 7 篇指南索引摘要：全部改为问题细节/可观察现象，不再写处理步骤；新增 `summary_type: "problem_detail"` 内容契约。指南规范已明确该要求，发布器预检会拒绝缺失或错误类型，后续新增指南必须遵守。活动版本为 `0.2.0`，共享 `config/guides/` 无需模块同步，重启客户端后查看。
- 验证：7 篇摘要字段检查、`tests/test_platform_content.py tests/test_publisher_extension_assets.py`（35 项）、两个模块与发布器编译、Ruff、`git diff --check` 均通过；未执行 GUI 人工验收、构建、上传或推送。

- 本次按截图调整“日志资料收集”采集卡片文案：程序日志说明改为“解锁工具日志”，系统信息改为“Windows DxDiag.txt”，不再显示“仅 Windows”。基线 `0.1.0` 已定向同步到活动模块 `0.2.0`，未修改 `app/state.json`；需重启客户端加载。提交：`b2feb3c`。
- 验证：`python -m pytest -q tests/test_support_collection_ui.py`（3 项通过）、两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 本次修正上一轮文案定位：恢复 `guide_patch_state.json` 中“常见原因”的原文，并将 `guides_index.json` 的 `patch-state.summary` 改为问题细节描述：“补丁状态未通过、缺少 unlock.dll，或补丁文件下载后消失、无法读取。”实际活动版本为 `0.2.0`，配置由共享 `config/guides/` 读取，无需模块同步，重启客户端后即可查看。
- 验证：指南 JSON 解析、`tests/test_platform_content.py`、两个活动/基线模块编译、基线 Ruff、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

- 本次强化三平台补丁安装：卡带补丁配置新增按平台独立的 `interference_files` 显式相对路径列表；`PatchEngine.apply()` 在写入补丁前以事务备份并删除普通干扰文件，失败回滚，成功后不恢复。基线已同步到活动模块 `0.2.0`，未修改 `app/state.json`；活动客户端需重启加载。
- 发布器卡带模型与客户端卡带导出同步校验该字段，拒绝绝对/越界/通配符/重复路径；补丁结果和客户端摘要记录清理文件。
- 验证：补丁、三平台、卡带目录、平台内容测试全部通过；两个模块和发布器编译通过；定向 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、全量构建、上传或推送。
- 当前工作区另有用户改动 `app/state.json`（`prevent_module_fallback`）及 `app_entry.py` 的日志工具栏样式，提交时不得纳入本任务；具体干扰文件清单尚未配置，等待内容设计者提供。

- 已确认旧的在线/缓存卡带可能没有 `interference_files` 字段：这会让补丁健康快速路径得到空列表而跳过残留清理。本次仅在字段**缺失**时，从客户端内置 bootstrap 卡带补齐当前平台的清理名单；线上卡带若显式声明空列表仍保持为空。基线 `0.1.0` 已定向同步到活动模块 `0.2.0`（活动模块为本地忽略目录），需要完全退出并重启客户端；此前构建的 EXE/模块需要更新后才会包含此兼容逻辑。一键修复继续复用 `PatchEngine.apply()` 的同一清理事务，不会二次扫描或恢复已删除文件。
- 验证（2026-08-26）：`python -m pytest -q tests/test_cartridge_catalog.py tests/test_patch_engine.py tests/test_ui_theme.py`（119 项通过）、两版 `cartridge_catalog.py` 编译、定向 Ruff、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

- 本次降低“运行日志”辅助操作栏的视觉强调：复制/清空去除图标并缩小为灰蓝纯文字幽灵按钮，锁定滚屏改用中性灰蓝勾选色；功能和操作位置不变。基线已同步到活动模块 `0.2.0`，未修改 `app/state.json`。工作区其余补丁相关改动属于用户已有改动，未触碰。
- 验证：`python -m pytest -q tests/test_ui_theme.py tests/test_support_collection_ui.py`（65 项通过）；两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 本次将 `config/guides/guide_patch_state.json` 中“常见原因”的说明改为问题细节描述：“问题通常表现为补丁状态未通过、unlock.dll 缺失，或补丁文件下载后消失、无法读取。”未修改客户端代码；实际活动版本为 `0.2.0`，配置由共享 `config/guides/` 读取，无需模块同步，重启客户端后即可查看。
- 验证：指南 JSON 解析通过；`tests/test_platform_content.py tests/test_client_problem_center.py` 共 1 项失败，失败为工作区既有补丁代码与测试夹具字段不一致（`interference_files_deleted` 缺失），与本次文案无关；两个活动/基线模块编译、基线 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 本次按截图删除补丁详情页“从云端重新下载补丁”按钮下方的说明行；下载逻辑、按钮和运行日志保持不变。基线已同步到活动模块 `0.2.0`，未修改 `app/state.json`。工作区其余补丁领域改动属于用户已有改动，未触碰。
- 验证：`python -m pytest -q tests/test_ui_theme.py`（62 项通过）；两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 新增启动器开发保护设置：设置页可勾选“启动失败时保留当前模块”，值写入 `app/state.json`；开启后模块导入失败会停止并显示错误，不自动切换旧版本，便于发现当前开发模块问题。默认关闭以保持普通用户自动回退行为。基线与活动模块 `0.2.0` 已同步。
- 验证：`tests/test_state.py tests/test_api.py tests/test_loader.py tests/test_main.py tests/test_ui_theme.py tests/test_support_collection_ui.py`（80 项通过）；启动器与两个模块编译、Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 本次修复启动失败：`CONSOLE_GHOST_BUTTON` 不再在模块导入阶段创建 `ctk.CTkFont`，改用字体元组，解决“Too early to use font: no default root window”。已验证 0.2.0 模块可由 `ModuleLoader` 成功导入；当前 `app/state.json` 活动版本为 `0.2.0` 且 `bad_versions` 为空。
- 验证：`python -m pytest -q tests/test_loader.py tests/test_state.py tests/test_launcher_problem_reporting.py tests/test_ui_theme.py tests/test_support_collection_ui.py`（79 项通过）；模块编译、Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 本次按截图精简“日志资料收集”详情页：移除顶部“本地采集 · 安全可控”说明卡和“问题记录”采集卡；保留后台问题记录收集逻辑，系统信息卡前移填补网格空位，AI 说明区随之上移。基线与活动模块 `0.2.0` 已同步，未修改 `app/state.json`，需重启客户端加载。
- 验证：`python -m pytest -q tests/test_support_collection_ui.py`（3 项通过）；两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 本次轻量化“运行日志”右上角工具栏：复制/清空改为 24px 高幽灵按钮，默认透明、悬停浅灰；锁定滚屏复选框缩小并统一为紧凑行内布局。基线已同步到活动模块 `0.2.0`，未修改 `app/state.json`，需重启客户端加载。
- 验证：`python -m pytest -q tests/test_ui_theme.py tests/test_support_collection_ui.py`（66 项通过）；两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 本次重构“日志资料收集”界面：采集内容改为 2×2 卡片，新增“本地采集 · 安全可控”和“AI 辅助诊断”Callout，优化主次按钮与组件间距；保留原有后台收集、打开目录和运行日志逻辑。基线已同步到活动模块 `0.2.0`，未修改 `app/state.json`，需重启客户端加载。
- 验证：`python -m pytest -q tests/test_support_collection_ui.py tests/test_ui_theme.py`（66 项通过）；两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 本次继续压缩显卡详情卡片：厂商、驱动版本、驱动日期改为三列同排显示，减少每张卡片的垂直占用，使默认窗口可同时容纳两张显卡信息；基线已同步到活动模块 `0.2.0`，未修改 `app/state.json`，需重启客户端加载。
- 验证：`python -m pytest -q tests/test_ui_theme.py tests/test_support_collection_ui.py`（66 项通过）；两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 本次压缩显卡驱动详情卡片布局：减少卡片间距、标题区和信息网格的上下留白，缩小字段字号与官网按钮底部间距；基线已同步到活动模块 `0.2.0`，未修改 `app/state.json`，需重启客户端加载。
- 验证：`python -m pytest -q tests/test_ui_theme.py tests/test_support_collection_ui.py`（66 项通过）；两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 本次优化日志资料收集说明：明确提示用户点击“打开收集文件夹”按钮查看收集结果；基线已同步到活动模块 `0.2.0`，未修改 `app/state.json`，需重启客户端加载。
- 验证：`python -m pytest -q tests/test_support_collection_ui.py`（2 项通过）；两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 本次调整“日志资料收集”详情页布局：正文文本框设置 190px 最小高度，状态信息与操作按钮增加上下间距，避免正文与后续组件挤压；基线已同步到活动模块 `0.2.0`，未修改 `app/state.json`，需重启客户端加载。
- 验证：`python -m pytest -q tests/test_support_collection_ui.py tests/test_ui_theme.py`（66 项通过）；两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 本次优化“日志资料收集”详情正文：改为逐行列出收集内容，并补充可将日志资料发送给 AI、附带问题以获取参考解决方案的提示。基线 `0.1.0` 已修改，并已定向同步到活动模块 `0.2.0`；未修改 `app/state.json`，需重启客户端加载。
- 验证：`python -m pytest -q tests/test_support_collection_ui.py`（2 项通过）；两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

- 已加固 Windows 全量更新：`transaction.json` 原子替换对 WinError 5/32/33 做有限重试；新事务使用同卷短目录 `.su`/`.ub`；增加 240 字符路径预检和辅助进程启动错误诊断。活动版本仍为 `0.2.0`，未构建、上传或推送。
- 验证：定向更新测试 36 项通过，`ruff`、启动器编译通过；全量 pytest 有 3 个既有临时目录清理错误和 1 个既有文档编码断言失败，与本次改动无关。

- 本任务已将指南和常用工具项改为本地固定定义：客户端仅读取 `config/guides/`，工具下载文件仍使用双端 `tools` Release；发布器入口已拆分为本地同步与工具文件上传。活动版本为 `0.2.0`，需重启客户端加载，未构建、上传或推送。

- 当前分支：`main`；进入本次文档治理前工作区无未提交改动。
- 本次调整指南详情行为：移除顶部固定工具管理按钮，工具下载/启动/删除统一由工具详情页负责；正文按需使用 `tool:<tool_id>` 按钮跳转，基线与活动模块 `0.2.0` 已同步。
- 本次将常用工具中的“安全软件检测”及其一键排错结果、详情页和返回提示统一更名为“杀毒软件检测”；基线已同步到活动模块 `0.2.0`，需重启客户端加载。
- 本次优化一键排错页面提示：仅说明进行检测且不会修改游戏文件、设置或网络配置，并提示未发现异常不代表问题已全部排除；基线与活动模块 `0.2.0` 已同步，需重启客户端加载。
- 当前正式线上版本为 `0.1.7`，开发目标为 `0.2.0`；客户端运行模块以 `app/state.json` 的 `active_version` 为准。
- 本次新增显卡驱动只读检查：基线 `0.1.0` 已实现并定向同步到活动模块 `0.2.0`；未修改 `app/state.json`，未构建、上传或推送。
- 交接历史已归档；后续只将仍影响当前代码、测试、发布或用户操作的结论留在本文件。

## 2026-08-26：工具详情日志按工具隔离

- 工具详情运行日志改为按稳定工具键缓存，重新进入同一工具保留历史，切换工具不再串日志；`_notify()` 不再把顶部提示复制到工具日志。
- 下载、取消、完成、失败、删除、启动、打开链接/目录/文件、刷新、指南互跳和内置诊断动作均通过专属日志入口记录；异步结果绑定发起工具键。
- 基线 `0.1.0` 已定向同步到活动模块 `0.2.0`，未修改 `app/state.json`；需重启客户端加载。
- 验证：`tests/test_tool_detail_logs.py`、`tests/test_helper_tools.py`、`tests/test_client_problem_center.py` 共 29 项通过；两个模块编译、基线 Ruff、`git diff --check` 通过。`tests/test_ui_theme.py` 中一个既有工具项文档编码断言失败，与本次改动无关。

## 2026-08-26：日志资料收集输出后台阶段

- `SupportBundleCollector.collect()` 增加可选进度回调，客户端将创建目录、DxDiag、程序日志、游戏资料和结果汇总等阶段实时写入 `builtin:support-collection` 子日志。
- 基线与活动模块 `0.2.0` 已同步；定向支持资料测试、编译、Ruff 和 `git diff --check` 通过，未执行 GUI 人工验收。

## 当前风险与边界

- 一键排错仅在 Windows 追加显卡驱动检查；使用 PowerShell/CIM 读取名称、版本和日期，按当前年份前 3 年提示“建议更新”。详情页只提供设备管理器、Windows 更新和厂商官网入口，不自动安装驱动。
- 活动模块目录被 Git 忽略；需重启客户端后才能看到同步内容。GUI 人工验收、发布构建、上传和推送未执行。

## 2026-08-26：所有工具详情提示同步专属日志

- 工具详情页打开时，统一 `_notify()` 会把当前操作结果追加到该详情页的专属日志；相邻重复消息自动去重。
- 因此删除、取消、下载完成/失败等未显式调用 `_append_tool_log()` 的工具操作也会记录；补丁工具原有的文件明细记录继续保留。
- 基线与活动模块 `0.2.0` 已同步；验证：83 项定向测试、两个模块编译、Ruff、`git diff --check` 通过。未执行 GUI、构建、上传或推送。

- 活动模块目录可能被 Git 忽略；不能因为基线提交成功就声称活动客户端已发布。
- GUI 人工视觉验收、跨平台原生构建、上传和推送均未执行，除非后续任务明确要求。
- 不能用历史交接文字替代当前代码、Git 状态和可重复测试结果。

## 最近验证

- 本次定向验证：`pytest -q tests/test_client_problem_center.py tests/test_helper_tools.py tests/test_ui_theme.py tests/test_security_software.py`（85 项通过）；基线与活动模块 `py_compile`、Ruff、`git diff --check` 通过。
- 本次文档治理验证：待完成，至少检查 Markdown 链接、重复入口和 Git diff 空白错误。

## 下一步

1. 新任务先读取 `docs/agent/README.md` 与本文件，再按任务需要读取 `DECISIONS.md`、专题文档和归档。
2. 修改代码前核对 `active_version`、Git 状态和直接相关测试。
3. 任务结束时只更新本文件的当前摘要；长期方案写入 `DECISIONS.md`，一次性过程写入归档。

## 2026-08-26：工具云端下载需求标记

- `GuideTool` 新增 `requires_cloud_download` 字段，默认 `true`，用于声明工具是否需要云端下载；非布尔值拒绝解析。
- 工具详情页支持按声明显示状态；显卡驱动、杀毒软件检测、日志资料收集等内置工具标记为无需云端下载，打开即显示“已就绪”；补丁工具及旧云端工具继续按缓存/资源状态判断。
- 基线 `0.1.0` 已定向同步相关文件到活动模块 `0.2.0`，未修改 `app/state.json`；需重启客户端加载。未构建、上传或推送。
- 验证：`python -m pytest -q tests/test_helper_tools.py tests/test_platform_content.py tests/test_ui_theme.py`（全部通过）、基线与活动模块编译、定向 Ruff、`git diff --check` 通过；未执行 GUI 人工验收。

## 文档治理约定

- 不在本文件追加逐步操作流水、完整日志、重复测试输出或已经结束的 UI 微调。
- 若当前摘要超过约 300 行或 40 KB，应将已结束条目迁入 `docs/agent/archive/`，并在此保留一行索引。

## 2026-08-26：固定关联指南入口移至工具详情顶部

- 工具详情页新增顶部“查看关联指南”按钮；补丁工具与有固定指南关联的辅助工具使用该入口，正文不再重复显示。
- 从指南返回工具时隐藏关联按钮，避免回跳循环；基线 `0.1.0` 已定向同步到活动模块 `0.2.0`，未修改 `app/state.json`，需重启客户端加载。
- 验证：两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过；定向 pytest 70 项通过，`test_tool_item_ui_spec_documents_the_card_description_limit` 仍因既有文档编码/文案断言失败。
- 未执行 GUI 人工验收、构建、上传或推送。
## 2026-08-26：补丁工具专属日志补齐下载操作

- 根因：补丁工具详情页的“运行日志”使用 `_append_tool_log()` 内存控制台；重新下载流程完成/失败时只调用 `_notify()`，因此主日志有记录但专属日志没有。
- 基线与活动模块 `0.2.0` 已在重新下载开始、每个文件完成/失败、异常及打开缓存/安装目录时追加专属日志；主日志记录保持不变。
- 未修改 `app/state.json`；活动客户端需完全退出并重启后加载。工作区另有用户已有的文档管理改动，本次未触碰。
- 验证（2026-08-26）：`python -m pytest -q tests/test_helper_tools.py tests/test_client_problem_center.py tests/test_ui_theme.py`（83 项通过）、两个模块 `py_compile`、基线 Ruff、`git diff --check` 均通过；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-26：补丁状态指南与指南/工具互跳

- `guide_patch_state.json` 的常见原因改为补丁可能被杀毒软件拦截；建议操作先跳转补丁工具查看状态，再按补丁状态重新下载/刷新，并增加补丁工具截图和安全软件疑似干扰指南入口。
- 指南正文新增受控 `button` 块：`patch-tool` 打开补丁工具，`guide:<guide_id>` 打开另一篇指南；导航记录初始入口，互相返回不会形成循环。
- 从指南进入工具时，工具详情返回原指南，原指南返回按钮仍回到最初入口；从工具进入指南时遵循同一规则。格式约束已同步写入 `docs/error-guide-content-catalog.md`。
- 验证：JSON、基线/活动模块 `py_compile`、Ruff，以及 `pytest -q tests/test_platform_content.py tests/test_ui_theme.py tests/test_client_problem_center.py tests/test_helper_tools.py`（全部通过）；未执行 GUI、构建、上传或推送。

## 2026-08-26：合并补丁异常解决方案

- 已移除 `patch-assets-missing` 指南及索引项；`PATCH-ASSET*`、`PKG-ASSET*` 和补丁工具回调统一映射到 `patch-state`（补丁状态异常）。
- 已同步更新指南目录文档与定向测试；基线和活动模块均已对齐，活动版本为 `0.2.0`，重启客户端后生效。
- 验证：指南 JSON、两个模块 `py_compile`、Ruff、`pytest -q tests/test_platform_content.py tests/test_client_problem_center.py tests/test_ui_theme.py`（全部通过）；未执行 GUI、构建、上传或推送。

## 2026-08-26：精简指南规范文档

- `docs/error-guide-content-catalog.md` 已收敛为内置与云端指南共用的格式、内容边界、图片、链接、跳转、发布和验收规则；历史报错案例与来源盘点已移除。

## 2026-08-26：互跳工具返回按钮文案

- 从指南进入补丁工具或辅助工具后，返回按钮现在根据来源指南标题动态显示（例如“返回补丁状态异常”），标题不可用时回退为“返回解决方案”。
- 基线与活动模块 `0.2.0` 已同步；定向 UI、问题中心和工具详情测试通过，需重启客户端加载活动模块。

## 2026-08-26：修正指南正文换行

- 指南正文宽度计算改为先还原 Tk DPI 缩放，再按内容区域扣除边距；修复动态宽度过大导致长句不换行的问题。
- 基线与活动模块 `0.2.0` 已同步；编译、Ruff、指南相关 UI/问题中心测试和 `git diff --check` 通过。

## 2026-08-26：修复指南滚动条首次布局

- `_AutoHideScrollableFrame` 的滚动条可见状态改为首次布局时未知，确保内容溢出时即使控件初始已隐藏也会执行显示；基线与活动模块 `0.2.0` 已同步。
- 编译、Ruff、指南相关 UI/问题中心测试和 `git diff --check` 通过；需重启客户端查看。

## 2026-08-26：调整指南正文换行宽度

- `CTkLabel` 会自行处理 `wraplength` 的 DPI 缩放，正文宽度计算不再重复除以缩放比例，改为直接使用内容容器宽度扣除边距，让中文字符尽量排到容器边缘再换行。
- 基线与活动模块 `0.2.0` 已同步；编译、Ruff、指南相关 UI/问题中心测试通过。

## 2026-08-26：指南正文改为逐字符换行

- 放弃依赖 `CTkLabel` 自动 `wraplength` 的方案；正文文本现在按实际字体测量逐字符累积，超过标签可用宽度立即插入换行，并在容器尺寸变化后重新排版。
- 基线与活动模块 `0.2.0` 已同步；编译、Ruff、指南相关 UI/问题中心测试通过。

## 2026-08-26：回退指南正文换行实验方案

- 逐字符测量换行会导致正文重排和滚动卡顿，已移除该逻辑，恢复为原始 `wraplength=820` 的 Tk 自动换行方案；滚动时不再重写正文文本。
- 基线与活动模块 `0.2.0` 已同步；编译、Ruff、指南相关 UI/问题中心测试通过。

## 2026-08-26：指南正文改用只读文本框

- 正文段落改用 `CTkTextbox`，设置 `wrap="char"` 和只读状态；每个文本框关闭自身滚动条并按显示行数自动调整高度，继续由外层指南滚动容器统一滚动。
- 基线与活动模块 `0.2.0` 已同步；编译、Ruff、指南相关 UI/问题中心测试通过；未执行 GUI 人工验收。

## 2026-08-26：调整指南文本框组件间距

- 文本框初始高度提高并在空闲时、短延迟后各进行一次行数测量，避免后续标题、图片或按钮在文本框尚未完成布局时提前占位。
- 关闭文本框额外边距，保持正文与相邻组件的间距由统一 `pack` 间距控制；基线与活动模块 `0.2.0` 已同步。

## 2026-08-26：修复指南联系链接的滚动可达性

- 联系开发者链接仍由指南 JSON 和正文渲染分支提供；问题来自文本框高度异步调整后外层滚动区域未刷新，导致底部链接落在可滚动范围之外。
- 文本框尺寸变化及正文构建完成后都会刷新指南滚动区域；基线与活动模块 `0.2.0` 已同步，定向测试通过。

## 2026-08-26：优化常用工具卡片摘要布局

- 工具卡片摘要改为按卡片实际宽度和 DPI 缩放动态计算 `wraplength`，避免固定宽度在高 DPI 下从容器右侧溢出。
- 优化内置显卡检查、杀毒软件检测、补丁工具、日志资料收集及 Defender 工具描述；基线已同步到活动模块 `0.2.0`，未修改 `app/state.json`。
- 验证：`pytest -q tests/test_ui_theme.py tests/test_support_collection_ui.py tests/test_helper_tools.py`（全部通过）、两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-26：修复工具详情页返回按钮文案

- 根因：`_show_tool_center_detail()` 只更新工具列表页返回按钮，未更新详情页 `tool_center_detail_back_button` 的文字；返回回调本身正常。
- 基线 `0.1.0` 与活动模块 `0.2.0` 已同步；未修改 `app/state.json`。活动客户端需完全退出并重启后加载。
- 验证：相关 pytest 105 项通过，两个模块编译、基线 Ruff、`git diff --check` 通过；已创建本地提交 `a8f9ad2`，未推送。未执行 GUI 人工验收、构建或上传。

## 2026-08-26：完善指南与工具连续互跳

- 指南详情新增显式返回上下文：指南→指南保存来源指南及其上一级上下文，工具→指南保存辅助工具或内置补丁工具上下文。
- 返回指南时按来源上下文恢复原指南/工具详情；补丁工具返回会跳过工具列表刷新后直接重建补丁工具详情。基线已同步到活动模块 `0.2.0`，未修改 `app/state.json`。
- 验证：导航、UI、指南、工具定向测试通过；两个模块编译、基线 Ruff、`git diff --check` 通过。`test_tool_item_ui_spec_documents_the_card_description_limit` 仍因工作区既有文档内容不匹配而未通过；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-26：工具详情正文采用只读文本框

- 工具详情页的 `detail_intro` 与 `description` 改用与解决方案详情一致的只读 `CTkTextbox`，按字符换行并自动按显示行数调整高度；警告仍保留提示色卡片。
- 基线 `0.1.0` 已定向同步到活动模块 `0.2.0`，未修改 `app/state.json`；需重启客户端查看，未执行 GUI 人工验收、构建、上传或推送。
- 验证：两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过；相关 pytest 83 项通过，`test_tool_item_ui_spec_documents_the_card_description_limit` 因既有文档编码/文案断言不匹配失败，与本次改动无关。

## 2026-08-26：优化解决方案文章跳转按钮

- 指南正文中的页面跳转按钮改用统一的浅蓝次要按钮样式，降低与下载/启动主操作的视觉冲突；跳转目标和返回路径未变。
- 基线 `0.1.0` 已定向同步到活动模块 `0.2.0`，未修改 `app/state.json`；需完全重启客户端查看。
- 验证：基线与活动模块 `py_compile`、基线 Ruff、`git diff --check` 通过；`tests/test_ui_theme.py tests/test_platform_content.py` 共 1 项既有文档编码断言失败，其余通过；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-26：统一指南与工具详情正文自动换行

- 修正前次实现方向：不增加文章卡片边框；工具详情改为直接复用解决方案详情的只读 `CTkTextbox`、字符换行和按显示行数自动高度逻辑。
- 内置日志资料收集、杀毒软件、补丁、显卡详情中的说明文字也统一走该文本框入口；基线 `0.1.0` 已同步到活动模块 `0.2.0`，需重启客户端查看。
- `docs/tool-item-ui-spec.md` 与 `docs/error-guide-content-catalog.md` 已补充正文文本框及自动换行约定。验证：两个模块编译、Ruff、空白检查通过；相关测试除既有文档编码断言外均通过；未执行 GUI 人工验收。

## 2026-08-26：显卡详情采用卡片、徽标与全局操作栏

- 显卡详情已重构为浅色卡片、品牌色标识、当前输出/状态胶囊徽标、2×2 参数网格和页面级系统工具栏；卡片仅保留厂商官网入口，底部提示改为信息 Alert。基线与活动模块 `0.2.0` 已同步，需重启客户端查看。
- 当前 `app/state.json` 实际活动版本为 `0.1.7`，`0.2.0` 标记为 bad；本次已将基线 `app_entry.py` 定向同步到活动模块 `0.1.7`，未修改状态文件。
- 工具详情规范已补充强调信息块约定。验证：基线/活动模块编译、Ruff、`git diff --check` 通过；相关测试除既有文档编码断言外均通过；未执行 GUI 人工验收。

## 2026-08-26：明确日志可交由 AI 辅助诊断

- “日志资料收集”详情页的 AI 提示改为明确说明：收集完成后可将日志文件与问题一起交由 AI 辅助诊断，以获取参考方案。
- 基线 `app/versions/0.1.0/app_entry.py` 已修改，并定向同步到当前活动版本 `0.2.0`；未修改 `app/state.json`，活动客户端需重启后加载。
- 验证：`python -m pytest -q tests/test_support_collection_ui.py`（3 项通过）；基线与活动模块 `py_compile`、基线 Ruff、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-26：微调一键排错按钮尺寸

- 根据反馈将报错指南“开始一键排错”按钮调整为 `170×50`，保持右侧操作列内垂直居中；基线已同步到活动模块 `0.2.0`，未修改 `app/state.json`。

## 2026-08-26：调整 AI 辅助诊断标题

- “日志资料收集”详情页红框标题改为“可将日志交由 AI 辅助诊断”，与用户期望的直接表达一致；说明正文保留操作指引。
- 基线已同步到当前活动版本 `0.2.0`，未修改 `app/state.json`，需重启客户端加载。
- 验证：两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过；相关定向测试待执行。未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-26：一键排错入口按钮布局

- 报错指南页的“开始一键排错”按钮改为 `190×42`，置于说明文字下方并在卡片中水平居中；标题和说明仍保持左对齐。
- 已修改 Git 跟踪基线 `0.1.0`，并定向同步到活动模块 `0.2.0`；未修改 `app/state.json`，需重启客户端加载。
- 验证：`python -m py_compile app/versions/0.1.0/app_entry.py app/versions/0.2.0/app_entry.py`、`python -m pytest -q tests/test_ui_theme.py`（62 项通过）、`python -m ruff check app/versions/0.1.0/app_entry.py`、`git diff --check` 均通过。未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-26：修正一键排错按钮为右侧列垂直居中

- 报错指南的一键排错卡片改为左右两列：左侧标题与说明，右侧保留 `190×42` 主按钮并在该列垂直居中，符合截图标注布局。
- 基线与活动模块 `0.2.0` 已同步；未修改 `app/state.json`，需重启客户端加载。
- 验证：两个模块 `py_compile`、`tests/test_ui_theme.py`（62 项通过）、基线 Ruff、`git diff --check` 均通过。未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-26：调整工具详情教程入口文案

- 工具详情顶部关联指南入口统一改为“查看使用教程 →”；基线 `0.1.0` 与活动模块 `0.2.0` 已同步，需重启客户端加载。
- 验证：两个模块 `py_compile`，`tests/test_ui_theme.py tests/test_platform_content.py`（87 项通过）；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-26：补丁工具始终显示文件状态

- 补丁工具现在始终按当前发布包列出三项补丁文件；仅当相应缓存文件已下载且可访问时显示“打开位置”（JSON 同时显示“打开文件”）。未下载、缓存丢失、校验失败、下载失败、取消或下载中均在对应行显示提示，并隐藏打开操作。
- 基线 `0.1.0` 已定向同步到活动模块 `0.2.0`，未修改 `app/state.json`；需重启客户端加载。验证：`python -m pytest -q tests/test_ui_theme.py tests/test_platform_content.py`（87 项通过）、两个模块 `py_compile`、基线 Ruff、`git diff --check` 均通过；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-26：发布器人工验收添加干扰文件样例

- 发布器“人工验收”页新增“补丁测试 / 添加干扰文件”。它只会在当前卡带解析出的实际补丁目录创建 10 个零字节干扰文件样例，便于用客户端“一键解锁”或“一键修复”验收清理流程；任何同名文件（包括符号链接）存在时拒绝覆盖，创建中失败会清理本次已创建的样例。
- 样例名单是发布器验收夹具的固定 Windows 清理样例，不依赖本地旧工作区卡带是否已刷新 `interference_files` 字段，也不改变客户端实际卡带清理配置。
- 验证：`python -m pytest -q tests/test_publisher_acceptance.py tests/test_publisher_ui_threading.py`（全部通过）、发布器验收相关 Ruff、`py_compile` 与 `git diff --check` 通过；未执行发布器 GUI 人工验收、构建、上传或推送。

## 2026-08-26：补丁文件正常状态标记

- 当单项补丁缓存已下载、校验通过且文件可访问时，在右侧操作按钮之前显示绿色“补丁正常”标记；其余缺失、校验失败或下载状态的提示不变。
- 基线 `0.1.0` 已定向同步到活动模块 `0.2.0`，未修改 `app/state.json`；需重启客户端加载。验证：`python -m pytest -q tests/test_ui_theme.py tests/test_platform_content.py`（87 项通过）、两个模块 `py_compile`、基线 Ruff、`git diff --check` 均通过；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-27：严格远端卡带同步，禁止旧缓存执行 DLC 操作

- 客户端增加严格远端卡带加载路径；远端卡带刷新失败时保留当前页面但标记未同步，并禁用 DLC 下载、一键解锁、批量选择和一键修复。
- “刷新目录”先刷新 hub 卡带索引与当前卡带，再读取 DLC catalog；远端成功后替换内存中的卡带服务，避免继续使用旧配置。
- 基线 `0.1.0` 已定向同步到活动模块 `0.2.0`，未修改 `app/state.json`；需重启客户端加载。验证：两个模块 `py_compile`、定向 Ruff、相关 pytest 全部通过。未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-27：修复游戏选择器滚动条刷新

- 游戏选择弹窗在映射完成后及搜索结果重建后重新测量滚动容器，超长游戏列表会显示可拖动滚动条，空结果也会正确更新状态。
- 基线 `0.1.0` 已同步到活动模块 `0.2.0`，未修改 `app/state.json`；需重启客户端加载。验证：两个模块 `py_compile`、基线 Ruff、`tests/test_ui_theme.py`（67 项通过）、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-27：游戏选择器改为始终显示滚动条

- 上述延迟重测不足以覆盖自动隐藏状态误判；为 `_AutoHideScrollableFrame` 增加 `always_show_scrollbar` 参数，仅游戏选择器启用，避免列表内容被截断且滚动条不可见。
- 基线与活动版本 `0.2.0` 均已同步，未修改 `app/state.json`；需重启客户端加载。验证：两个模块 `py_compile`、基线 Ruff、`tests/test_ui_theme.py`（67 项通过）、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-27：明确主表总数与当前平台可用数

- 远端主表可包含暂未发布当前平台资源的条目；选择器按 `platform_resources` 过滤是预期安全行为。此前仅提示主表总数，造成“读取 11 款却只显示 6 款”的误解。
- 游戏选择弹窗和同步通知现在分别显示“已读取 N 款 / 当前平台可用 M 款”，未绕过不可用资源过滤。基线与活动版本 `0.2.0` 已同步，需重启客户端加载。
- 验证：两个模块 `py_compile`、基线 Ruff、`tests/test_ui_theme.py`（67 项通过）、`git diff --check` 通过。未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-28：DLC 编号稳定化与远端旧附件清理

- 自动导入编号改为持久化高水位，删除中间 DLC 不会让后续资源重新编号或复用旧编号；构建阶段拒绝重复 DLC 编号和安装目录名。
- GitHub 卡带中心、兼容入口和单端上传在发布前清理不在当前快照中的旧附件，随后按 SHA-256 状态决定同名附件是否覆盖，避免新旧编号并存。
- 实际活动版本仍为 `0.2.0`；本次仅发布器源码，无需客户端同步。定向编号/GitHub 测试、Ruff、`compileall`、`git diff --check` 通过；发布器工作区全量测试仅有既有的 `.build-complete.json` 元组/列表断言失败，未执行真实云端上传或推送。

## 2026-08-28：已发布平台资源改为勾选配置

- 发布器游戏卡带配置页将 `published_platform_resources` JSON 文本框改为 Windows、SteamOS、macOS 三个勾选框；勾选后保存为对应平台资源声明，旧 JSON 会按任一资源标记回显。
- 勾选的平台按当前 DLC 交付方式写入 `patch: true`；下载式 DLC 同时写入 `dlc: true`，内置 DLC 保持 `dlc: false`。实际活动版本仍为 `0.2.0`，本次仅发布器源码，无需客户端同步。
- 验证：发布器相关 Ruff、`py_compile`、`tests/test_platform_content.py tests/test_publisher_ui_threading.py`（96 项通过）、`git diff --check` 通过；未执行发布器 GUI 人工验收、真实云端上传或推送。

## 2026-08-27：修复发布器 GitHub 同名附件误复用

- 卡带中心双端发布及兼容发布入口不再依据“文件名 + 文件大小”判断 GitHub 附件是否可复用；改用按仓库/通道保存的本地 SHA-256 发布状态，内容变化（即使大小不变）会执行同名覆盖。
- GitHub 发布成功后写入独立 `state_channel="github"` 状态；附件替换同时按大小写不敏感名称删除旧附件，避免云端残留同名变体。
- 实际活动版本仍为 `0.2.0`；本次仅发布器源码，无需客户端同步或重启。验证：发布器定向 pytest、Ruff、`git diff --check` 均通过；未执行发布器 GUI、真实云端上传、构建或推送。

## 2026-08-28：新增退出代码 null 启动错误指南

- 新增内置指南 `paradox-launcher-crash-null`，标题与摘要均完整采用截图报错原文“游戏似乎出现崩溃或意外终止（退出代码 null）。此问题可以通过验证游戏文件完整性和停用任何 Mod 来解决。使用 Windows 系统的用户可能还需要安装 Visual C++ Redistributable 和 .NET Framework。”，展示用户提供的错误截图；建议先返回主页执行“一键修复”，仍失败时跳转“补丁状态异常”指南。
- 更新 `config/guides/guides_index.json`，新增截图资源 `config/guides/assets/paradox-launcher-crash-null.png`；活动版本为 `0.2.0`，配置目录会直接生效，无需修改版本模块或 `app/state.json`。
- 验证：`tests/test_platform_content.py` 通过；指南 JSON/图片引用校验通过；基线与活动模块 `py_compile`、基线 Ruff、`git diff --check` 通过。组合测试中 `tests/test_client_problem_center.py` 有 2 项由工作区既有客户端改动引起的失败，未修改相关逻辑；未执行 GUI、构建、上传或推送。
- 当前工作区同时包含此前未提交的客户端、索引及其他指南改动，无法安全拆分本次提交；本次新增内容暂不单独 commit，待相关指南改动一起核对后再提交。

## 2026-08-28：修复长标题导致指南详情溢出

- 解决方案列表中的长标题和摘要现在自动截断并追加 `...`；详情页标题改为占用返回按钮左侧的可用区域并自动换行，避免横向溢出和返回按钮被顶出。
- 基线 `app/versions/0.1.0/app_entry.py` 已同步到活动版本 `0.2.0`，未修改 `app/state.json`；需重启客户端查看。
- 验证：`tests/test_ui_theme.py tests/test_platform_content.py`、两个模块 `py_compile`、基线 Ruff、`git diff --check` 通过；未执行 GUI 人工验收、构建、上传或推送。

## 2026-08-28：修正退出代码 null 指南原因表述

- 将常见原因中的“结构有问题的文件”改为“结构有问题的 dlc 文件”，将“不完整的文件结构安装内容”改为“安装过不完整的 dlc 文件”。
- 验证：`tests/test_platform_content.py` 与 `git diff --check` 通过；未执行 GUI、构建、上传或推送。

## 2026-08-28：调整退出代码 null 指南提示文案

- 将截图下方提示改为“此问题往往不是因为Mod，缺失Visual C++ Redistributable 和 .NET Framework导致的”。
- 验证：`tests/test_platform_content.py` 与 `git diff --check` 通过；未执行 GUI、构建、上传或推送。

## 2026-08-28：首图移动到指南标题下方

- 解决方案详情渲染器现在会将正文首个图片块放在标题下、摘要前；其他指南的图片顺序保持不变。
- 基线已同步到活动版本 `0.2.0`，需重启客户端查看；`tests/test_ui_theme.py tests/test_platform_content.py`、两个模块编译、Ruff 和 `git diff --check` 均通过。

## 2026-08-28：修复指南返回按钮布局管理器冲突

- 详情标题栏改用 `grid` 后，移除返回指南列表时残留的 `pack()` 调用，避免 Tkinter 抛出“cannot use geometry manager pack ... already has slaves managed by grid”。
- 基线已同步到活动版本 `0.2.0`；相关 UI/指南测试、编译、Ruff 和 `git diff --check` 通过。

## 2026-08-28：SteamOS 阻塞后完成 macOS 原生重建

- SteamOS 原始 VM 与 `SteamOS-Password-Fixed` 克隆机均可进入桌面，但来宾 `sshd` 握手被重置，Guest Additions 也未就绪；已清理原始 VM 的重复 NAT 规则并保留两台旧 VM，未删除快照或磁盘。SteamOS 原生构建未执行，暂记为环境阻塞。
- macOS Sequoia VM（Darwin 24、x86_64）通过本机 VNC 接管；当前源码同步到 `~/signriver-build`，使用已有用户目录 Miniforge Python 3.13，安装项目 dev 依赖后完成 `tests/test_build_native_release.py` 定向测试与 `tools/build_native_release.py --platform macos`。
- macOS 构建产物位于来宾 `~/signriver-build/dist/`：首装 `SignRiver-DLC-Hub-v0.2.0-macos-x64.app.zip`（25,145,191 bytes，SHA-256 `d7f540554b06b02af9cd059fb1fe9ace8bb6719ad31a9d2e0c05b03ef46481b9`）；更新包 `updates/SignRiver-DLC-Hub-full-v0.2.0-macos-x64.zip`（25,159,088 bytes，SHA-256 `2f45b3a271ae2f85492f83dc4bbb5c6c60a2a35fa7c4cdf9f64af73f776784c6`）。`unzip -t`、Mach-O x86_64、ad-hoc `codesign --verify --deep --strict` 均通过，冻结客户端已启动并观察超过 8 秒。
- 当前活动版本为 `0.2.0`；本次未修改客户端源码，仅在被 Git 忽略的 `publisher-workspace/vm-share/` 创建临时同步目录和归档，未上传、发布或推送；两台 SteamOS 与 macOS VM 最终均已关闭。

## 2026-08-29：新增文章与指南组件库

- 在 `app/versions/0.1.0/article_components.py` 新增可复用 CustomTkinter 组件：`AlertBanner`、`StepWorkflowCard`、`PillBadge`、`FramedImageContainer` 及 `demo_patch_troubleshooting()`；调色板统一定义 `Bg/Border/Text/Accent`，文本支持窄窗口自适应换行，图片支持等比缩放与图注。
- 已将同一文件定向同步到活动版本 `0.2.0`（未修改 `app/state.json`）；当前客户端现有页面尚未接入该组件库，不能声称 GUI 已切换，需后续页面改造并重启验证。
- 验证：两个版本 `py_compile`、组件导入、Ruff、`git diff --check` 均通过；未执行 GUI 人工验收、全量测试、构建、上传或推送。

## 2026-08-29：指南详情页接入文章组件视觉

- 指南详情渲染器已实际接入 `FramedImageContainer`：正文截图增加浅灰边框、背景填充、居中等比缩放和文件名图注；章节标题改为浅蓝卡片与蓝色强调条，长标题配置 `wraplength`。
- 基线 `0.1.0` 已修改并将相关代码块定向同步到活动版本 `0.2.0`；未修改 `app/state.json`。已按源码入口启动当前客户端，PID 72836，需在已打开窗口中重新进入指南详情查看；不声称已发布。
- 验证：两个版本客户端与组件 `py_compile`、基线 Ruff、`tests/test_ui_theme.py tests/test_platform_content.py`（全部通过）、`git diff --check`；未执行构建、上传或推送。

## 2026-08-29：指南操作改为横幅与步骤卡片

- 指南详情页进一步接入 `AlertBanner` 和 `StepWorkflowCard`：包含“注意/警告/风险”的章节显示警示横幅，`button/action` 块显示圆形序号、说明与右侧执行按钮；保留原有回调和返回路径。
- 基线 `0.1.0` 已修改，相关代码块同步到活动版本 `0.2.0`；已停止旧源码进程并重启当前客户端 PID 58692，需重新打开指南详情查看。
- 验证：两个版本 `py_compile`、基线 Ruff、`tests/test_ui_theme.py tests/test_platform_content.py`（全部通过）；未执行构建、上传或推送。

## 2026-08-29：指南正文自动标记 DLL

- 指南 `text` 块现在自动识别 `.dll` 文件名并显示为蓝色 `PillBadge`，不改变原文和业务回调；基线与活动版本均已同步。
- 客户端已重启，当前源码进程 PID 46948。验证：两个版本 `py_compile`、基线 Ruff、`tests/test_ui_theme.py tests/test_platform_content.py`（全部通过）；未执行构建、上传或推送。

## 2026-08-29：修复文章卡片默认高度撑开

- 修复指南标题卡片大片空白：内部装饰 `CTkFrame` 的 CustomTkinter 默认高度会把父卡片撑到约 200px，现已显式限制装饰框高度，组件正文框也按内容收缩。
- 基线与活动版本 `0.2.0` 已同步；客户端已重启，当前源码进程 PID 55040。验证：两个版本 `py_compile`、基线 Ruff、`tests/test_ui_theme.py tests/test_platform_content.py`（全部通过）；未执行构建、上传或推送。

## 2026-08-29：移除截图文件名并恢复图片点击

- 截图容器不再显示内部文件名图注，预览最大高度调整为 420px，避免图片占满页面导致操作入口难以发现。
- `FramedImageContainer` 新增 `bind_click()`，同时绑定容器和实际图片控件，恢复点击图片打开大图预览；原指南按钮仍保留原有目标与回调，仅更换视觉为步骤卡片。
- 基线与活动版本已同步，客户端已重启，当前源码进程 PID 68656。验证：两个版本 `py_compile`、基线 Ruff、`tests/test_ui_theme.py tests/test_platform_content.py`（全部通过）；未执行构建、上传或推送。

## 2026-08-29：优化步骤卡片操作文案

- 移除卡片中的占位标题“执行指南操作”，卡片标题直接使用指南原按钮文案；正文改为简短引导，避免重复和无意义层级。
- 右侧按钮按目标显示“进入工具界面”“查看相关指南”“进入补丁工具”等明确动作，仍调用原有 `_activate_solution_button` 或 action 回调。
- 基线与活动版本已同步，客户端已重启，当前源码进程 PID 62688。验证：两个版本 `py_compile`、基线 Ruff、`tests/test_ui_theme.py tests/test_platform_content.py`（全部通过）；未执行构建、上传或推送。

## 2026-08-29：移除步骤卡片次要占位说明

- `StepWorkflowCard` 支持空正文；指南操作卡片不再显示“点击右侧按钮继续。”，单行标题在卡片内垂直居中，右侧动作按钮和原回调保持不变。
- 基线与活动版本已同步，客户端已重启，当前源码进程 PID 68656。验证：两个版本 `py_compile`、基线 Ruff、`tests/test_ui_theme.py tests/test_platform_content.py`（全部通过）；未执行构建、上传或推送。
