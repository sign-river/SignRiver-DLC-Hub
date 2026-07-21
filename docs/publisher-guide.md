# SignRiver 发布管理器

发布管理器是独立于普通用户客户端的维护工具。它只负责整理源文件、生成发布包和向独立的 GitLink 资源仓库发布；客户端继续负责读取 Release、下载和安装。

## 游戏机 / 卡带模型

发布器相当于服务端“制卡机”，`publisher-workspace/games` 下的每个游戏目录都是一张独立卡带。卡带的 `game.json` 声明游戏 ID、Steam App ID、Release 标签、AppInfo 文件名以及该游戏使用的两个补丁 DLL 文件名；构建、增量发布和远程资源管理始终只操作当前卡带。

客户端游戏列表来自资源仓库的 `hub` Release：先下载很小的 `cartridges_index.json` 主表，再按用户选择按需下载 `cartridge_<game_id>.json`。启动公告来自同一 Release 的 `announcement.json`；发布器工作区根目录若存在该文件，导出客户端卡带主表时会一并写入 `output/hub`。客户端设置可在 GitLink（默认）与 GitHub 间切换；两边使用相同的标签与文件名，GitHub 默认仓库为 `sign-river/signriver-dlc-assets`。发布器“导出客户端卡带主表”会把当前全部卡带写成可上传文件，并可通过发布目标选择 GitLink 或 GitHub。

本地构建页提供「检测最新 DLC」：向 Steam Store 拉取官方 DLC 列表，与当前卡带 `dlc/` 包数量对比，标注“已是最新 / 可能不是最新”，并写入 `games/<id>/freshness.json`。导出客户端卡带时会附带完整度摘要；客户端在 DLC 列表上方展示该状态与检测时间。注意 Steam 列表可能含音乐包/外观等条目，数量差仅作提示，仍需人工核对后导入。

发布验收中的补丁目录同样读取当前卡带的 `patch_relative_dir`，不会固定为 Stellaris 或文明 6 的目录。选择实际游戏目录时必须与顶部当前卡带一致；若目录不存在，提示会同时显示当前卡带与它配置的目标路径。

客户端与服务端使用相同边界：客户端插入游戏卡带后读取对应 Release 并执行该游戏的检测、下载和安装；服务端选择同一游戏卡带后构建并更新对应 Release。新增游戏时不应在主程序中增加游戏名判断，而应新增一张卡带配置及其游戏专属实现。

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
- DLC ZIP 采用增量构建：新增或源文件发生变化时才重新压缩，未变化的 ZIP 直接复用。旧版本已经生成且与源目录匹配的 ZIP 会在首次新版构建时自动纳入缓存。
- GitLink 单附件限制为 300 MB；发布器会把超过 280 MiB 的 DLC ZIP 自动拆成 `原文件.zip.part001-of-XXX` 分卷，随后删除本地超限完整 ZIP，只保留可增量复用的分卷。Release 只上传分卷。客户端会检查卷号是否连续，按顺序下载并还原成原始 ZIP 后再校验和安装；缺少任意一卷时不会向用户展示该 DLC。
- `patches` 下只需放入该游戏适用的 `steam_api64.dll` 和原版备份 `steam_api64_o.dll`。
- 发布器根据游戏配置中的 Steam App ID 主动查询 Steam，构建并上传 `<game_id>_appinfo.json`；无需人工准备该文件。
- AppInfo 文件名由游戏 ID 自动确定且不会跨游戏混用：`stellaris` 生成 `stellaris_appinfo.json`，例如 `europa_universalis_4` 会生成 `europa_universalis_4_appinfo.json`。
- “刷新 Steam 数据”可以单独重新生成 AppInfo；“生成全部发布文件”也会自动刷新一次，避免发布旧 DLC 信息。
- Steam 请求会自动重试，但 AppInfo 不使用旧缓存。每次完整构建都必须重新请求 Steam 并重写 AppInfo；刷新失败时构建终止，同时移除旧 AppInfo，防止误发布过期数据。
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

客户端补丁安装做成可回滚事务：先审计游戏目录中现有 `steam_api64.dll` 与 `steam_api64_o.dll` 的大小并与发布器产物比对，判定 `HEALTHY / ORIGINAL / MODIFIED / UNKNOWN` 四种状态；随后按下列规则处理：

- `HEALTHY`（补丁 DLL 与原版备份都与我们的一致）跳过替换，仅在 INI 需要更新时以原子写覆盖 `cream_api.ini`。
- `ORIGINAL`（当前只有原版 DLL，尺寸与 `steam_api64_o.dll` 一致）把它重命名为 `steam_api64_o.dll`，再原子写入我们的补丁 DLL。
- `MODIFIED` / `UNKNOWN`（同名文件大小与我们的产物差距过大，或备份缺失）判定为损坏或第三方补丁，用发布器的 DLL 强制替换并在必要时补建原版备份。
- 所有替换都通过 `write-temp + os.replace` 完成，失败时按操作顺序逆序回滚到事务开始前的状态。

