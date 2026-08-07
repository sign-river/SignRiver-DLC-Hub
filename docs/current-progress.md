# SignRiver DLC Hub 当前进度

更新时间：2026-08-07（Asia/Shanghai）

## 当前结论

- 当前程序版本：`0.1.3`
- Host API：`2`
- 更新类型：`full`
- `0.1.3` 已于 2026-08-01 双源发布（GitHub 与 GitLink 的 `updates` Release，23,550,648 字节 / SHA256 `712cf5...`）。
- 本地 2026-08-07 已用 UPX 重建全量包：18,753,701 字节 / SHA256 `baf1fb...`（EXE 从 176.9MB 压缩回 17.3MB），包含最新源码改动，尚未上传，与线上不一致。
- 已修复 `tools/restore_module_archives.py` 的 GitLink 下载地址（去掉错误的 `/api/` 前缀，并按平台区分仓库所有者），实测可从 GitLink 恢复 v0.1.3 模块归档。
- 已为 `tools/build_release.py` 接入 UPX 探测（`--upx-dir` / PATH）；本机 UPX 5.0.2 下构建产物：启动器 EXE 17,279,062 字节、全量更新包 18,753,701 字节（SHA256 `baf1fb5e...`）。
- 两个平台的清单均指向各自平台的下载地址，不会跨源下载。
- GitLink 的重复 `update-manifest.json` 已清理，目前只保留一份。
- 源码修改尚未提交或推送，当前工作区不是干净状态。

## 已完成内容

### 下载源与更新源联动

- 选择 GitLink 时，从 GitLink 获取清单并下载更新包。
- 选择 GitHub 时，从 GitHub 获取清单并下载更新包。
- 切换下载源后立即同步更新服务配置。
- GitLink、GitHub 使用各自独立的 `package_url`。

### 全量更新

- 修复 Windows 更新助手使用 `os.kill(pid, 0)` 导致的
  `OSError: [WinError 6] 句柄无效`。
- Windows 上改用 `OpenProcess + WaitForSingleObject` 等待旧程序退出，
  不再误终止父进程。
- 更新助手和更新后重启进程使用安全的空标准输入输出句柄。
- 新版启动器使用更新包内的新 EXE 作为更新助手。
- 已准备但尚未应用的残留事务会在下次启动时自动回滚清理。
- 全量更新成功后会激活新模块；失败时恢复受管文件和旧活动版本。
- `data/`、`cache/`、`app/state.json` 和用户更新源配置不由全量更新覆盖。

### 发布器

- 程序更新上传已接入真实进度：
  - 单源发布显示更新包与清单两个阶段。
  - 双源发布显示 GitLink 包、GitHub 包、GitLink 清单、GitHub 清单四个阶段。
  - 显示百分比、已传大小、总大小和上传速度。
- 更新包选择后会自动读取：
  - `release-manifest.json`：识别为 `full`。
  - `module.json`：识别为 `module`。
  - 元数据中的 `version`：自动作为发布版本。
- 文件名中的版本和类型会与包内元数据交叉校验。
- 不再手工输入版本号和 `full/module`，只需填写更新说明并选择是否强制更新。
- GitLink 发布时会读取发行版编辑详情，取得可删除的附件 UUID。
- 同名附件会先从 Release 中替换，再清理全部旧附件，避免固定下载链接继续返回旧清单。
- GitHub 继续使用同名 Release Asset 替换机制。

## 远端发布状态

核验时间：2026-08-07；两个平台的 `updates` Release 均已发布 `0.1.3`（2026-08-01 上传，23,550,648 字节 / SHA256 `712cf5...`）。

### GitHub

- 清单状态：HTTP `200`
- 清单版本：`0.1.3`
- 类型：`full`
- 下载包：
  `https://github.com/sign-river/signriver-dlc-assets/releases/download/updates/SignRiver-DLC-Hub-full-v0.1.3-windows-x64.zip`
- `updates` Release 当前受管附件：
  - `SignRiver-DLC-Hub-full-v0.1.1-windows-x64.zip`
  - `SignRiver-DLC-Hub-full-v0.1.2-windows-x64.zip`
  - `SignRiver-DLC-Hub-full-v0.1.3-windows-x64.zip`
  - `update-manifest.json`
- `modules` Release：**不存在**，模块归档 v0.1.1/v0.1.2/v0.1.3 均返回 HTTP `404`，需创建 Release 并上传。

### GitLink

- 清单状态：HTTP `200`
- 清单版本：`0.1.3`
- 类型：`full`
- 下载包：
  `https://gitlink.org.cn/signriver/signriver-dlc-assets/releases/download/updates/SignRiver-DLC-Hub-full-v0.1.3-windows-x64.zip`
- `modules` Release：模块归档 v0.1.1/v0.1.2/v0.1.3 均已存在，下载大小与 SHA256 和 `config/module-archives.json` 一致。
- `update-manifest.json` 数量：`1`

GitLink 的 `updates.ZIP`、`updates.TAR.gz` 以及 GitHub 的 Source code
属于平台自动生成的源码归档，不是客户端更新包。

## 当前产物

### 客户端全量更新包

路径：

