# 当前任务交接

> 本文件只保存“下一位 AI 继续工作所需的当前状态”。历史操作记录见 [`archive/HANDOFF-2026-08-26-history.md`](archive/HANDOFF-2026-08-26-history.md)，不要在新任务中默认全文读取。

## 当前状态（2026-08-26）

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
