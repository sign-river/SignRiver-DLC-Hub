# 解决方案辅助工具流程模板

后续 AI 若要在解决方案详情页引用可下载工具，必须复用本模板，不要再平行造一套下载/解压/启动页面。

## 适用场景

- 教程需要一个官方 Release 中的辅助工具；
- 工具按当前设置中的下载源选择 GitLink 或 GitHub；
- 用户在解决方案详情标题下操作：下载、取消、删除、启动或打开文件夹；
- 程序本身不自动修改系统防护，只提供教程和用户确认后的工具操作。

## 不要做的事

- 不要占用已有 `guide_id`（例如 `security-interference`）；
- 不要把 `tools` Release 附件塞进 `publisher-workspace/guides/assets/` 或 `hub` 打包；
- 不要用指南旧附件流程（`guides/cache/tools/...` + “下载附件”）替代 helper 流程；
- 不要整目录覆盖活动模块，也不要改 `app/state.json`；
- 不要让程序自动关闭 Windows Defender 或改安全设置。

## 资源位置

| 用途 | 位置 |
| --- | --- |
| 出厂指南索引 | `config/guides/guides_index.json` |
| 出厂指南正文 | `config/guides/guide_<name>.json` |
| 工具 zip | 双源 `signriver-dlc-assets` 的 `tools` Release |
| 本机解压目录 | `data/helper-tools/{tool_id}/` |
| 服务实现 | `app/versions/0.1.0/signriver_app/application/helper_tools.py` |
| 字段定义 | `GuideTool`（`guides.py`） |
| 界面 | `app_entry.py` 解决方案详情标题下按钮 |

GitLink 示例：

`https://gitlink.org.cn/signriver/signriver-dlc-assets/releases/download/tools/<AssetName>.zip`

GitHub 示例：

`https://github.com/sign-river/signriver-dlc-assets/releases/download/tools/<AssetName>.zip`

当前已存在并持续复用的双源 `tools` Release：

- GitLink：`https://gitlink.org.cn/signriver/signriver-dlc-assets/tree/tools`
- GitHub：`https://github.com/sign-river/signriver-dlc-assets/releases/download/tools`

发布新工具时，将工具文件放入 `publisher-workspace/tools/assets/`，由客户端内置定义负责名称、说明、平台和启动方式；发布器只把载荷上传到两个源的 `tools` Release。不要为单个工具另建 Release，也不要把工具附件复制到 `publisher-workspace/guides/assets/`。

由 `fixed_release_asset_url(download_source, "tools", asset_name)` 生成，禁止把源写死在按钮回调里。

工具目录约定：`publisher-workspace/tools/assets/` 只接受平铺普通文件；客户端 `config/guides/` 内的固定工具定义必须自行保证 `asset_name` 与载荷文件名一致。

## 发布拓展指南和工具

发布源严格分开：

| 资源 | 发布器工作区 | Release | 索引 |
| --- | --- | --- | --- |
| 指南与工具项定义 | `publisher-workspace/guides/`、`publisher-workspace/tools/tools_index.json` | 客户端 `config/guides/` | 本地版本发布 |
| 工具包 | `publisher-workspace/tools/assets/` | `tools` | 客户端内置定义中的 `asset_name` |

使用发布器“发布资源统一管理”页的“工具文件上传”。客户端指南与工具项定义在客户端版本准备阶段同步，不属于云端上传流程。工具文件上传流程会先检查：

- `assets/` 中是否只有平铺普通文件；
- 工具快照中的文件名、大小和 SHA-256 是否与当前文件一致。

预检失败时不会开始上传。先点击“构建工具快照”，再点击“上传工具文件”；发布器只将载荷同步到 GitLink、GitHub 的 `tools` Release，不上传指南或工具定义。需要更新客户端定义时，直接修改客户端配置并随客户端版本构建。

发布器为 GitLink 与 GitHub 分别保存本地成功发布的 SHA-256 状态。下次发布时只上传本地内容发生变化的附件，未变化的附件跳过；此判断不下载云端文件作内容比较。若有人手动删除云端附件而本地文件和本地状态均未变化，发布器不会自动补回，需修改文件或清除对应本地发布状态后重新发布。

指南正文里的 `tools` 条目推荐只保留：

```json
{
  "tool_id": "example-tool",
  "release_tag": "tools"
}
```

工具的完整标题、说明、文件名、版本、平台与启动方式只在 `tools_index.json` 维护，避免两处元数据漂移。

工具也可以在同一条 `tools_index.json` 记录中声明详情页内容和按钮：

