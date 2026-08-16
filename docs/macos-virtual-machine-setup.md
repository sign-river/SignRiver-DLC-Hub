# macOS Sequoia（Darwin 24）VMware 虚拟机复现手册

> 最后核对：2026-08-16
> 当前状态：macOS Sequoia 已完成安装，首次设置界面已从俄语改为简体中文；本地账户已创建并进入桌面，尚未安装 VMware Tools、开发工具链、Steam 或 SignRiver。

## 1. 文档目的与适用范围

本文不是按当时的试错时间线复述，而是把已经验证成功的路线整理成一条可从零执行的主线。未来重建时，应优先按第 2～13 节顺序操作；VirtualBox + OpenCore、完整 `InstallAssistant.pkg` 提取、错误网卡和错误 Recovery 进入方式等失败尝试统一收录在第 16 节，避免再次绕路。

当前虚拟机文件历史名称为：

```text
D:\Downloads\SignRiver-Test-OS\vmware\macOS Tahoe.vmx
```

虽然文件名和 `displayName` 仍写着 `macOS Tahoe`，实际恢复镜像、安装器和已安装系统均为 **macOS Sequoia（Darwin 24）**。为避免破坏脚本和快照引用，当前不重命名。

本文所说“虚拟机可运行”仅表示系统已安装、完成首次设置并能进入桌面，不代表 VMware Tools、SSH、Python、Rust、Steam、游戏和 SignRiver 的 macOS 端验收已经完成。

> **许可与支持风险：** 在非 Apple 硬件上运行 macOS，以及使用第三方工具修改 Windows 版 VMware 的 macOS 来宾支持，可能不受 Apple 或 VMware 官方支持，也可能受软件许可条款限制。复现前请自行确认授权、合规性和风险。

## 2. 已验证成功路线总览

主线只保留以下步骤：

1. 在 Windows 上安装 VMware Workstation 17.6.4；
2. 如 VMware 无法创建 macOS 来宾，备份 VMware 后应用 Unlocker 4.2.8；
3. 下载 OpenCorePkg 1.0.7，但**只使用其中的 `macrecovery.py`**；
4. 让 `macrecovery.py` 向 Apple Recovery 服务动态取得 `BaseSystem.dmg` 和 `BaseSystem.chunklist`；
5. 用 `dmg2img` 把 DMG 转为 raw IMG，再用 VirtualBox 的 `VBoxManage.exe` 转为 VMDK；
6. 用 `VBoxManage.exe` 创建约 100 GiB 的目标 VMDK；
7. 创建 VMware VM，并从一开始就使用正确的 EFI、PCIe、xHCI、虚拟 USB 键鼠、NAT 和 `vmxnet3` 配置；
8. 从 BaseSystem 进入 Recovery，把目标盘抹成 GUID + APFS；
9. 临时让宿主代理直连 Apple CDN，在线安装 Sequoia；
10. 如果首次设置是俄语，重新从 BaseSystem Recovery 启动，离线修改系统级语言 plist；
11. 恢复正常磁盘连接，验证中文界面并创建快照。

**不推荐的分支：**

- 不再用 VirtualBox 直接运行 macOS；VirtualBox 只保留 `VBoxManage.exe` 作为磁盘转换工具；
- 不再构造 OpenCore 启动 VM；OpenCorePkg 只提供 `macrecovery.py`；
- 不再优先下载 18 GB 的完整 `InstallAssistant.pkg`；当前成功主线只需要 BaseSystem Recovery 在线安装；
- 不使用 `e1000e`、`e1000` 或桥接网络；直接使用 NAT + `vmxnet3`；
- 不使用 `nvram recovery-boot-mode=unused` 或 `macosguest.forceRecoveryModeInstall` 强制 Recovery。

## 3. 当前已验证状态

| 项目 | 当前值 |
| --- | --- |
| 虚拟化软件 | VMware Workstation 17.6.4 |
| VM 文件 | `D:\Downloads\SignRiver-Test-OS\vmware\macOS Tahoe.vmx` |
| 实际系统 | macOS Sequoia，Darwin 24 |
| 虚拟硬件版本 | 21 |
| 来宾标识 | `darwin24-64` |
| 固件 | EFI |
| CPU | 4 vCPU，2 cores/socket |
| 内存 | 8192 MB |
| 显存 | 256 MiB |
| 3D 加速 | 关闭 |
| 网络 | NAT + `vmxnet3` |
| 键鼠 | VMware 虚拟 USB 键盘、虚拟 USB 鼠标、xHCI |
| VNC | 仅监听 `127.0.0.1:5901`，当前无认证 |
| 安装目标盘 | 102400 MiB；macOS 显示约 107.16 GB；GUID + APFS |
| 当前界面 | 简体中文 macOS 桌面，首次设置已完成 |
| 当前推荐快照 | `pre-account-setup-zh` |

当前 VMX 已连接四层快照链中的差分盘：

```ini
sata0:0.fileName = "BaseSystem-000004.vmdk"
sata0:1.fileName = "macos-disk-000004.vmdk"
```

快照编号会继续变化。**不得**因为正文中的示例写着基础盘或 `-000003.vmdk`，就手工把当前 VMX 改回那些名字；始终以当前 VMX 中实际引用的盘为准。

## 4. 下载资源、实际链接与校验值

### 4.1 主线必需资源

