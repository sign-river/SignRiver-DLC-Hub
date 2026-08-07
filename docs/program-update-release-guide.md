# 程序更新发布指南

## 当前测试版本

- 基线版本：`0.1.2`
- 待测版本：`0.1.3`
- 本次更新类型：`full`
- 原因：验证修复后启动器的完整自动升级链路，并交付全量更新可靠性与双源发布流程
  改进；需要发布包含新启动器的全量包。

`app/versions/0.1.0`、`app/versions/0.1.1` 和 `app/versions/0.1.2` 必须保留，
作为 `0.1.3` 启动失败时的本地回滚版本。

## 构建与准备

> 说明：`build_release.py` 会自动从 PATH 查找 UPX（也可用 `--upx-dir` 显式指定）。
> 没有 UPX 时启动器 EXE 不会压缩（约 177MB），构建会打印显式警告；
> 安装 UPX 后 EXE 约 17MB、全量更新包约 19MB。UPX 仅需在构建机上使用，
> 不随发布包分发。


```powershell
.\.venv\Scripts\python.exe tools\build_release.py --upx-dir C:\Users\32173\AppData\Local\tools\upx\upx-5.0.2-win64
.\.venv\Scripts\python.exe tools\prepare_update_release.py `
  dist\updates\SignRiver-DLC-Hub-full-v0.1.3-windows-x64.zip `
  --version 0.1.3 --kind full --min-launcher-version 0.1.2 `
  --notes "改进全量更新可靠性与双源发布流程"
```

## `updates` Release 上传清单

两个平台使用同一个 Release 标签：`updates`。

### GitLink

仓库：`signriver/signriver-dlc-assets`

上传：

1. `dist/updates/SignRiver-DLC-Hub-full-v0.1.3-windows-x64.zip`
2. `dist/updates/gitlink/update-manifest.json`

### GitHub

仓库：`sign-river/signriver-dlc-assets`

上传：

1. `dist/updates/SignRiver-DLC-Hub-full-v0.1.3-windows-x64.zip`
2. `dist/updates/github/update-manifest.json`

发布顺序必须是“两边先上传 ZIP，两边确认 ZIP 可下载，再上传各自清单”。发布器的
“双源镜像发布程序更新”按钮已经按这个顺序执行。

不要上传以下文件到 `updates` Release：

- `唏嘘南溪DLC一键解锁工具-v0.1.3-windows-x64.zip`：这是带外层目录的首次安装包。
- `唏嘘南溪DLC一键解锁工具-v0.1.3-windows-x64-自解压.exe`：这是首次安装自解压包。
- GitLink 的清单不能上传到 GitHub，GitHub 的清单也不能上传到 GitLink；两者的
  `package_url` 不同。

## 历史模块归档

历史 `app/versions/<version>` 可通过以下命令压缩，供构建留档与人工恢复使用：

```powershell
.\.venv\Scripts\python.exe tools\build_module.py --all-versions app\versions
```

在发布器中选择“发布模块归档”或“双源镜像归档”。发布器会读取 ZIP 根目录的
`module.json` 自动识别版本。两个按钮默认绑定 `dist/modules/`：会校验并一次上传该
目录中的全部 `SignRiver-DLC-Hub-module-v*.zip` 到独立的 `modules` Release；该操作
不写入 `updates/update-manifest.json`，不会触发客户端更新。归档 ZIP 上传前仍应保留
本地版本目录，直到下载、SHA-256 校验和构建恢复流程完成验收。

本次需将 `dist/modules/SignRiver-DLC-Hub-module-v0.1.3.zip` 上传到两个平台的
`modules` Release，供干净源码环境按 `config/module-archives.json` 恢复构建。

## 保留与删除

必须保留：

- 当前清单 `update-manifest.json`。
- 当前清单引用的 `SignRiver-DLC-Hub-full-v0.1.3-windows-x64.zip`。
- 本地源码中的 `app/versions/0.1.0`、`app/versions/0.1.1`、
  `app/versions/0.1.2` 和 `app/versions/0.1.3`。
- 测试期间的 `0.1.2` 基线安装目录，不要在原目录覆盖安装新版。

建议至少保留到下一版验证完成：

- 上一个已经发布且验证通过的版本化更新 ZIP。
- 对应版本的首次安装 ZIP/SFX（放在普通版本 Release，不放在 `updates`）。
- `.update-backup/<transaction-id>`；确认升级和回滚测试完成后再清理。

可以替换：

- `update-manifest.json`：这是 `updates` Release 中唯一固定名称、每次发布都会替换
  的文件。
- 同版本号的测试 ZIP 可以在尚未对外开放时替换；一旦清单已公开，修改 ZIP 后必须
  重新生成并最后上传清单，确保大小和 SHA-256 同步。

不要删除：

- 当前清单仍引用的包。
- 用户安装目录中的 `data/`、`cache/`、`app/state.json`、`config/update.json`。
- 回滚测试尚未完成时的 `0.1.2` 模块或 `.update-backup`。

## 人工测试

准备两个独立的 `0.1.2` 基线目录，一个选择 GitLink，一个选择 GitHub。可使用
`dist/test-baselines-fixed-launcher-v0.1.2/` 下现有的两个固定启动器测试 ZIP；这些只用于
本地测试，不要上传到公开 Release。

1. 先只上传两边的 `0.1.3` ZIP，不上传清单；两个基线都应显示没有新版本或远端清单
   尚不存在，不能开始升级。
2. 上传 GitLink 清单。在 GitLink 基线点击“检查更新”，应发现 `0.1.3`；GitHub
   基线此时不应读取 GitLink 的更新。
3. 上传 GitHub 清单。GitHub 基线应发现同一个 `0.1.3`。
4. 两边分别执行升级，确认程序退出、助手替换文件、自动启动，设置页显示 `0.1.3`。
5. 切换下载源后再次检查更新，日志和网络请求应使用新平台。
6. 至少模拟一次新模块启动失败，确认活动版本回到 `0.1.2`，受管文件恢复，用户
   `data/`、缓存和下载源设置均未丢失。