`cream_api.ini` 使用发布器上传的 `<game>_appinfo.json` 及各游戏独立的 INI 模板渲染，AppInfo 中的 `appid` 与 `dlcs` 与模板占位符组合后以 UTF-8 BOM 落盘；模板不再硬编码 Stellaris 的 App ID，可为每个游戏在客户端侧提供独立的 `PatchTemplate`。

客户端主入口是简洁视图上的三枚按钮：

- **一键解锁**：先做补丁审计，若不健康就把三件补丁下载到内容寻址缓存并顺序应用（下载补丁 → 应用补丁 → 依次下载安装勾选的 DLC）；补丁已健康则直接跳到 DLC 下载/安装阶段。按钮文本会随阶段变成“正在下载补丁… / 正在应用补丁…”，并阻塞其他破坏性操作。
- **一键修复**：二次确认后卸载全部已安装 DLC、清空下载记录与内容缓存、`patch_engine.reset(game_root)` 抹掉补丁三件套，然后重新走一次一键解锁流程；提示用户会下载大量数据。
- **缓存复用**：卸载游戏不会删除客户端缓存，重新安装游戏后，同一 DLC 可直接从内容寻址缓存恢复并安装。补丁 DLL 和 AppInfo 使用 Release 附件 ID 作为缓存版本；服务端重新发布附件后客户端会下载新版本，不会把旧的同名补丁当作当前版本。
- **一键移除补丁**：只做卸载：删除补丁 DLL 与 `cream_api.ini`，把 `steam_api64_o.dll` 恢复为 `steam_api64.dll`。任一步骤失败都回滚到操作前状态。

## 卡带中的安装位置

每个游戏卡带独立声明客户端安装位置，路径均相对于该游戏的根目录：

- `dlc_relative_dir`：DLC 目录，例如 Stellaris 为 `dlc`，其他游戏可以是 `content/addons`。
- `patch_relative_dir`：补丁三件套所在目录，例如根目录用 `.`，也可以是 `bin/win64`。

客户端的安装、已安装扫描、卸载和修复会统一读取这两个字段。服务端的“游戏卡带配置”页面也保存相同字段，便于新增游戏时完整记录发布协议。两者都拒绝绝对路径和包含 `..` 的越界路径。

当前预置五张 Steam 卡带：

| 游戏 | Steam App ID | Release 标签 | DLC 安装目录 | 补丁安装目录 | AppInfo |
| --- | ---: | --- | --- | --- | --- |
| Stellaris | `281990` | `stellaris` | `dlc` | `.` | `stellaris_appinfo.json` |
| Civilization VI | `289070` | `civilization_6` | `DLC` | `Base/Binaries/Win64Steam` | `civilization_6_appinfo.json` |
| Hearts of Iron IV | `394360` | `hearts_of_iron_4` | `dlc` | `.` | `hearts_of_iron_4_appinfo.json` |
| 城市天际线 | `255710` | `cities_skylines` | `Files` | `.` | `cities_skylines_appinfo.json` |
| 边缘世界 | `294100` | `rimworld` | `Data` | `.` | `rimworld_appinfo.json` |

首次启动新版服务端管理器时，会为缺失的内置卡带自动创建本地工作区，不覆盖已有游戏配置。为新游戏准备资源时：

1. 在游戏卡带对应的 `dlc` 工作区中放入 DLC 文件夹；服务端会将每个文件夹单独压缩。`manual_prefixed` 卡带要求使用 `dlcNNN_英文名称`，`auto_prefix` 卡带可直接通过“导入 DLC”选择原始目录并由服务端分配稳定编号。
2. 在对应 `patches` 工作区放入该游戏自己的 `steam_api64.dll` 和 `steam_api64_o.dll`。
3. 点击构建，让服务端从 Steam 获取并生成该卡带对应的 `xxx_appinfo.json`。
4. 在 GitLink 仓库创建与表格一致的 Release 标签，再执行发布。

文明 6、城市天际线与边缘世界使用通用目录包检查器，目录内部不要求 Stellaris 的 `.dlc + 内层 ZIP` 结构。这些卡带启用 `auto_prefix + children_if_root`：通过“导入 DLC”既可选择单个原始目录，也可选择游戏的整个 DLC 根目录；选择根目录时会把每个一级子文件夹分别导入为 `dlc001_...` 等独立资源。附件叫 `dlc001_Expansion1.zip`，但 ZIP 顶层及客户端最终安装目录仍为原始文件夹名。导入在后台进行，并先复制到临时区后再落位，避免窗口卡死或留下半份资源。编号计数单独持久化，删除旧资源后不会随意复用编号。钢铁雄心 4 和 Stellaris 默认使用 `manual_prefixed + single_directory`，适合自带编号或需要人工保持固定编号的资源。

## GitLink 仓库

默认新仓库为 `signriver/signriver-dlc-assets`。在新仓库成功创建、首个 Release 上传并验证以前，不要修改客户端当前的资源仓库。

“检查登录与仓库”、日常上传、Release 更新和远程附件管理都直接使用 GitLink API，不要求安装额外工具。只有“一键创建新仓库”按钮需要 GitLink 官方 CLI；也可以先在网页手动创建仓库：

```powershell
npm install -g @gitlink-ai/cli
gitlink-cli auth login
```

