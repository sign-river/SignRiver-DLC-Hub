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

发布新工具时，先为整个 `tools` Release 更新统一的 `tools_index.json`，再把工具附件和索引上传到两个源；指南详情 JSON 只按 `tool_id` 做可选关联引用。不要为单个工具另建 Release，也不要把工具附件复制到 `publisher-workspace/guides/assets/`。

由 `fixed_release_asset_url(download_source, "tools", asset_name)` 生成，禁止把源写死在按钮回调里。

工具目录约定：`tools_index.json` 是整个 `tools` Release 的唯一工具目录；每个条目必须包含稳定 `tool_id`、标题、说明、`asset_name`、`filename`、`revision`、`platforms`、`package_kind`、`launch_action` 和 `release_tag: "tools"`。工具文件即使尚未下载，也应凭索引在“常用工具”中显示。

## 发布拓展指南和工具

发布源严格分开：

| 资源 | 发布器工作区 | Release | 索引 |
| --- | --- | --- | --- |
| 拓展指南 | `publisher-workspace/guides/` | `guides` | `guides_index.json` |
| 工具包 | `publisher-workspace/tools/assets/` | `tools` | `publisher-workspace/tools/tools_index.json` |

使用发布器“发布资源统一管理”页的“预检并双端发布扩展”，不要再分别手工上传。该按钮会先检查：

- 每篇指南索引和正文是否齐全；
- `tools_index.json` 的工具 ID、元数据和工具包是否齐全；
- 每个 `release_tag: "tools"` 的指南引用是否指向已有 `tool_id`；
- 如果指南重复填写了工具的文件名、版本、平台或启动字段，是否与工具索引一致。

预检失败时不会开始上传。预检通过后，发布器会把指南和工具分别同步到 GitLink、GitHub 的 `guides` / `tools` Release；同名的已变更附件直接覆盖。

发布器为 GitLink 与 GitHub 分别保存本地成功发布的 SHA-256 状态。下次发布时只上传本地内容发生变化的附件，未变化的附件跳过；此判断不下载云端文件作内容比较。若有人手动删除云端附件而本地文件和本地状态均未变化，发布器不会自动补回，需修改文件或清除对应本地发布状态后重新发布。

指南正文里的 `tools` 条目推荐只保留：

```json
{
  "tool_id": "example-tool",
  "release_tag": "tools"
}
```

工具的完整标题、说明、文件名、版本、平台与启动方式只在 `tools_index.json` 维护，避免两处元数据漂移。

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
- 从安全软件检测进入时 `origin="security_products"`，返回必须回到「常用工具 → 安全软件检测」，不得跨层回到报错指南。
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

当前样例：`close-windows-defender`。安全软件检测列表下方横条跳转到该教程；标题下下载/启动 `dControl`。后续同类教程复制该指南 JSON 和 helper 字段即可，不要复制一套新的下载器。