| 资源 | 本次版本与用途 | 下载入口 | 本次文件校验 |
| --- | --- | --- | --- |
| VMware Workstation | 17.6.4，实际运行平台 | [VMware/Broadcom 官方产品页](https://www.vmware.com/products/desktop-hypervisor/workstation-and-fusion)；本次实际使用的[第三方 GitHub 镜像](https://github.com/201853910/VMwareWorkstation/releases/download/17.0/VMware-workstation-full-17.6.4-24832109.exe) | `425426160` bytes；SHA256 `10fe3a36f525d88aa133118ab3b5a16b18da88d4aa11b14d74e4164b3fb94ba9` |
| Unlocker | 4.2.8，使 VMware 能识别 macOS 来宾 | [Release 页面](https://github.com/DrDonk/unlocker/releases/tag/v4.2.8)；[unlocker428.zip](https://github.com/DrDonk/unlocker/releases/download/v4.2.8/unlocker428.zip) | `24748614` bytes；SHA256 `7ec212696981a95f7bbf9b04b7d33e644a8a808c88a39db897b16487be456af4` |
| OpenCorePkg | 1.0.7，只使用 `Utilities\macrecovery\macrecovery.py` | [Release 页面](https://github.com/acidanthera/OpenCorePkg/releases/tag/1.0.7)；[OpenCore-1.0.7-RELEASE.zip](https://github.com/acidanthera/OpenCorePkg/releases/download/1.0.7/OpenCore-1.0.7-RELEASE.zip) | `10437696` bytes；SHA256 `2ffab6ebf58c7aefb0bcb3a1a385d207746823d6dd87d44bd666e1286939943e` |
| dmg2img | 1.6.7，把 BaseSystem DMG 转为 raw IMG | [项目工具页](http://vu1tur.eu.org/tools/)；本次使用的[dmg2img-1.6.7-win32.zip](http://vu1tur.eu.org/tools/dmg2img-1.6.7-win32.zip) | `64462` bytes；SHA256 `c33595575b08d04ab3cd1d7bc0339fc7ffa473d5969ce29a2a206d08dc4f42a4` |
| VirtualBox | 7.2.14，只使用 `VBoxManage.exe` 转盘和建盘 | [Windows 安装包](https://download.virtualbox.org/virtualbox/7.2.14/VirtualBox-7.2.14-174565-Win.exe)；[官方 SHA256SUMS](https://download.virtualbox.org/virtualbox/7.2.14/SHA256SUMS) | `178059368` bytes；SHA256 `5fb111f32a15763d519bf9ef23e0111153521f641cde7460e5b8e895ca27a1d2` |
| Python | Windows Python 3，用于运行 `macrecovery.py` | [Python 官方 Windows 下载页](https://www.python.org/downloads/windows/) | 以当时官方安装包为准；安装后执行 `python --version` |
| 7-Zip | 26.02，解压工具包 | [7z2602-x64.exe](https://www.7-zip.org/a/7z2602-x64.exe)；[7z2602-extra.7z](https://www.7-zip.org/a/7z2602-extra.7z) | EXE：`1657896` bytes，SHA256 `6745fa76dc2ea031596d8678f6f6b99c3c1b435b4164a63485adbbc7b8d82ef0`；extra：`1758916` bytes，SHA256 `081df9e9311dfd9c9e0e98c1c80180b99bb51e4cb24156b5f3057fe3c259d70a` |

VMware 的版本固定下载在官方门户中可能需要登录或重新定位，因此表中同时记录了本次真正下载成功的第三方镜像。使用非官方镜像时，必须核对上表 SHA256；不匹配就不要运行。

`dmg2img` 官方站点是 HTTP，且 2026-08-16 复查时连接不稳定。若链接失效，应优先使用本机已保留且哈希匹配的归档，不要从不明站点随意下载同名 EXE。

### 4.2 Apple Recovery：推荐动态下载，固定 URL 只用于还原本次记录

本次通过 `macrecovery.py` 最终取得：

| 文件 | 大小 | SHA256 |
| --- | ---: | --- |
| `BaseSystem.dmg` | `884317790` bytes | `7314eb401f5e84087f621b3599f0ad21ca3cdcc2685ea2da7f76806792328e20` |
| `BaseSystem.chunklist` | `3352` bytes | `dbf262b83a16d55f1b2d8ce8ce95986561f8e889719524ea4b7aa22a2417ca27` |

本次下载日志记录的 Apple CDN 地址：

- [BaseSystem.dmg](http://oscdn.apple.com/content/downloads/04/11/082-33203/orvwro1v8xhjrakr7tvl5hu1s1ew3epxne/RecoveryImage/BaseSystem.dmg)
- [BaseSystem.chunklist](http://oscdn.apple.com/content/downloads/04/11/082-33203/orvwro1v8xhjrakr7tvl5hu1s1ew3epxne/RecoveryImage/BaseSystem.chunklist)

这些固定 CDN 地址可能在未来失效、拒绝 HEAD 请求或被 Apple 替换。正常复现时不要硬编码它们，应执行第 6 节的 `macrecovery.py`，让脚本重新向 Apple 服务请求当前有效地址。若未来脚本返回了不同版本，应根据文件大小、系统版本和项目需求决定是否继续，不要把不同版本误当成本文的 Sequoia 镜像。

日志中的 `AP`、`AH`、`CH` 是 Apple Recovery 服务返回的产品/校验字段，**不能**直接当作普通文件 SHA256。普通 SHA256 以上表为准。

### 4.3 历史路线下载资源

这些文件当时确实下载过，但不属于推荐主线：

| 资源 | 下载入口 | 本次校验/说明 |
| --- | --- | --- |
| gibMacOS | [项目主页](https://github.com/corpnewt/gibMacOS)；[master.zip](https://github.com/corpnewt/gibMacOS/archive/refs/heads/master.zip) | 本次 ZIP `537187` bytes，SHA256 `7f1d202d360805bb3f12ed2100062b9fa40e09e94fab273cd3cb31ef68f659cf`；`master.zip` 会变化，此哈希只对应 2026-08-08 下载 |
| 完整 `InstallAssistant.pkg` | [本次 Apple CDN 地址](https://swcdn.apple.com/content/downloads/10/29/140-77964-A_0UTOTNYQBE/i3xi6sdu6ix3hinx00nytw4u0tky6oyswt/InstallAssistant.pkg) | `18368573458` bytes；本机 SHA256 `5737685d3dc6598dc16b4ebf5269d0bfdbde5cc230e3baad46dd5237b23589a4`；未进入最终稳定启动路径 |
| aria2 | [Release 页面](https://github.com/aria2/aria2/releases/tag/release-1.37.0)；[Windows ZIP](https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip) | `2475379` bytes；SHA256 `67d015301eef0b612191212d564c5bb0a14b5b9c4796b76454276a4d28d9b288`；仅用于历史大文件下载 |

Apple 的完整安装器产品 URL 也会变化。若确实要重走完整安装器路线，应让 `gibMacOS` 重新读取 Apple 软件目录，不要默认旧 URL 永久有效。

### 4.4 在 Windows 上核对下载文件

```powershell
Get-FileHash 'D:\path\to\downloaded-file' -Algorithm SHA256
(Get-Item 'D:\path\to\downloaded-file').Length
```

ZIP 文件还应检查文件头，防止把下载错误页当成压缩包：

```powershell
Format-Hex 'D:\path\to\archive.zip' -Count 4
```

正常 ZIP 通常以 `PK` 开头。本次曾有两个名为 `dmg2img.zip` 的 16700-byte 文件实际是 HTML 页面，不是压缩包。

## 5. 准备目录、安装 VMware 与 Unlocker

### 5.1 建立工作目录

```powershell
$base = 'D:\Downloads\SignRiver-Test-OS'
foreach ($d in @('macos','macos\recovery','vmware','tools')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $base $d) | Out-Null
}
```

后文沿用本次实际路径。换目录也可以，但 VMX、转换命令和快照父盘路径必须同步修改。

### 5.2 安装 VMware Workstation 17.6.4

1. 优先从第 4.1 节的 VMware/Broadcom 官方入口下载；若只能使用本次第三方镜像，先核对 SHA256；
2. 正常安装 VMware Workstation；
3. 首次启动确认程序能运行，然后完全退出 VMware；
4. 在任务管理器或 PowerShell 中确认 `vmware.exe`、`vmware-vmx.exe` 等相关进程已退出。

```powershell
Get-Process vmware,vmware-vmx -ErrorAction SilentlyContinue
```

### 5.3 仅在需要时应用 Unlocker 4.2.8

如果 VMware 已能创建并运行 `darwin24-64` 来宾，可跳过此步。否则：

1. 下载并核对 `unlocker428.zip`；
2. 备份 VMware 安装目录和现有虚拟机；
3. 解压 ZIP；
4. 完全退出 VMware；
5. 以管理员身份运行解压目录 `windows\unlock.exe`；
6. 可用同目录 `check.exe` 检查补丁状态；需要撤销时运行 `relock.exe`。

VMware 升级或修复安装可能覆盖补丁，升级后需要重新检查。不要从不明来源获取或直接以管理员身份运行修改版 Unlocker。

## 6. 下载 Apple BaseSystem Recovery

### 6.1 下载并解压 OpenCorePkg 1.0.7

从第 4.1 节链接下载 `OpenCore-1.0.7-RELEASE.zip`，核对哈希后解压到：

```text
D:\Downloads\SignRiver-Test-OS\tools\OpenCore-1.0.7
```

本路线不使用 OpenCore 引导器、Kext 或 `config.plist`，只调用：

```text
D:\Downloads\SignRiver-Test-OS\tools\OpenCore-1.0.7\Utilities\macrecovery\macrecovery.py
```

### 6.2 动态下载 Recovery

确认 Windows Python 可用：

```powershell
python --version
```

执行本次成功使用的命令：

```powershell
$mr = 'D:\Downloads\SignRiver-Test-OS\tools\OpenCore-1.0.7\Utilities\macrecovery\macrecovery.py'
$out = 'D:\Downloads\SignRiver-Test-OS\macos\recovery'

New-Item -ItemType Directory -Force -Path $out | Out-Null
python $mr download -o $out -v
```

也可以把日志保存下来：

```powershell
python $mr download -o $out -v 2>&1 |
  Tee-Object 'D:\Downloads\SignRiver-Test-OS\macos\recovery-download.log'
```

完成后至少应得到：

```text
D:\Downloads\SignRiver-Test-OS\macos\recovery\BaseSystem.dmg
D:\Downloads\SignRiver-Test-OS\macos\recovery\BaseSystem.chunklist
```

核对本次 Sequoia 文件：

```powershell
Get-Item "$out\BaseSystem.dmg", "$out\BaseSystem.chunklist" |
  Select-Object Name,Length

Get-FileHash "$out\BaseSystem.dmg", "$out\BaseSystem.chunklist" -Algorithm SHA256
```

预期值见第 4.2 节。如果未来 Apple 返回不同的文件，先确认版本再继续。不要因为文件名仍叫 `BaseSystem.dmg` 就默认内容完全相同。

## 7. 把 Recovery 转为 VMware 磁盘并创建目标盘

### 7.1 安装 VirtualBox 和解压 dmg2img

安装 VirtualBox 7.2.14 后确认：

```text
C:\Program Files\Oracle\VirtualBox\VBoxManage.exe
```

存在。VirtualBox 不用于运行这台 macOS VM，仅使用其磁盘工具。

将 `dmg2img-1.6.7-win32.zip` 解压，确认实际 EXE 路径。本次使用：

```text
D:\Downloads\SignRiver-Test-OS\tools\dmg2img\extracted\dmg2img.exe
```

### 7.2 BaseSystem.dmg → BaseSystem.img → BaseSystem.vmdk

```powershell
$dmg2img = 'D:\Downloads\SignRiver-Test-OS\tools\dmg2img\extracted\dmg2img.exe'
$recovery = 'D:\Downloads\SignRiver-Test-OS\macos\recovery'
$VBoxManage = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'

& $dmg2img `
  "$recovery\BaseSystem.dmg" `
  "$recovery\BaseSystem.img"

if ($LASTEXITCODE -ne 0) { throw 'dmg2img 转换失败' }

& $VBoxManage convertfromraw `
  "$recovery\BaseSystem.img" `
  "$recovery\BaseSystem.vmdk" `
  --format VMDK

if ($LASTEXITCODE -ne 0) { throw 'VBoxManage convertfromraw 失败' }
```

本次保留结果：

```text
BaseSystem.dmg   884317790 bytes
BaseSystem.vmdk  2442330112 bytes
```

`BaseSystem.img` 是可再生成的中间文件；只有在 `BaseSystem.vmdk` 已验证可启动、且没有 VM 或快照引用 IMG 时才可删除。

### 7.3 创建约 100 GiB 的安装目标盘

本次先创建动态 VDI，再克隆成 VMDK：

```powershell
$VBoxManage = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
$mac = 'D:\Downloads\SignRiver-Test-OS\macos'

& $VBoxManage createmedium disk `
  --filename "$mac\macos-disk.vdi" `
  --size 102400 `
  --format VDI

if ($LASTEXITCODE -ne 0) { throw '创建目标 VDI 失败' }

& $VBoxManage clonemedium disk `
  "$mac\macos-disk.vdi" `
  "$mac\macos-disk.vmdk" `
  --format VMDK

if ($LASTEXITCODE -ne 0) { throw '目标盘转 VMDK 失败' }
```

`102400 MiB` 在 macOS 磁盘工具中显示为约 `107.16 GB`，这是二进制 MiB/GiB 与十进制 MB/GB 的显示差异，不是容量异常。

最终主线需要：

```text
D:\Downloads\SignRiver-Test-OS\macos\recovery\BaseSystem.vmdk
D:\Downloads\SignRiver-Test-OS\macos\macos-disk.vmdk
```

## 8. 创建 VMware 虚拟机并写入最终正确配置

### 8.1 创建空虚拟机

在 VMware Workstation 中：

1. 新建自定义虚拟机；
2. 选择“稍后安装操作系统”；
3. 若列表中有 macOS，选择对应的 64 位 macOS；若没有，先处理第 5.3 节 Unlocker；
4. 虚拟硬件兼容性使用 Workstation 17.x 对应版本；
5. CPU 设为 4 vCPU、每插槽 2 核；
6. 内存设为 8192 MB；
7. 固件使用 EFI；
8. 暂时不创建新的安装盘，或创建后移除；
9. 完成向导后**不要启动 VM**，完全退出 VMware。

VM 目录本次为：

```text
D:\Downloads\SignRiver-Test-OS\vmware
```

### 8.2 编辑 VMX 前的安全检查

```powershell
$vmrun = 'C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe'
$vmx = 'D:\Downloads\SignRiver-Test-OS\vmware\macOS Tahoe.vmx'

& $vmrun list
Get-Process vmware-vmx -ErrorAction SilentlyContinue
Copy-Item $vmx "$vmx.before-initial-config"
```

只有 `vmrun list` 不包含该 VM、对应 `vmware-vmx.exe` 已退出时，才可编辑 VMX。

### 8.3 写入从一开始就正确的 VMX 主干

不要先使用 `e1000e` 再排障。初始配置就应使用 NAT + `vmxnet3`，并一次性写入无冲突的 PCIe/xHCI 槽位。

以下片段中的两块 VMDK 是**首次建机时的基础盘**。如果 VM 已经创建快照，必须保留 VMX 当前的差分盘文件名，不能照抄回基础盘。

```ini
.encoding = "UTF-8"
config.version = "8"
virtualHW.version = "21"
displayName = "macOS Tahoe"
guestOS = "darwin24-64"
firmware = "efi"

numvcpus = "4"
cpuid.coresPerSocket = "2"
memsize = "8192"

smc.present = "TRUE"
smc.version = "0"
board-id.reflectHost = "TRUE"
hw.model.reflectHost = "TRUE"
serialNumber.reflectHost = "TRUE"
smbios.reflectHost = "TRUE"

sata0.present = "TRUE"
sata0.pciSlotNumber = "36"
sata0:0.deviceType = "disk"
sata0:0.fileName = "D:/Downloads/SignRiver-Test-OS/macos/recovery/BaseSystem.vmdk"
sata0:0.present = "TRUE"
sata0:0.redo = ""
sata0:1.deviceType = "disk"
sata0:1.fileName = "D:/Downloads/SignRiver-Test-OS/macos/macos-disk.vmdk"
sata0:1.present = "TRUE"
sata0:1.redo = ""

ethernet0.present = "TRUE"
ethernet0.connectionType = "nat"
ethernet0.virtualDev = "vmxnet3"
ethernet0.addressType = "generated"
ethernet0.pciSlotNumber = "160"

pciBridge0.present = "TRUE"
pciBridge0.pciSlotNumber = "17"
pciBridge4.present = "TRUE"
pciBridge5.present = "TRUE"
pciBridge6.present = "TRUE"
pciBridge7.present = "TRUE"
pciBridge4.virtualDev = "pcieRootPort"
pciBridge4.functions = "8"
pciBridge5.virtualDev = "pcieRootPort"
pciBridge5.functions = "8"
pciBridge6.virtualDev = "pcieRootPort"
pciBridge6.functions = "8"
pciBridge7.virtualDev = "pcieRootPort"
pciBridge7.functions = "8"
pciBridge4.pciSlotNumber = "21"
pciBridge5.pciSlotNumber = "22"
pciBridge6.pciSlotNumber = "23"
pciBridge7.pciSlotNumber = "24"

usb.present = "TRUE"
usb.pciSlotNumber = "34"
usb_xhci.present = "TRUE"
usb_xhci.pciSlotNumber = "192"
keyboard.vusb.present = "TRUE"
keyboard.vusb.enable = "TRUE"
mouse.vusb.present = "TRUE"
mouse.vusb.enable = "TRUE"
mouse.vusb.useBasicMouse = "FALSE"
mouse.present = "FALSE"
vmmouse.present = "TRUE"
usb.generic.allowHID = "TRUE"

svga.vramSize = "268435456"
mks.enable3d = "FALSE"
```

`256 MiB = 268435456 bytes`。当前关闭 3D 是为了稳定性；本文目标是系统和项目功能验证，不是图形性能测试。

编辑时应替换同名旧键，而不是在文件末尾不断追加重复键。保存后可检查关键项：

```powershell
Select-String -Path $vmx -Pattern `
  '^(guestOS|firmware|sata0|ethernet0|pciBridge[4-7]|usb|usb_xhci|keyboard|mouse|vmmouse|mks)'
```

## 9. 启用仅限本机的 VNC 控制（推荐但可选）

Windows `SendInput` 和 VMware 控制台自动输入无法稳定进入 macOS Recovery。本次最终在 VMX 中加入：

```ini
RemoteDisplay.vnc.enabled = "TRUE"
RemoteDisplay.vnc.ip = "127.0.0.1"
RemoteDisplay.vnc.port = "5901"
```

项目内使用过的控制脚本：

```text
D:\project\SignRiver-DLC-Hub\.test-artifacts\vmware_vnc.py
```

常用命令：

```powershell
python .test-artifacts\vmware_vnc.py info
python .test-artifacts\vmware_vnc.py screenshot .test-artifacts\macos.png
python .test-artifacts\vmware_vnc.py click 500 400
python .test-artifacts\vmware_vnc.py type "example"
```

安全要求：

- 当前 VNC 没有认证，只能绑定 `127.0.0.1`；
- 不得改成 `0.0.0.0`，不得暴露到局域网或公网；
- 不要通过自动化脚本输入、保存或记录账户密码；
- 首次设置和自动化结束后，如果不再需要，应关闭 VNC。

## 10. 首次启动 Recovery 并初始化目标盘

### 10.1 启动与关机命令

```powershell
$vmrun = 'C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe'
$vmx = 'D:\Downloads\SignRiver-Test-OS\vmware\macOS Tahoe.vmx'

# GUI 启动
& $vmrun start $vmx gui

# 请求来宾正常关机
& $vmrun stop $vmx soft
```

首次启动应从 `sata0:0` 的 BaseSystem 进入 macOS Recovery。先验证：

- Recovery 界面能显示；
- 鼠标能离开左上角并正常点击；
- 键盘能输入；
- “磁盘工具”能看到约 107.16 GB 的独立目标盘；
- 网络工具能看到 `vmxnet3` 对应接口。

如果此时 VMware 自身崩溃、xHCI 报无槽位或键鼠不可用，不要继续安装，先按第 16.3 节检查 PCIe 槽位和键名。

### 10.2 抹掉目标盘

进入 Recovery 的“磁盘工具”后：

1. 选择“显示所有设备”；
2. 找到约 107.16 GB 的独立目标虚拟磁盘；
3. 选择该磁盘的最上层物理设备，而不是其子卷；
4. 点击“抹掉”；
5. 分区图选择 `GUID Partition Map`；
6. 格式选择 `APFS`；
7. 名称可使用 `Macintosh HD`；
8. 等待抹盘完成并退出磁盘工具。

不要抹掉 `BaseSystem`、Recovery 盘或名称相近的安装介质。

目标盘初始化完成后创建安装前快照：

```powershell
& $vmrun snapshot $vmx 'pre-tahoe-apfs-install'
```

快照名保留早期 `Tahoe` 命名，但内容实际是 Sequoia 安装前状态。

## 11. 配置网络并在线安装 Sequoia

### 11.1 直接使用 NAT + vmxnet3

最终正确配置是：

```ini
ethernet0.present = "TRUE"
ethernet0.connectionType = "nat"
ethernet0.virtualDev = "vmxnet3"
ethernet0.pciSlotNumber = "160"
```

本次 Recovery 中 `vmxnet3` 被识别为 `en0`，并从 VMware NAT 获得 `192.168.233.x` 地址。实际地址会变化，不要硬编码。

可在 Recovery Terminal 检查：

```bash
ifconfig en0
route -n get default
```

如果只得到 `169.254.x.x`，通常表示 DHCP 失败；即使界面中出现了网卡，也不能据此判断已经联网。

### 11.2 避免宿主代理干扰 Apple CDN

本次 Windows 宿主使用 Mihomo/Clash Verge Fake-IP/TUN 时，Recovery 虽能访问 Apple CDN，但 `OSISDownloadOperation` 长时间停在起点，实际流量只有几十 KB/s。成功处理方式：

1. VM 保持 NAT + `vmxnet3`；
2. 安装前把宿主 Clash Verge 从“规则”临时切换到“直连”；
3. 确认 Apple CDN 下载速度恢复；
4. 完成系统安装后把宿主代理恢复到原来的“规则”模式。

这是临时且可逆的宿主路由调整，不是要求永久关闭代理。切换前确认宿主安全边界，安装结束后及时恢复。

### 11.3 执行在线安装

目标盘已经是 GUID + APFS、网络正常后：

1. 退出磁盘工具；
2. 选择“安装 macOS”；
3. 选择刚创建的 APFS 目标盘；
4. 接受安装过程中的多次自动重启；
5. 不要在重启间隙强制关闭 VM；
6. 等待进入 Setup Assistant。

Recovery 安装器显示俄语不代表镜像损坏。安装器语言和最终系统首次设置语言可以分别处理。

进入首次设置后创建快照：

```powershell
& $vmrun snapshot $vmx 'pre-account-setup'
```

## 12. 把俄语 Setup Assistant 离线改为简体中文

如果首次设置已经是中文或可接受的英文，可跳过本节。下面的方法是本环境实际成功的修复路线，不创建账户、不修改 `.AppleSetupDone`，也不需要知道任何密码。

### 12.1 操作边界

整个过程必须遵守：

- 不创建本地账户；
- 不填写、询问、保存或猜测密码；
- 不删除 APFS 卷；
- 不修改 `.AppleSetupDone`；
- VMX 变更前先完全关机并备份；
- 使用当前 VMX 中真实的目标差分盘名，不照抄本文的 `-000003.vmdk` 示例。

### 12.2 记录当前磁盘引用并关机

```powershell
$vmrun = 'C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe'
$vmx = 'D:\Downloads\SignRiver-Test-OS\vmware\macOS Tahoe.vmx'

Select-String -Path $vmx -Pattern '^sata0:[01]\.fileName|^sata0:[01]\.present'
& $vmrun stop $vmx soft
& $vmrun list
Get-Process vmware-vmx -ErrorAction SilentlyContinue
Copy-Item $vmx "$vmx.before-language-recovery"
```

等待 `vmrun list` 不再列出该 VM，并确认对应 `vmware-vmx.exe` 已退出。

### 12.3 临时把目标系统盘从 SATA 改挂到 NVMe

保持 BaseSystem 在 `sata0:0`，临时关闭目标盘原来的 SATA 连接，再把**同一块当前目标差分盘**挂到 NVMe。

例如当时 VMX 中是：

```ini
sata0:1.fileName = "macos-disk-000003.vmdk"
```

临时改为：

```ini
sata0:1.present = "FALSE"

nvme0.present = "TRUE"
nvme0:0.present = "TRUE"
nvme0:0.fileName = "macos-disk-000003.vmdk"
nvme0:0.redo = ""
nvme0.pciSlotNumber = "224"
```

如果当前 VMX 写的是 `macos-disk-000004.vmdk` 或更高编号，就必须在 `nvme0:0.fileName` 中使用那个当前值。不可猜测，也不可改挂基础 `macos-disk.vmdk`。

启动后，EFI 会从 SATA 上的 BaseSystem 进入 Recovery，同时 Recovery 能看到 NVMe 上已安装的 Sequoia。

### 12.4 识别 APFS 卷并挂载 Data 卷

本次识别结果是：

```text
/dev/disk0       约 107.4 GB 目标盘
  disk0s1        EFI
  disk0s2        APFS Container disk2
/dev/disk1       约 3.2 GB BaseSystem

/dev/disk2s1     Data: Macintosh HD - данные
/dev/disk2s2     Preboot
/dev/disk2s3     Recovery
/dev/disk2s4     System: Macintosh HD
/dev/disk2s6     VM
```

盘号和卷名在未来可能不同，必须先运行：

```bash
diskutil list
diskutil apfs list
```

本次 FileVault 检查结果为 `No`。挂载系统卷后，把 Data 卷挂到系统卷的 firmlink 路径：

```bash
diskutil unmount disk2s1
/sbin/mount_apfs /dev/disk2s1 "/Volumes/macintosh hd/System/Volumes/Data"
D="/Volumes/macintosh hd/System/Volumes/Data"
```

这里的 `/dev/disk2s1` 和 `/Volumes/macintosh hd` 必须按现场输出调整。不要把 Data 卷另挂到一个平行目录后直接修改；挂进 `System/Volumes/Data` 才是目标系统的完整目录布局。

### 12.5 备份并修改系统级语言偏好

真实语言来源位于：

```text
$D/Library/Preferences/.GlobalPreferences.plist
```

本次修改前是：

```text
AppleLanguages.0 = ru-CN
AppleLocale       = ru_CN
Country           = CN
```

先备份：

```bash
cp -p "$D/Library/Preferences/.GlobalPreferences.plist" \
  "$D/Library/Preferences/.GlobalPreferences.plist.before-zh"
```

写入简体中文，并保留英文作为第二语言：

```bash
plutil -replace AppleLanguages \
  -json '["zh-Hans-CN","en-US"]' \
  "$D/Library/Preferences/.GlobalPreferences.plist"

plutil -replace AppleLocale -string zh_CN \
  "$D/Library/Preferences/.GlobalPreferences.plist"

plutil -replace Country -string CN \
  "$D/Library/Preferences/.GlobalPreferences.plist"
```

同时修改 root 的全局偏好作为兜底：

```bash
R="$D/private/var/root/Library/Preferences/.GlobalPreferences.plist"
cp -p "$R" "$R.before-zh"

/usr/libexec/PlistBuddy -c "Delete :AppleLanguages" "$R" >/dev/null 2>&1
/usr/libexec/PlistBuddy -c "Add :AppleLanguages array" "$R"
/usr/libexec/PlistBuddy -c "Add :AppleLanguages:0 string zh-Hans-CN" "$R"
/usr/libexec/PlistBuddy -c "Add :AppleLanguages:1 string en-US" "$R"

/usr/libexec/PlistBuddy -c "Delete :AppleLocale" "$R" >/dev/null 2>&1
/usr/libexec/PlistBuddy -c "Add :AppleLocale string zh_CN" "$R"

/usr/libexec/PlistBuddy -c "Delete :Country" "$R" >/dev/null 2>&1
/usr/libexec/PlistBuddy -c "Add :Country string CN" "$R"
```

验证两份文件应包含：

```text
AppleLanguages.0 = zh-Hans-CN
AppleLanguages.1 = en-US
AppleLocale       = zh_CN
Country           = CN
```

注意：`plutil -extract AppleLanguages raw ...` 可能输出数组项数，例如 `35`，那不是语言代码。读取首项应使用 `AppleLanguages.0`。

### 12.6 关机并恢复正常 SATA 连接

在 Recovery 中正常关机：

```bash
shutdown -h now
```

宿主侧确认 VM 已完全停止后，只做定向恢复：

- 把 `sata0:1.present` 改回 `TRUE`；
- 删除全部临时 `nvme0...` 行；
- 如果曾加入调试用 `bios.bootDelay = "10000"`，将其删除；
- 不要用很早的 VMX 备份整体覆盖当前文件，以免丢失后续的网络、xHCI、VNC或快照配置。

正常结构应恢复为：

```ini
sata0:1.deviceType = "disk"
sata0:1.fileName = "当前 VMX 原本使用的 macos-disk-xxxxxx.vmdk"
sata0:1.present = "TRUE"
sata0:1.redo = ""
```

重启后，Setup Assistant 应显示简体中文并回到“选择国家或地区”页。右上角若仍显示“俄罗斯”，那表示当前输入源/键盘布局，不代表整个界面仍是俄语。

创建修复完成快照：

```powershell
& $vmrun snapshot $vmx 'pre-account-setup-zh'
```

### 12.7 完成首次设置并进入桌面

语言修复后，本次实际采用以下首次设置选项：

1. 数据迁移选择“设置为新机”；
2. 创建本地账户；账户名和密码由操作者保存，不写入本文；
3. Apple 账户选择“稍后设置”；
4. 定位服务保持关闭；
5. 时区手动选择中国标准时间（`Asia/Shanghai`）；
6. “与 Apple 共享 Mac 分析”和“与 App 开发者共享崩溃与使用数据”均关闭；
7. 屏幕使用时间选择“稍后设置”；
8. 外观选择“自动”；
9. 系统更新选择“自动下载，手动安装更新”。

对于依赖 Unlocker 和特定 VMX 拓扑的测试虚拟机，不应无人值守安装 macOS 大版本更新。手动更新前先正常关机并创建 VMware 快照，更新后验证启动、网络、键鼠和磁盘链。

完成上述步骤后应进入访达桌面。此时建议立即正常关机并创建新的“完成 OOBE”快照，再开始安装 VMware Tools、开发工具链和 Steam。

## 13. 快照、日常启动与状态检查

### 13.1 当前快照

1. `pre-xhci-signriver-0.2.0`：xHCI、PCIe 拓扑和键鼠修复前；
2. `pre-tahoe-apfs-install`：目标盘完成 GUID/APFS 初始化、正式安装前；
3. `pre-account-setup`：Sequoia 安装完成、俄语首次设置、语言修复前；
4. `pre-account-setup-zh`：系统级语言已改为简体中文；当前推荐恢复点。

列出快照：

```powershell
$vmrun = 'C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe'
$vmx = 'D:\Downloads\SignRiver-Test-OS\vmware\macOS Tahoe.vmx'
& $vmrun listSnapshots $vmx
```

恢复示例：

```powershell
& $vmrun stop $vmx soft
& $vmrun revertToSnapshot $vmx 'pre-account-setup-zh'
& $vmrun start $vmx gui
```

恢复快照会丢弃其后的虚拟磁盘修改。创建账户、下载工具链或放入源码后，恢复前必须导出需要保留的数据。

### 13.2 日常命令

```powershell
$vmrun = 'C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe'
$vmx = 'D:\Downloads\SignRiver-Test-OS\vmware\macOS Tahoe.vmx'

# GUI 启动
& $vmrun start $vmx gui

# 后台启动
& $vmrun start $vmx nogui

# 请求正常关机
& $vmrun stop $vmx soft

# 查看运行中的 VM
& $vmrun list

# 查看快照
& $vmrun listSnapshots $vmx
```

如果软关机长时间无响应，先检查来宾是否正在安装或更新。强制终止 `vmware-vmx.exe` 只能作为最后手段，可能损坏 APFS 或快照链。

### 13.3 `.lck` 的安全处理

只有在确认 VM 已完全停止时，才能处理遗留锁目录。优先移动到备份目录，而不是直接删除：

```powershell
$vmrun = 'C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe'
$vmx = 'D:\Downloads\SignRiver-Test-OS\vmware\macOS Tahoe.vmx'
$dir = Split-Path -Parent $vmx

& $vmrun list
Get-Process vmware-vmx -ErrorAction SilentlyContinue

$backup = Join-Path $dir ('.lck-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force $backup | Out-Null
Get-ChildItem -LiteralPath $dir -Force -Filter '*.lck' |
  Move-Item -Destination $backup
```

如果 `vmrun list` 仍列出该 VM，或对应 `vmware-vmx.exe` 仍在运行，禁止移动或删除 `.lck`。

## 14. 当前 VMX 关键配置与快照链提示

当前实际 VMX 的关键配置为：

```ini
.encoding = "UTF-8"
config.version = "8"
virtualHW.version = "21"
displayName = "macOS Tahoe"
guestOS = "darwin24-64"
firmware = "efi"
numvcpus = "4"
cpuid.coresPerSocket = "2"
memsize = "8192"

sata0:0.fileName = "BaseSystem-000004.vmdk"
sata0:1.fileName = "macos-disk-000004.vmdk"

ethernet0.connectionType = "nat"
ethernet0.virtualDev = "vmxnet3"

pciBridge4.virtualDev = "pcieRootPort"
pciBridge4.functions = "8"
pciBridge5.virtualDev = "pcieRootPort"
pciBridge5.functions = "8"
pciBridge6.virtualDev = "pcieRootPort"
pciBridge6.functions = "8"
pciBridge7.virtualDev = "pcieRootPort"
pciBridge7.functions = "8"

pciBridge4.pciSlotNumber = "21"
pciBridge5.pciSlotNumber = "22"
pciBridge6.pciSlotNumber = "23"
pciBridge7.pciSlotNumber = "24"
usb.pciSlotNumber = "34"
sata0.pciSlotNumber = "36"
ethernet0.pciSlotNumber = "160"
usb_xhci.pciSlotNumber = "192"

usb.present = "TRUE"
usb_xhci.present = "TRUE"
keyboard.vusb.present = "TRUE"
keyboard.vusb.enable = "TRUE"
mouse.vusb.present = "TRUE"
mouse.vusb.enable = "TRUE"
mouse.vusb.useBasicMouse = "FALSE"
mouse.present = "FALSE"
vmmouse.present = "TRUE"
usb.generic.allowHID = "TRUE"

svga.vramSize = "268435456"
mks.enable3d = "FALSE"

RemoteDisplay.vnc.enabled = "TRUE"
RemoteDisplay.vnc.ip = "127.0.0.1"
RemoteDisplay.vnc.port = "5901"
```

`BaseSystem-000004.vmdk` 和 `macos-disk-000004.vmdk` 是当前快照链叶子。以后创建新快照后编号可能继续增加。VMware 会自动维护父子关系，不要手工移动、重命名、替换或跨目录复制其中任何一层 VMDK。

## 15. 从零复现后的验收清单

完成主线后逐项确认：

- [ ] VMware Workstation 能启动 VM，且 VMware 自身不发生 `0xc0000005` 崩溃；
- [ ] `guestOS = "darwin24-64"`，固件为 EFI，虚拟硬件版本为 21；
- [ ] BaseSystem Recovery 能启动；
- [ ] 键盘和鼠标在 Recovery 中可用；
- [ ] 目标盘显示约 107.16 GB，并已抹成 GUID + APFS；
- [ ] 网卡为 NAT + `vmxnet3`，存在默认路由，而不是只有 `169.254.x.x`；
- [ ] Apple 在线安装能持续下载并完成多次自动重启；
- [ ] 已安装系统是 Sequoia / Darwin 24，而不是被历史 `Tahoe` 文件名误导；
- [x] Setup Assistant 是简体中文，并已完成首次设置进入桌面；
- [ ] VNC 若启用，只监听 `127.0.0.1`；
- [ ] 已建立安装前、账户设置前和中文修复后的快照；
- [ ] 当前 VMX 仍引用最新差分盘，没有误退回基础 VMDK。

## 16. 失败路线与排障记录

本节保留历史试错，仅用于解释故障和避免未来重复尝试，不是从零复现的执行顺序。

### 16.1 VirtualBox + OpenCore 路线：最终放弃

初期曾尝试：

- 让 VirtualBox 直接运行 macOS；
- 把 BaseSystem 转成 VDI/VMDK；
- 制作 OpenCore 启动盘；
- 加入 [Lilu 1.7.2](https://github.com/acidanthera/Lilu/releases/download/1.7.2/Lilu-1.7.2-RELEASE.zip)、[VirtualSMC 1.3.7](https://github.com/acidanthera/VirtualSMC/releases/download/1.3.7/VirtualSMC-1.3.7-RELEASE.zip) 和 [VoodooPS2Controller 2.3.7](https://github.com/acidanthera/VoodooPS2/releases/download/2.3.7/VoodooPS2Controller-2.3.7-RELEASE.zip)；
- 用 [MSYS2 mtools 软件包页](https://packages.msys2.org/packages/mingw-w64-x86_64-mtools)取得的 `mtools` 修改 FAT32 中的 `EFI/OC/config.plist`；
- 用 `keyboardputscancode` 选择 OpenCore 启动项；
- 排查 GPT、ESP、FAT32、HFS+、APFS 扫描和 Apple DeviceProperties。

相关历史脚本仍保留在：

```text
D:\Downloads\SignRiver-Test-OS\macos\boot-recovery.ps1
D:\Downloads\SignRiver-Test-OS\macos\boot-kbdonly.ps1
D:\Downloads\SignRiver-Test-OS\macos\boot-voodoo.ps1
D:\Downloads\SignRiver-Test-OS\vmware\rebuild-opencore.ps1
D:\Downloads\SignRiver-Test-OS\vmware\rebuild-and-start.ps1
```

主要问题：

1. `mtools` 生成的 FAT32 表面能看到 EFI 文件，但 VirtualBox EFI 不一定把它识别为有效 ESP；
2. OpenCore 能启动后，恢复分区仍可能因 DeviceProperties 或 APFS 驱动扫描链不显示；
3. VoodooPS2Controller 与新系统 Recovery 的兼容性不理想；
4. scancode 只能勉强操作 OpenCore 菜单，进入 Recovery 后键鼠仍不可靠；
5. 继续投入意味着同时维护 VirtualBox EFI、OpenCore、APFS 驱动和输入设备兼容，成本高于迁移 VMware。

结论：**VirtualBox 不再作为运行平台，只保留 `VBoxManage.exe` 做磁盘转换。**

### 16.2 完整 InstallAssistant.pkg / SharedSupport 路线：不再作为主线

历史上通过 `gibMacOS` 下载了约 18 GB 的完整 `InstallAssistant.pkg`，并尝试展开 `SharedSupport.dmg`、生成 `SharedSupport.img`、`macos-install.vdi` 和 `macos-install.vmdk`。

曾使用：

```powershell
Set-Location 'D:\Downloads\SignRiver-Test-OS\tools\gibMacOS-master'
python gibMacOS.py -l --no-interactive `
  -o 'D:\Downloads\SignRiver-Test-OS\macos'
```

当时还使用 BITS、`curl` 和 aria2 处理大文件下载。最终稳定 VMware 启动入口并不是 `SharedSupport` 介质，而是 `macrecovery.py` 下载的 `BaseSystem.dmg` 转换成的 VMDK，再从 Recovery 联网安装。

结论：完整安装器保留作历史资源，但未来优先执行第 6～7 节，避免先下载和展开 18 GB 安装包。

### 16.3 xHCI、键鼠和 VMware 0xc0000005

历史症状：

- 鼠标锁在左上角；
- 键盘无法可靠输入；
- 打开 xHCI 时 VMware 报没有可用 PCIe 插槽；
- VMware Workstation 17.6.4 自身发生 `0xc0000005` 崩溃。

最终根因不是 Sequoia、BaseSystem 或系统盘损坏，而是 VMX PCIe 拓扑：

- `pciBridge*.virtualDev` 曾误写成 `virtualDevice`；
- Root Port 缺少 `functions = "8"`；
- bridge、USB、SATA、网卡和 xHCI 的 PCI 槽位冲突；
- 网卡注册/PCIe 冲突可让 VMware 自身空指针崩溃。

修复就是采用第 8.3 节完整配置：

- `virtualDev = "pcieRootPort"`；
- bridge 4～7 都有 `functions = "8"`；
- bridge 槽位固定为 21～24；
- USB/SATA/网卡/xHCI 分别使用 34/36/160/192；
- 启用 vUSB 键盘、vUSB 鼠标、`vmmouse` 和 xHCI。

不要因为 VMware 崩溃就先回滚或重建系统盘；先检查 VMX 拓扑和重复键。

### 16.4 网卡失败路线

本次尝试结果：

1. `e1000e`：Recovery 不识别；
2. `e1000`：仍没有可用网卡；
3. `vmxnet3`：成功识别为 `en0` 并获得 NAT 地址；
4. 桥接：只获得 `169.254.x.x`，没有默认路由；
5. 恢复 NAT 后稳定。

结论：正文从一开始就使用 NAT + `vmxnet3`，不要重走上述顺序。

### 16.5 Apple CDN 能访问但安装下载不动

症状是 HTTPS/域名表面可访问，但安装停在 `OSISDownloadOperation` 起点，流量极低。根因与 Windows 宿主上的 Mihomo/Clash Verge Fake-IP/TUN 路由有关。

结论：保留 NAT + `vmxnet3`，安装期间临时把宿主代理切成直连，安装完成后恢复原模式。不要为了这个问题改桥接或反复更换虚拟网卡。

### 16.6 dmg2img 假 ZIP

本次曾下载到两个 16700-byte 的 `dmg2img.zip` / `dmg2img-1.6.7.zip`，实际内容是 HTML 页面，SHA256 均为：

```text
699e35119c027415d2b2848ce2b9b9da3186dde6041205ed44930dc248411955
```

真正成功使用的归档是：

```text
dmg2img-1.6.7-win32.zip
64462 bytes
SHA256 c33595575b08d04ab3cd1d7bc0339fc7ffa473d5969ce29a2a206d08dc4f42a4
```

结论：下载后必须检查大小、SHA256 和 `PK` 文件头，不能只看扩展名。

### 16.7 俄语首次设置：未成功或有风险的方法

以下方法已经尝试但没有解决问题，或会引发启动循环：

1. 在 Setup Assistant 中按 `Control + Option + Command + T` 打开 Terminal：当前身份是 `_mbsetupuser`，没有可用 sudo 密码，无法修改系统级设置；
2. `defaults write -g AppleLanguages ...`：只改临时用户偏好，重启后会被覆盖；
3. `Language Chooser`：能选择简体中文，但应用时一直转圈，重启后仍回俄语；
4. 修改 NVRAM 的 `prev-lang:kbd`：只影响固件/键盘语言线索，不能单独改变 Setup Assistant；
5. `-s keepsyms=1` 单用户模式：在本虚拟硬件组合中卡在 AHCI 初始化附近；
6. 用 `Command-R`、`Escape` 抢 Recovery：VMware 启动阶段难以稳定捕获；
7. `nvram recovery-boot-mode=unused`：在本环境造成大约每 11 秒一次的 EFI 重启循环，**禁止再次使用**；
8. Recovery 中 `chroot` 后运行 `languagesetup`：缺少所需 dyld cache / InternationalSupport framework；
9. `macosguest.forceRecoveryModeInstall = "TRUE"`：曾导致 EFI 循环，**不要再次加入 VMX**。

最终成功方法只有第 12 节：保持 BaseSystem 为 SATA 启动盘，把当前目标差分盘临时改挂 NVMe，在 Recovery 中离线改系统级 plist。

### 16.8 故障—原因—处理速查

| 故障 | 根因/判断 | 最终处理 |
| --- | --- | --- |
| VirtualBox EFI 不认 OpenCore FAT32 | FAT/GPT/ESP 和固件兼容问题 | 放弃 VBox 运行主线 |
| OpenCore 看不到 Recovery | DeviceProperties/APFS 扫描链问题 | 改用 VMware 直接启动 BaseSystem |
| Recovery 键鼠失效 | PS/2 路径与新系统兼容差 | VMware xHCI + 虚拟 USB 键鼠 |
| 鼠标锁在左上角 | vUSB/xHCI 路径未正确建立 | 启用 vUSB、`vmmouse`、xHCI |
| xHCI 没有 PCIe 槽位 | Root Port 键名、functions 或槽位错误 | 使用第 8.3 节固定拓扑 |
| VMware `0xc0000005` | PCIe/网卡注册冲突 | 修正 VMX，不回滚系统盘 |
| `e1000e` / `e1000` 无网卡 | Sequoia Recovery 驱动不匹配 | NAT + `vmxnet3` |
| 桥接得到 `169.254.x.x` | DHCP 失败、无默认路由 | 恢复 NAT |
| Apple CDN 下载不动 | 宿主 Fake-IP/TUN/代理路由干扰 | 临时直连，完成后恢复规则 |
| 自动输入进不了 Recovery | Windows SendInput 未进入来宾 | 仅回环地址的临时 VNC |
| Setup Assistant 为俄语 | 系统级 plist 为 `ru-CN` / `ru_CN` | BaseSystem + 临时 NVMe，离线改 plist |

## 17. 已知限制与后续工作

1. 虚拟机已完成简体中文首次设置并进入桌面，但尚未形成可 SSH 的日常开发环境；
2. 当前 VNC 无认证，必须继续只监听 `127.0.0.1`，用完后关闭；
3. VMX 名称和部分快照仍写 `Tahoe`，实际系统是 Sequoia；暂不重命名以免影响脚本和快照；
4. 当前快照链叶子为 `BaseSystem-000004.vmdk` 与 `macos-disk-000004.vmdk`，以后编号会变化；禁止手工移动、重命名或替换快照盘；
5. macOS 内的 VMware Tools、Python、Rust、Steam、icecream、HOI4 和 SignRiver 客户端真实验收尚未完成；
6. Windows 宿主不能替代 Intel macOS 环境构建最终 dylib，必须在这台 VM 或其他合规 Intel macOS 环境中完成；
7. 首次设置阶段的 1024×768 画面可操作；进入桌面后的最终分辨率和 VMware Tools 状态仍待验证；
8. Apple Recovery 和完整安装器 CDN URL 可能变化，未来应优先通过 `macrecovery.py` 或 Apple 软件目录重新解析，而不是只依赖本文记录的固定地址。
