# 模块化更新架构

## 目标

`SignRiver-DLC-Hub.exe` 被设计成稳定宿主，只包含以下职责：

1. 读取当前应用模块版本；
2. 提供稳定的 Host API；
3. 获取更新清单并下载包；
4. 校验包的 SHA-256 和大小；
5. 安全解压、原子切换与失败回滚；
6. 加载外部应用模块并启动界面。

游戏支持、界面和绝大多数业务逻辑都放在外部应用模块中。因此常规更新不需要替换正在运行的 EXE。

## 发布目录

```text
SignRiver-DLC-Hub/
├── SignRiver-DLC-Hub.exe       # 稳定启动器
├── app/
│   ├── state.json              # 当前、上一和待确认版本
│   ├── .staging/               # 更新暂存目录
│   └── versions/
│       ├── 0.1.0/
│       │   ├── module.json
│       │   ├── app_entry.py
│       │   └── ...
│       └── 0.1.1/
├── config/update.json          # 清单地址、通道和超时
├── cache/                      # 下载缓存，可删除
└── data/                       # 用户设置、日志和长期数据
```

`data/` 不属于任何模块更新包，更新和回滚都不会覆盖用户数据。

## 模块接口

每个模块根目录必须包含 `module.json`：

```json
{
  "schema_version": 1,
  "name": "SignRiver DLC Hub",
  "version": "0.1.1",
  "api_version": 1,
  "entrypoint": "app_entry.py:create_application"
}
```

入口函数接收一个 `HostContext`，并返回拥有 `run()` 方法的对象：

```python
def create_application(context):
    return Application(context)
```

模块可通过 context 使用稳定能力：

- `context.paths.data`：持久用户数据；
- `context.paths.cache`：可清理缓存；
- `context.updates.check()`：检查更新；
- `context.updates.install(...)`：下载并安装；
- `context.restart()`：由宿主安全重启；
- `context.logger`：统一日志。

模块内部文件请使用相对导入（例如 `from .services import updater`）。宿主会为每个版本建立独立的包命名空间，避免新版本初始化失败后污染旧版本的导入缓存。

只有提升 Host API 版本或修改宿主本身时，才需要重新发布 EXE。

## 更新清单

服务端提供 UTF-8 JSON：

```json
{
  "schema_version": 1,
  "channel": "stable",
  "releases": [
    {
      "version": "0.1.1",
      "kind": "module",
      "min_launcher_version": "0.1.0",
      "package_url": "https://host/path/module-v0.1.1.zip",
      "sha256": "64位十六进制摘要",
      "size": 123456,
      "mandatory": false,
      "notes": "本次更新说明"
    }
  ]
}
```

`kind` 有两种：

- `module`：普通更新，启动器自动安装；
- `full`：涉及启动器或运行时的大更新，引导用户下载完整压缩包。

`package_url` 可以是 HTTPS 绝对地址，也可以是相对于清单地址的相对地址。默认拒绝普通 HTTP。

## 安装事务

1. 将更新包下载为 `cache/*.part`；
2. 校验文件大小和 SHA-256；
3. 检查 ZIP 文件数量、展开大小、符号链接和路径穿越；
4. 解压到 `app/.staging/<version>-<random>/`；
5. 校验 `module.json`、Host API 和入口文件；
6. 将暂存目录原子重命名为 `app/versions/<version>/`；
7. 原子更新 `app/state.json`，记录 `active_version`、`previous_version` 和 `pending_version`；
8. 重启后初始化新模块；成功则清除 `pending_version`，失败则切回 `previous_version`。

旧版本不会在更新过程中删除。以后可以增加保留最近两个健康版本的清理策略。

## 发布模块更新

1. 将新代码复制为 `app/versions/新版本/`；
2. 修改该目录中的 `module.json` 版本；
3. 执行：

   ```bash
   python tools/build_module.py app/versions/新版本
   ```

4. 上传 `dist/modules/SignRiver-DLC-Hub-module-v新版本.zip`；
5. 将生成的 `.release.json` 内容加入线上清单；
6. 把 `config/update.json` 的 `manifest_url` 指向线上清单。

## 安全边界

当前实现强制 HTTPS 并验证清单指定的 SHA-256，可防止传输损坏和包被意外替换。SHA-256 本身不能防止“清单与更新包同时被篡改”。正式大规模发布前，应在 Host API 2 中加入离线保存于启动器内的 Ed25519 公钥，并要求清单签名。
