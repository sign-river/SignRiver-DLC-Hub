# SteamOS 原生构建流程

仅在目标平台包含 SteamOS 时读取。

## 环境定位

- 当前项目测试机是 x86_64 SteamOS 虚拟机，具体地址、挂载点、Python 环境和虚拟机状态以 `docs/steamos-virtual-machine-setup.md`、当前交接和实时探测为准，不把连接凭据写入技能。
- 构建必须在 SteamOS 内进行。先用 `uname -srm`、`python --version` 和 `python -m PyInstaller --version` 确认 Linux x86-64 与构建依赖。
- 优先使用已经验证过的项目虚拟环境；路径变化时通过来宾文件系统探测，不凭历史记录猜测。

## 同步与预检

1. 从 Windows 生成不含凭据和旧产物的临时源码归档，确保它包含当前未提交改动以及完整 `app/versions/<目标版本>/`。
2. 传入来宾的独立临时构建目录，不覆盖桌面测试源码、现有发布产物或用户数据。
3. 解包后检查：

   ```bash
   test -f app/state.json
   test -f app/versions/<版本>/module.json
   test -f app/versions/<版本>/app_entry.py
   test -d app/versions/<版本>/signriver_app
   find app/versions/<版本>/signriver_app -type f | head
   ```

4. 运行与原生构建直接相关的测试；至少包含 `tests/test_build_native_release.py`，若改动涉及平台、补丁或更新，再加入相应专项测试。

## 构建

在同步后的项目根目录使用已验证的 Python：

```bash
python tools/build_native_release.py --platform steamos
```

预期主要产物：

```text
dist/SignRiver-DLC-Hub-v<版本>-steamos-x64.tar.gz
dist/updates/SignRiver-DLC-Hub-full-v<版本>-steamos-x64.zip
```

脚本会拒绝在非 SteamOS 主机或非 x64 主机上构建；不要绕过此检查。

## 验证

- 用 `tar -tzf` 检查首次安装包，用 `unzip -t` 检查全量更新包。
- 解包后使用 `file` 确认 `SignRiver-DLC-Hub` 为 x86-64 ELF，并确认具有执行权限。
- 检查包内目标版本的 `module.json`、`app_entry.py` 与 `signriver_app/`。
- 在隔离的数据与缓存目录中启动程序，观察至少 8 秒后正常停止；桌面 GUI 验收需要来宾图形会话时，使用现有 KDE 测试入口。
- 计算并报告两个发布包的 SHA-256。

不要因构建成功而改动线上发布源；上传与清单更新必须另获用户授权。