```json
"detail": {
  "intro": "仅处理用户主动选择的文件，不会修改游戏安装目录。",
  "warnings": ["使用前请先备份文件。"],
  "buttons": [
    {"action": "open_guide", "label": "查看使用指南", "guide_id": "example-tool-guide"},
    {"action": "open_url", "label": "项目主页", "url": "https://example.com/tool"},
    {"action": "open_folder", "label": "打开工具目录"}
  ]
}
```

客户端只接受 `open_guide`、`open_url`、`open_folder` 三种白名单动作；不接受命令、脚本或任意回调。没有 `detail` 的旧工具继续使用默认详情页。`open_url` 必须使用 HTTPS，`open_guide` 的 `guide_id` 必须是稳定的小写 ID。

## 出厂指南 JSON

1. 在 `guides_index.json` 增加稳定 `guide_id`、标题、摘要、`asset_name`、`platforms`。
2. 新建详情 JSON，`blocks` 给后续正文留 heading/text 占位。
3. `tools` 中声明 helper 工具，参考 `close-windows-defender` / `dcontrol`：

```json
{
  "tool_id": "example-tool",
  "title": "工具显示名",
  "description": "用途说明",
  "asset_name": "ExampleTool.zip",
  "release_tag": "tools",
  "package_kind": "zip",
  "launch_action": "exe",
  "executable_name": "ExampleTool.exe",
  "run_as_admin": false,
  "platforms": ["windows"]
}
```

字段约定：

- `release_tag`：`hub` 表示指南附件，随 hub 打包；`tools` 表示独立工具 Release，发布器必须跳过。
- `package_kind`：`zip` 下载后解压到 `helper-tools/{tool_id}/`；`file` 保留原文件。
- `launch_action`：
  - `exe`：启动 `executable_name`，找不到则打开工具文件夹；
  - `open_folder`：只打开工具文件夹，让用户自己执行；
  - `legacy`：旧指南附件，不走 helper 双按钮。
- `run_as_admin`：仅 Windows 下用 `runas` 启动，由系统 UAC 确认。

## 界面约定

- 入口若在常用工具/安全检测等子页，用横条 +「查看教程」，调用 `_open_solution_article(guide_id, origin=...)`。
- 指南正文不再自动显示工具下载/启动/查看详情按钮；需要进入工具管理时，在正文增加 `button` 块并将 `target` 设为 `tool:<tool_id>`。
- 从杀毒软件检测进入时 `origin="security_products"`，返回必须回到「常用工具 → 杀毒软件检测」，不得跨层回到报错指南。
- 解决方案详情：标题下先放 helper 按钮，再放摘要和正文。
- 下载按钮三态：
  - 未下载：`下载工具`
  - 下载中：`暂停下载`（立即取消，删除本次临时文件，不做断点续传）
  - 已下载：`删除下载`（弹窗确认后删除整个工具目录，按钮回到「下载工具」）
- 启动按钮：已下载且未在下载中才可点。`exe` 显示「启动工具」，不能直接执行的显示「打开工具文件夹」。
- 下载、解压、启动都不得阻塞 UI 线程；完成后刷新当前详情页按钮。

## 代码落点

1. 改 Git 跟踪基线 `app/versions/0.1.0/`。
2. 若用户要立刻在当前客户端看到，按 `app/state.json` 的 `active_version` 定向同步：
   - `app_entry.py`
   - `signriver_app/application/helper_tools.py`
   - `signriver_app/application/guides.py`
   - `signriver_app/application/__init__.py`
3. `config/guides/` 在仓库根，两版本共用，不必复制。
4. 同步后提醒用户重启客户端；不要声称已发布。

## 验证

至少运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_helper_tools.py tests\test_platform_content.py tests\test_publisher_guides.py tests\test_ui_theme.py tests\test_client_problem_center.py
.\.venv\Scripts\python.exe -m ruff check app\versions\0.1.0\signriver_app\application\helper_tools.py app\versions\0.1.0\signriver_app\application\guides.py app\versions\0.1.0\app_entry.py src\signriver_publisher\client_guides.py tests\test_helper_tools.py
.\.venv\Scripts\python.exe -m compileall -q app\versions\0.1.0 app\versions\<active_version>
```

## 参考实现

当前样例：`close-windows-defender`。杀毒软件检测列表下方横条跳转到该教程；正文按需使用 `tool:dcontrol` 按钮进入工具详情页。后续同类教程复制该指南 JSON 和 helper 字段即可，不要复制一套新的下载器。