发布时，管理器按 GitLink 官方 API 的流程逐个流式上传文件，取得附件 ID，再创建或更新 Release。令牌可以来自私有本地配置、`GITLINK_TOKEN` 环境变量或界面输入，且不会输出到日志。发布成功后，未由本地配置提供的临时令牌会立即清空。

也可以把长期使用的令牌写入 `config/publisher.local.json`。该文件已被 Git 精确忽略，公开仓库只保留不含真实令牌的 `config/publisher.example.json`。发布器启动时会自动读取本地配置；可通过 `SIGNRIVER_PUBLISHER_CONFIG` 环境变量指定其他位置。

构建独立 EXE 时，本地配置会作为单独的 `publisher.local.json` 复制到 EXE 同目录，不会嵌入可执行文件。对外分发发布器时不要附带这个私密文件，只分发 EXE 和 `publisher.example.json`。

如果同一游戏标签的 Release 已存在，发布器会更新它的附件列表；否则会创建新 Release。首次正式发布前建议先用少量测试文件验证账号权限和仓库配置。

完整发布采用增量同步：只有新增或哈希发生变化的文件会上传，未变化文件复用原远程附件 ID；每个游戏的 AppInfo 始终强制上传并替换。Release 更新成功后才清理被替换或本地已删除的旧附件；更新失败时会回收本次新上传的附件并保留原 Release。首次没有本地发布状态时会安全地完整上传一次。

GitLink 更新 Release 时必须使用 `version_id`，不能使用列表中的普通 `id`。如果旧版本已经上传附件但未正确挂载，发布器会并行检查本地状态保存的附件 ID，确认文件名匹配后重新挂载，避免再次上传大文件。

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

## 发布验收

“发布验收”页面用于在正式发布前组织人工测试，不会一键修改游戏文件或自动判定客户端是否成功。验收清单由通用项目和卡带专属项目组成：所有游戏都有路径与卡带切换、DLC 识别、下载控制、补丁异常、安全恢复、一键修复和界面刷新等检查；使用“去掉管理编号”目录结构的卡带还会自动增加编号附件与实际游戏目录映射检查。

使用顺序：

1. 选择本轮实际运行的客户端 EXE，以及当前卡带对应的实际游戏目录。
2. 点击“刷新指纹”。指纹绑定客户端 EXE 与活动模块、当前卡带配置和本地发布资源内容。
3. 按左侧清单逐项构造环境、操作客户端并核对预期结果。
4. 可随时使用“检查并记录”生成只读环境快照，或者使用“收集日志”复制客户端日志作为证据。
5. 根据人工观察标记“通过”“失败”或“跳过”，备注会随当前结果保存。

只要客户端、卡带配置或本地发布资源发生变化，当前轮次就会显示“已过期”，且不能继续写入结果；点击“开始新一轮”后，旧轮次会归档并保留，新轮次从未测试状态开始。

验收数据按游戏隔离保存：

```text
publisher-workspace/
└─ acceptance/
   ├─ settings.json
   ├─ stellaris/
   │  ├─ current.json
   │  ├─ history/
   │  └─ evidence/
   ├─ civilization_6/
   ├─ hearts_of_iron_4/
   ├─ cities_skylines/
   └─ rimworld/
```

`settings.json` 只记录本机待测客户端和游戏目录；`current.json` 保存当前轮次；`history` 保存旧轮次；`evidence` 保存环境快照和复制出的日志。整个 `publisher-workspace` 已被 Git 忽略，不会把本机路径、测试记录或日志提交到公开仓库。

“检查并记录”只读取客户端、游戏根目录、DLC 目录、补丁目录和日志文件状态，不删除、不移动、不覆盖游戏文件。补丁缺失、安全软件隔离等破坏性场景仍由测试人员按照单项说明手动准备，并应先在外部位置建立完整备份。

### 补丁测试环境工具

发布验收页提供「补丁失败场景」清单。每项对应一种坏补丁状态，可点「构建该环境」一键生成；测完后务必点「恢复测试环境」。使用顺序：

1. 选择待测客户端与实际游戏目录，刷新指纹并开始/沿用当前轮次。
2. 首次构建前会提示记录补丁基线（只备份两个 DLL 和 `cream_api.ini`，不改游戏文件）。也可手动点「记录补丁基线」。
3. 关闭游戏和客户端后，在场景列表中点对应项的「构建该环境」，确认将被修改的路径。
4. 启动客户端验证预期行为；测完后点「恢复测试环境」。
5. 「安全软件隔离」无法在程序内安全模拟，仍需人工操作。

当前自动场景包括：干净首次安装、当前 DLL 缺失、原版备份 DLL 缺失、INI 缺失、当前 DLL 内容异常。安全软件隔离等无法可靠控制的场景仍保持人工操作。

执行准备前会再次确认当前文件与基线一致；如果记录基线后文件已经变化，程序拒绝执行，避免覆盖新的用户内容。环境准备先写入“待恢复”标记再修改文件；任一步失败会自动回滚，只有完整恢复后才清除标记。发布管理器重新启动后仍会识别未恢复环境，关闭程序时也会显示警告。
