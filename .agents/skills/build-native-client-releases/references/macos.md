# macOS 原生构建流程

仅在目标平台包含 macOS 时读取。

## 环境定位

- 当前项目测试机是 Intel x64 macOS 虚拟机，具体地址、Python 环境和应用位置以 `docs/macos-virtual-machine-setup.md`、当前交接和实时探测为准，不把连接凭据写入技能。
- 构建必须在 macOS 内进行。先用 `uname -srm`、`python --version`、`python -m PyInstaller --version` 和 `uname -m` 确认 Darwin x86_64 与构建依赖。
- 使用已经验证过且满足项目 Python 版本要求的虚拟环境；系统自带的旧 Python 不能满足源码要求时，不要降级源码兼容它。

## 同步与预检

1. 从 Windows 生成不含凭据和旧产物的临时源码归档，确保它包含当前未提交改动以及完整 `app/versions/<目标版本>/`。
2. 传入来宾的独立临时构建目录，不直接覆盖 `~/Applications/SignRiver-DLC-Hub.app`，也不覆盖用户数据目录。
3. 解包后检查：

   ```bash
   test -f app/state.json
   test -f app/versions/<版本>/module.json
   test -f app/versions/<版本>/app_entry.py
   test -d app/versions/<版本>/signriver_app
   find app/versions/<版本>/signriver_app -type f | head
   ```

4. 运行与原生构建直接相关的测试；至少包含 `tests/test_build_native_release.py`，若改动涉及 macOS 更新、平台或补丁，再加入对应专项测试。

## 构建

在同步后的项目根目录使用已验证的 Python：

```bash
python tools/build_native_release.py --platform macos
```

预期主要产物：

```text
dist/SignRiver-DLC-Hub.app
dist/SignRiver-DLC-Hub-v<版本>-macos-x64.app.zip
dist/updates/SignRiver-DLC-Hub-full-v<版本>-macos-x64.zip
```

脚本会执行临时签名并拒绝在非 macOS 或非 x64 主机上构建；不要绕过平台检查。

## 验证与安装

- 用 `unzip -t` 检查两个 ZIP；用 `file` 或 `lipo -info` 确认 `.app/Contents/MacOS/SignRiver-DLC-Hub` 为 x86_64 Mach-O。
- 检查 `.app/Contents/Resources/runtime/app/versions/<版本>/` 含完整 `signriver_app/`。仅存在 `module.json` 时构建无效，即使 PyInstaller 命令成功退出也不能交付。
- 先直接启动 `dist/SignRiver-DLC-Hub.app` 做隔离验证。观察至少 8 秒，检查进程和 `~/Library/Logs/DiagnosticReports` 中是否出现新崩溃报告。
- 只有用户要求更新虚拟机桌面程序时，才停止现有应用、临时备份并替换 `~/Applications/SignRiver-DLC-Hub.app`；验证成功后删除临时备份，保持只留最新版。
- `.app` 内的打包状态和用户可写状态是两套数据。若界面版本与包内版本不一致，检查 `~/Library/Application Support/SignRiver DLC Hub/app/state.json` 是否因旧启动失败回退到旧版本并把目标版本加入 `bad_versions`。
- 计算并报告首次安装 ZIP 和全量更新 ZIP 的 SHA-256。

不要执行 Steam 登录、游戏下载、应用内容下载或线上发布，除非用户明确授权。
