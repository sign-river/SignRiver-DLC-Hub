# 程序更新发布指南

## 当前发布基线

- 当前正式版本：`0.1.7`
- 当前更新类型：`full`
- 最低可自动全量更新的启动器版本：`0.1.2`
- 模块维护基线：`0.1.5`、`0.1.6`、`0.1.7`

后续发布必须使用高于线上版本的新版本号。业务模块的唯一受控源码是 `app/versions/0.1.0/`；修改完成后复制到新的目标版本目录，不能直接把旧的已发布版本目录作为新源码继续修改。

## 发布前同步

假设新版本号为 `<版本>`：

1. 修改 `app/versions/0.1.0/` 中的客户端代码。
2. 将受控模块源码同步到 `app/versions/<版本>/`，并更新该目录的 `module.json`。
3. 更新 `src/signriver_launcher/constants.py` 的 `LAUNCHER_VERSION`。
4. 更新 `app/state.json` 的 `active_version`，清空 `bad_versions`。
5. 在 `publisher-workspace/update-notes.json` 中写入面向普通用户的中文说明，结尾使用“建议尽快更新。”。
6. 确认更新说明不会泄露内部路径、令牌或测试信息。

## 构建与准备

`build_release.py` 会自动从 PATH 查找 UPX，也可以用 `--upx-dir` 显式指定。未找到 UPX 时启动器不会压缩，构建会给出警告。

```powershell
.\.venv\Scripts\python.exe tools\build_module.py --all-versions app\versions
.\.venv\Scripts\python.exe tools\build_release.py `
  --upx-dir C:\Users\32173\AppData\Local\tools\upx\upx-5.0.2-win64
```

`build_module.py --all-versions` 会构建所有本地版本，再清理 `dist/modules` 中不应发布的 `0.1.0` 产物。构建后将 `config/module-archives.json` 更新为最近三个发布版本的文件名、大小和 SHA-256。

生成全量更新的双源清单时，PowerShell 直接传中文参数可能乱码，建议通过 Python `subprocess` 调用：

```python
import subprocess

version = "<版本>"
notes = "<与 update-notes.json 完全一致的中文更新说明>"
subprocess.run(
    [
        r".venv\Scripts\python.exe",
        r"tools\prepare_update_release.py",
        rf"dist\updates\SignRiver-DLC-Hub-full-v{version}-windows-x64.zip",
        "--version", version,
        "--kind", "full",
        "--min-launcher-version", "0.1.2",
        "--notes", notes,
        "--mandatory",
    ],
    check=True,
)
```

## `updates` Release

两个平台均使用 `updates` 标签：

- GitLink：`signriver/signriver-dlc-assets`
- GitHub：`sign-river/signriver-dlc-assets`

每个平台上传：

1. `dist/updates/SignRiver-DLC-Hub-full-v<版本>-windows-x64.zip`
2. 对应平台目录中的 `update-manifest.json`

发布顺序必须是：

1. GitLink 上传更新 ZIP。
2. GitHub 上传更新 ZIP。
3. 确认两个 ZIP 均可下载，且大小和 SHA-256 正确。
4. 上传 GitLink 清单。
5. 上传 GitHub 清单。

发布器的“双源镜像发布程序更新”已按这个安全顺序执行。清单必须最后上传，否则客户端可能在 ZIP 尚不可用时发现新版本。

以下文件不能放入 `updates` Release：

- 带外层安装目录的首次安装 ZIP。
- 首次安装自解压 EXE。
- 另一个平台的清单；GitLink 与 GitHub 的 `package_url` 不同。

## `modules` Release

模块归档发布到独立的 `modules` 标签，不修改程序更新清单，也不会触发客户端更新。

发布器会读取 ZIP 根目录的 `module.json` 自动识别版本。“发布模块归档”和“双源镜像归档”会校验并上传 `dist/modules/SignRiver-DLC-Hub-module-v*.zip`。

必须保证：

- `config/module-archives.json` 只维护最近三个发布版本。
- 配置中的大小与 SHA-256 和本地归档一致。
- 两个平台的同版本模块归档内容一致。
- 远端归档验证和 CI 恢复测试完成前，不清理本地目标版本目录。

## 保留与删除

必须保留：

- 当前唯一的 `update-manifest.json`。
- 当前清单引用的全量更新 ZIP。
- 最近一个已验证版本的全量更新 ZIP，供回滚演练使用。
- 最近三个模块归档。
- 回滚测试结束前的 `.update-backup/<transaction-id>`。

可以替换：

- `update-manifest.json`，但只能在新 ZIP 已上传并完成校验后替换。
- 尚未公开的同版本测试 ZIP；替换 ZIP 后必须重新生成清单。

不得删除或覆盖：

- 当前清单仍引用的更新包。
- 用户安装目录中的 `data/`、`cache/`、`app/state.json` 和用户更新源配置。
- 回滚测试仍需使用的旧模块和事务备份。

不得提交或上传：

- `publisher-workspace/`
- `config/publisher.local.json`
- `dist/publisher/publisher.local.json`
- 本地更新测试基线
- GitLink/GitHub 令牌或其他私有凭据

## 发布验收

至少准备两个独立的旧版本安装目录，分别选择 GitLink 和 GitHub：

1. 只上传两个平台的 ZIP、不上传新清单时，旧客户端不能发现新版本。
2. 分别上传清单后，两边应发现相同版本，但从各自平台下载。
3. 验证程序退出、更新助手替换文件、自动重启和版本显示。
4. 验证下载源设置、`data/`、缓存和安装回执没有丢失。
5. 模拟新模块启动失败，确认可以回退到任一可用旧版本。
6. 模拟没有可用模块的情况，确认显示明确的修复提示。
7. 重新计算更新 ZIP 和模块归档哈希，并与本地配置、双源清单核对。
8. 运行 `pytest`、Ruff、`git diff --check` 和必要的冻结版 Windows E2E。

发布包上传完成后再提交源码。默认由用户手工推送；只有用户明确要求“推送”或“提交并推送”时，AI 才能执行 `git push`。