`dist/updates/SignRiver-DLC-Hub-full-v0.1.3-windows-x64.zip`

- 大小：`18,753,701` 字节（2026-08-07 UPX 重建版）
- SHA256：
  `baf1fb5ec2ce523bd9be4ed7e392431802882d48927dac89f507ce19767d7497`
- 注：线上 2026-08-01 发布的仍是旧版（23,550,648 字节 / `712cf5...`），新版尚未上传。

对应清单：

- `dist/updates/gitlink/update-manifest.json`
- `dist/updates/github/update-manifest.json`

### 首次安装包

- `dist/唏嘘南溪DLC一键解锁工具-v0.1.3-windows-x64.zip`
- `dist/唏嘘南溪DLC一键解锁工具-v0.1.3-windows-x64-自解压.exe`

### 模块归档

- `dist/modules/SignRiver-DLC-Hub-module-v0.1.3.zip`
- 大小：`182,152` 字节
- SHA256：
  `17dd3b3bf8fa106494cce27ec0f99b4cee5efd59618b377944abc9d13e30c1c0`

### 发布器

路径：

`dist/publisher/SignRiver-Publisher.exe`

- 大小：`19,711,015` 字节
- SHA256：
  `a17ff796fc020e50579d865ba4b7ac8f42e2ca87838588f4132eb9a3fb032c83`

### 更新测试基线

- `dist/test-baselines-fixed-launcher-v0.1.2/SignRiver-test-baseline-v0.1.1-gitlink.zip`
- `dist/test-baselines-fixed-launcher-v0.1.2/SignRiver-test-baseline-v0.1.1-github.zip`

这些基线只用于本地更新测试，不得上传到公开 Release。

## 验证结果

- 完整测试：`472` 项通过。
- Ruff 静态检查：通过。
- Git diff whitespace 检查：通过。
- 冻结版全量更新端到端测试：
  - 父进程退出码：`0`
  - 更新助手退出码：`0`
  - 更新事务状态：`confirmed`
  - 活动版本：`0.1.2`
  - 未再出现 `WinError 6`
- `0.1.3` 更新包结构、ZIP 完整性、内部版本和双源清单哈希校验通过。
- 更新包自动识别实测：
  - 版本：`0.1.3`
  - 类型：`full`
- GitLink 编辑接口实测可取得重复清单对应的两个附件 UUID，并完成同名清理。

## 已知限制

### 旧启动器不能通过全量更新自我修复

旧版 `0.1.0` 启动器会复制自己的旧 EXE 作为更新助手，因此它在执行全量更新时仍会触发
旧的 Windows 句柄错误。这个缺陷无法只靠替换远端 ZIP 修复已经安装的旧启动器。

处理方式：

- `0.1.2` 作为新的首次安装版本提供。
- 已安装旧版的测试用户需要手动安装 `0.1.2`。
- 从 `0.1.2` 开始，后续全量自动更新使用更新包中的新助手，可以正常升级。
- `fixed-launcher-v0.1.2` 测试基线仅用于验证修复后的更新链路，不代表旧
  `0.1.0` 能直接自愈。

### 程序更新上传暂停

普通资源发布仍支持暂停和继续。程序更新发布目前显示实时进度，但不支持中途暂停。

## 上传与保留规则

### 应上传

- 普通程序 Release：
  - `唏嘘南溪DLC一键解锁工具-v0.1.3-windows-x64.zip`
  - `唏嘘南溪DLC一键解锁工具-v0.1.3-windows-x64-自解压.exe`
- `updates` Release：
  - `SignRiver-DLC-Hub-full-v0.1.3-windows-x64.zip`
  - 对应平台的 `update-manifest.json`
- `modules` Release：
  - `SignRiver-DLC-Hub-module-v0.1.3.zip`

使用新版发布器的“双源镜像发布更新”时，更新 ZIP 和两份清单会自动按安全顺序上传。

### 应保留

- 源码中的：
  - `app/versions/0.1.0`
  - `app/versions/0.1.1`
  - `app/versions/0.1.2`
  - `app/versions/0.1.3`
- 远端版本化更新包：
  - `SignRiver-DLC-Hub-full-v0.1.1-windows-x64.zip`
  - `SignRiver-DLC-Hub-full-v0.1.2-windows-x64.zip`
- 当前唯一的 `update-manifest.json`
- 回滚测试未结束前的 `.update-backup/`

### 禁止上传

- `dist/publisher/publisher.local.json`
- `config/publisher.local.json`
- `publisher-workspace/`
- `dist/test-baselines/`
- `dist/test-baselines-fixed-launcher-v0.1.2/`
- 任何包含 GitLink/GitHub 私有令牌的文件

## 后续建议

1. 使用新版发布器先向 GitLink 和 GitHub 上传 `0.1.3` ZIP，确认可下载后再上传清单。
2. 从两个独立的 `0.1.2` 安装目录分别执行 `0.1.2 → 0.1.3`。
3. 验证更新后自动启动、版本显示、下载源保留和回滚。
4. 检查工作区差异后提交源码，并分别推送到 GitLink 和 GitHub。
5. 提交前确认私有配置和测试基线未被加入 Git。
