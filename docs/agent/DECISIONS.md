# SignRiver DLC Hub 决策记录

> 这里只记录仍影响后续设计的长期约束；逐次操作和旧决策原文见 [`archive/DECISIONS-2026-09-04-history.md`](archive/DECISIONS-2026-09-04-history.md)。

## 发布与更新

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
