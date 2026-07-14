# SignRiver 发布管理器

发布管理器是独立于普通用户客户端的维护工具。它只负责整理源文件、生成发布包和向独立的 GitLink 资源仓库发布；客户端继续负责读取 Release、下载和安装。

## 启动

在项目目录运行：

```powershell
.\.venv\Scripts\python.exe publisher.py
```

首次启动会建立 `publisher-workspace`：

```text
publisher-workspace/
├─ games/
│  └─ stellaris/
│     ├─ game.json
│     ├─ dlc/
│     │  └─ dlc001_symbols_of_domination/
│     └─ patches/
│        ├─ steam_api64.dll
│        └─ steam_api64_o.dll
└─ output/
   └─ stellaris/
      ├─ steam_api64.dll
      ├─ steam_api64_o.dll
      └─ stellaris_appinfo.json
```

需要独立 EXE 时运行：

```powershell
.\.venv\Scripts\python.exe tools\build_publisher.py
```

产物位于 `dist\publisher\SignRiver-Publisher.exe`。

- 每个 DLC 必须是 `dlc编号_英文名称` 格式的独立文件夹。
- 点击“生成全部发布文件”后，每个 DLC 文件夹会生成一个同名 ZIP。
- `patches` 下只需放入该游戏适用的 `steam_api64.dll` 和原版备份 `steam_api64_o.dll`。
- 发布器根据游戏配置中的 Steam App ID 主动查询 Steam，构建并上传 `<game_id>_appinfo.json`；无需人工准备该文件。
- AppInfo 文件名由游戏 ID 自动确定且不会跨游戏混用：`stellaris` 生成 `stellaris_appinfo.json`，例如 `europa_universalis_4` 会生成 `europa_universalis_4_appinfo.json`。
- “刷新 Steam 数据”可以单独重新生成 AppInfo；“生成全部发布文件”也会自动刷新一次，避免发布旧 DLC 信息。
- AppInfo 是客户端生成 `cream_api.ini` 的 Steam 元数据源，不是发布器自定义的资源校验清单。
- `cream_api.ini` 不需要放入发布目录。客户端打补丁时根据 AppInfo 和固定模板生成它。
- `patches` 下的其他普通文件原样复制；子文件夹压缩为同名 ZIP。
- 新游戏通过“游戏配置 → 新增游戏”创建，不同游戏的输入、输出和 Release 标签互不混用。

## 补丁数据与客户端流程

以 Stellaris 为例，服务端最终发布以下三个补丁资源：

```text
steam_api64.dll       # 新补丁 DLL
steam_api64_o.dll     # 与当前游戏版本对应的原版 DLL / 恢复文件
stellaris_appinfo.json
```

客户端根据 `stellaris_appinfo.json` 生成 `cream_api.ini`。字段映射为：

- `app_id` → `[steam] appid`
- `dlcs[].id` → `[dlc]` 左侧 ID
- `dlcs[].name` → `[dlc]` 右侧名称
- DLC 顺序保持与 AppInfo 一致
- 默认模板为 `language=schinese`、`unlockall=True`、`extraprotection=False`、`forceoffline=False`

客户端补丁安装需要做成可回滚事务：检查游戏未运行，确认目标 DLL 状态，保留原版 `steam_api64_o.dll`，原子替换 `steam_api64.dll`，再以 UTF-8 BOM 写入 `cream_api.ini`。重复安装只更新补丁 DLL 和 INI，不能把已经安装的补丁 DLL 覆盖到原版备份中。

卸载补丁时删除补丁 DLL 和 `cream_api.ini`，把 `steam_api64_o.dll` 恢复为 `steam_api64.dll`。任一步骤失败都应回滚到操作前状态。

## GitLink 仓库

默认新仓库为 `signriver/signriver-dlc-assets`。在新仓库成功创建、首个 Release 上传并验证以前，不要修改客户端当前的资源仓库。

日常上传与 Release 更新直接使用 GitLink 官方 API，不要求安装额外工具。只有“一键创建新仓库”按钮需要 GitLink 官方 CLI；也可以先在网页手动创建仓库：

```powershell
npm install -g @gitlink-ai/cli
gitlink-cli auth login
```

发布时，管理器按 GitLink 官方 API 的流程逐个流式上传文件，取得附件 ID，再创建或更新 Release。令牌可以来自私有本地配置、`GITLINK_TOKEN` 环境变量或界面输入，且不会输出到日志。发布成功后，未由本地配置提供的临时令牌会立即清空。

也可以把长期使用的令牌写入 `config/publisher.local.json`。该文件已被 Git 精确忽略，公开仓库只保留不含真实令牌的 `config/publisher.example.json`。发布器启动时会自动读取本地配置；可通过 `SIGNRIVER_PUBLISHER_CONFIG` 环境变量指定其他位置。

构建独立 EXE 时，本地配置会作为单独的 `publisher.local.json` 复制到 EXE 同目录，不会嵌入可执行文件。对外分发发布器时不要附带这个私密文件，只分发 EXE 和 `publisher.example.json`。

如果同一游戏标签的 Release 已存在，发布器会更新它的附件列表；否则会创建新 Release。首次正式发布前建议先用少量测试文件验证账号权限和仓库配置。

## 远程资源管理

“远程资源”页面只管理当前游戏配置所对应的 GitLink 仓库和 Release 标签，不会操作其他游戏的 Release。

- “刷新远程”会读取当前 Release 中已经挂载的附件。
- 本地输出文件可以直接上传，也可以通过“选择文件上传”添加任意准备好的资源。
- 上传同名文件会替换 Release 中的旧附件；上传不同名文件会追加到现有附件列表。
- 点击远程附件旁的“删除”会先将它从 Release 中解除挂载，再删除 GitLink 上的附件文件。
- 上传或删除过程中如果后续步骤失败，程序会尽量回滚或显示明确警告，避免静默留下未挂载的附件。
- 第一次上传到尚不存在的标签时，程序会自动创建该 Release。

批量“发布到 GitLink”适合一次性发布当前构建结果；“远程资源”页面适合后续单独补充、替换或删除某个 DLC、补丁或 AppInfo 文件。

## 删除说明

资源页的删除只会删除当前发布工作区中的源文件，并会要求二次确认。它不会自动删除已经发布到 GitLink 的旧附件；远程附件需要在“远程资源”页面中单独删除。重新生成时，输出目录里不再属于当前游戏资源的旧文件会被清理。
