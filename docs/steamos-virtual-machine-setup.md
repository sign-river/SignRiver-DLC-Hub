# SteamOS 虚拟机从零搭建、改造与排障记录

> 最后核对：2026-08-16
> 当前状态：VirtualBox 虚拟机已关机，当前快照为 `steamos-0.2.0-validated`，能够启动、SSH 接管并运行 SignRiver 0.2.0 与 HOI4 测试流程。

## 1. 文档定位

本文记录本项目实际使用的 SteamOS 测试虚拟机从镜像准备、VirtualBox 建机、首次启动、显示与内核改造，到最终项目验收状态的完整过程。

这里的“安装 SteamOS”并不是使用传统桌面发行版 ISO 执行一次标准安装，而是：

1. 获取 Valve 的 Steam Deck OOBE/Recovery 磁盘镜像；
2. 把原始磁盘镜像转换为 VirtualBox 的 VDI；
3. 直接从恢复磁盘启动；
4. 额外挂载一块大容量数据盘；
5. 对恢复系统做适合长期自动化测试的内核、显示、SSH、关机、Steam Runtime 和存储调整。

因此，它更准确地说是一台“由 Steam Deck 恢复镜像改造成的稳定 SteamOS 测试机”。本文中的系统级改造只属于测试基础设施，不进入 SignRiver 客户端发行包。

## 2. 最终状态摘要

| 项目 | 当前值 |
| --- | --- |
| 虚拟化软件 | VirtualBox `7.2.14r174565` |
| 虚拟机名 | `SteamOS` |
| 来宾类型 | Arch Linux 64-bit / x86_64 |
| 固件 | EFI，Secure Boot 关闭 |
| CPU | 2 vCPU |
| 内存 | 8192 MB |
| 显存 | 256 MB |
| 图形控制器 | `VMSVGA`，3D 加速开启 |
| 磁盘 0 | 恢复系统盘 `steamos-install.vdi` |
| 磁盘 1 | 128 GiB 动态数据盘 `steamos-disk.vdi` |
| 网络 | NAT，Intel PRO/1000 MT Desktop (`82540EM`) |
| SSH 转发 | 宿主 `127.0.0.1:2222` → 来宾 `22` |
| 下载服务转发 | 宿主 `9001` → 来宾 `9000` |
| 剪贴板/拖放 | 双向 |
| USB/音频 | 关闭 |
| 当前电源状态 | `poweroff` |
| 当前快照 | `steamos-0.2.0-validated` |

当前磁盘位置：

```text
D:\Downloads\SignRiver-Test-OS\steamos\vm\steamos-install.vdi
D:\Downloads\SignRiver-Test-OS\steamos\vm\steamos-disk.vdi
```

## 3. 前置资源与下载链接

### 3.1 资源下载总表

下表优先记录本次实操真正使用的固定版本和直接下载地址。对于由 `pacman`、`pip` 或 Steam 客户端自动选择镜像的资源，同时给出官方稳定入口，避免以后镜像路径变化后无法定位。标有“失败尝试”的链接只用于还原排障过程，不应作为当前推荐方案。

| 资源 | 本次版本或文件 | 下载/说明链接 | 本次用途与状态 |
| --- | --- | --- | --- |
| Oracle VirtualBox | `7.2.14r174565` | [Windows 安装包](https://download.virtualbox.org/virtualbox/7.2.14/VirtualBox-7.2.14-174565-Win.exe)；[SHA256SUMS](https://download.virtualbox.org/virtualbox/7.2.14/SHA256SUMS)；[7.2.14 文件目录](https://download.virtualbox.org/virtualbox/7.2.14/) | 宿主虚拟化软件，当前虚拟机由此版本创建和运行。 |
| Steam Deck Recovery/OOBE 镜像 | `steamdeck-oobe-repair-20260707.10-3.8.14.img.bz2` | [本次镜像直接下载](https://steamdeck-images.steamos.cloud/recovery/steamdeck-oobe-repair-20260707.10-3.8.14.img.bz2)；[Valve Recovery 说明](https://help.steampowered.com/en/faqs/view/1B71-EDF2-EB6D-2BB3)；[官方镜像索引](https://steamdeck-images.steamos.cloud/recovery/) | 作为恢复系统盘；不是 ISO。 |
| Python 3 | 宿主已有版本 | [Python for Windows](https://www.python.org/downloads/windows/) | 只使用标准库 `bz2` 解压恢复镜像，并用 `pip download` 获取 Linux wheels。 |
| Windows OpenSSH Client | Windows 可选功能 | [Microsoft 安装与首次使用说明](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse) | 通过 NAT 转发使用 SSH/SCP 接管来宾。 |
| Arch Linux LTS 内核 | `linux-lts 6.18.44-1` | [当前包页面](https://archlinux.org/packages/core/x86_64/linux-lts/)；[固定版本归档](https://archive.archlinux.org/packages/l/linux-lts/linux-lts-6.18.44-1-x86_64.pkg.tar.zst)；[归档签名](https://archive.archlinux.org/packages/l/linux-lts/linux-lts-6.18.44-1-x86_64.pkg.tar.zst.sig) | 实际通过来宾 `pacman` 仓库安装；固定归档链接用于以后复现相同版本。 |
| 64 位 Lavapipe | `vulkan-swrast 1:26.1.6-1` | [当前包页面](https://archlinux.org/packages/extra/x86_64/vulkan-swrast/)；[固定版本归档](https://archive.archlinux.org/packages/v/vulkan-swrast/vulkan-swrast-1%3A26.1.6-1-x86_64.pkg.tar.zst)；[归档签名](https://archive.archlinux.org/packages/v/vulkan-swrast/vulkan-swrast-1%3A26.1.6-1-x86_64.pkg.tar.zst.sig) | 实际通过 `pacman` 安装，为 64 位程序提供软件 Vulkan。 |
| 32 位 Lavapipe | `lib32-vulkan-swrast 1:25.1.6-1` | [固定版本归档](https://archive.archlinux.org/packages/l/lib32-vulkan-swrast/lib32-vulkan-swrast-1%3A25.1.6-1-x86_64.pkg.tar.zst)；[归档签名](https://archive.archlinux.org/packages/l/lib32-vulkan-swrast/lib32-vulkan-swrast-1%3A25.1.6-1-x86_64.pkg.tar.zst.sig)；[归档目录](https://archive.archlinux.org/packages/l/lib32-vulkan-swrast/) | 本次最终采用的兼容版本；验签后只提取 `usr/lib32/libvulkan_lvp.so`。 |
| Python Linux wheels | CPython 3.14 / manylinux2014 x86_64 | [清华 PyPI 镜像](https://pypi.tuna.tsinghua.edu.cn/simple)；[官方 PyPI](https://pypi.org/) | 宿主下载后通过 SCP 传入来宾；精确包版本见 10.3。 |
| SmokeAPI | `v4.1.3` | [发布页](https://github.com/acidicoala/SmokeAPI/releases/tag/v4.1.3)；[ZIP 直接下载](https://github.com/acidicoala/SmokeAPI/releases/download/v4.1.3/SmokeAPI-v4.1.3.zip)；[安装文档](https://smokeapi.readthedocs.io/en/latest/user/install.html) | 用于 HOI4 proxy 模式和 DLC 生命周期真实验收。 |
| Hearts of Iron IV | Steam App ID `394360` | [Steam 商店页](https://store.steampowered.com/app/394360/Hearts_of_Iron_IV/) | 由 Steam 客户端下载到数据盘；需要账户已拥有游戏。 |

### 3.2 必需软件

- Windows 宿主机；
- [Oracle VirtualBox 7.2.14 Windows 安装包](https://download.virtualbox.org/virtualbox/7.2.14/VirtualBox-7.2.14-174565-Win.exe)；
- [Python 3 for Windows](https://www.python.org/downloads/windows/)，用于稳定解压 `.bz2`；
- [Windows OpenSSH Client](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse)，用于后续远程接管；
- 足够的磁盘空间：恢复镜像压缩包约 3.13 GiB，恢复盘转换后约数 GiB，数据盘逻辑容量 128 GiB，快照还会继续占用空间。

### 3.3 使用的恢复镜像

本次使用的本地文件：

```text
D:\Downloads\SignRiver-Test-OS\steamos\steamdeck-oobe-repair-20260707.10-3.8.14.img.bz2
```

直接下载地址：

```text
https://steamdeck-images.steamos.cloud/recovery/steamdeck-oobe-repair-20260707.10-3.8.14.img.bz2
```

官方入口：

- [Valve：Steam Deck Recovery Instructions](https://help.steampowered.com/en/faqs/view/1B71-EDF2-EB6D-2BB3)
- [Valve 官方恢复镜像索引](https://steamdeck-images.steamos.cloud/recovery/)

本地文件核对结果：

```text
文件大小：3357999306 bytes
SHA256：4254ee02ec34ae8add9aceef1881a2ce675a9d0176171df92e0eaa1bf014c594
```

该文件不是 ISO。若需重新下载，可在 Windows PowerShell 中执行：

```powershell
$dir = 'D:\Downloads\SignRiver-Test-OS\steamos'
New-Item -ItemType Directory -Force $dir | Out-Null
curl.exe -fL --retry 3 `
  -o "$dir\steamdeck-oobe-repair-20260707.10-3.8.14.img.bz2" `
  'https://steamdeck-images.steamos.cloud/recovery/steamdeck-oobe-repair-20260707.10-3.8.14.img.bz2'
Get-FileHash -Algorithm SHA256 `
  "$dir\steamdeck-oobe-repair-20260707.10-3.8.14.img.bz2"
```

恢复镜像索引会继续增加新版本；本文固定使用 `20260707.10-3.8.14`，不要在复现当前虚拟机时未经验证就替换成最新文件。

## 4. 从零创建虚拟机

### 4.1 解压恢复镜像

最初尝试过用 `tar -xjf` 解压，但该路线在 Windows 环境下不稳定。最终直接使用 Python 标准库 `bz2`：

```python
import bz2
import shutil

src = r"D:\Downloads\SignRiver-Test-OS\steamos\steamdeck-oobe-repair-20260707.10-3.8.14.img.bz2"
dst = r"D:\Downloads\SignRiver-Test-OS\steamos\steamdeck-oobe-repair-20260707.10-3.8.14.img"

with bz2.open(src, "rb") as fin, open(dst, "wb") as fout:
    shutil.copyfileobj(fin, fout, length=4 * 1024 * 1024)
```

解压完成后先确认 `.img` 文件存在且大小合理，再进行格式转换。

### 4.2 转换恢复盘并创建数据盘

```powershell
$VBoxManage = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
$dir = 'D:\Downloads\SignRiver-Test-OS\steamos'

New-Item -ItemType Directory -Force "$dir\vm" | Out-Null

& $VBoxManage convertfromraw `
  "$dir\steamdeck-oobe-repair-20260707.10-3.8.14.img" `
  "$dir\vm\steamos-install.vdi" `
  --format VDI

& $VBoxManage createmedium disk `
  --filename "$dir\vm\steamos-disk.vdi" `
  --size 131072 `
  --format VDI
```

`131072` 的单位是 MiB，即逻辑容量 128 GiB。该 VDI 是动态分配磁盘，宿主文件不会一开始就占满 128 GiB。

### 4.3 创建 VirtualBox 虚拟机

最初创建时使用 4096 MB 内存和 128 MB 显存，后续为构建、Steam 和游戏测试提高到 8192 MB 与 256 MB。

```powershell
$VBoxManage = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
$dir = 'D:\Downloads\SignRiver-Test-OS\steamos'

& $VBoxManage createvm --name SteamOS --ostype ArchLinux_64 --register

& $VBoxManage modifyvm SteamOS `
  --memory 8192 `
  --cpus 2 `
  --vram 256 `
  --graphicscontroller vmsvga `
  --accelerate-3d on `
  --firmware efi `
  --nic1 nat `
  --nictype1 82540EM `
  --ioapic on `
  --audio-enabled off `
  --usb off `
  --clipboard-mode bidirectional `
  --drag-and-drop bidirectional
```

创建 SATA 控制器并挂载两块磁盘：

```powershell
& $VBoxManage storagectl SteamOS `
  --name SATA `
  --add sata `
  --controller IntelAhci `
  --portcount 2

& $VBoxManage storageattach SteamOS `
  --storagectl SATA `
  --port 0 `
  --device 0 `
  --type hdd `
  --medium "$dir\vm\steamos-install.vdi"

& $VBoxManage storageattach SteamOS `
  --storagectl SATA `
  --port 1 `
  --device 0 `
  --type hdd `
  --medium "$dir\vm\steamos-disk.vdi"
```

设置 NAT 端口转发：

```powershell
& $VBoxManage modifyvm SteamOS `
  --natpf1 "ssh,tcp,127.0.0.1,2222,,22" `
  --natpf1 "dldl,tcp,,9001,,9000"
```

SSH 只绑定到宿主回环地址，避免直接暴露到局域网。下载服务当前配置允许宿主的 `9001` 进入来宾 `9000`；如果不再需要，应删除该规则或也限制为回环地址。

### 4.4 首次启动

```powershell
& $VBoxManage startvm SteamOS --type gui
```

恢复镜像测试阶段使用过默认用户 `deck`。接管后应立即更换密码，并优先使用 SSH 公钥；本文不记录任何密码或私钥。

SSH 连接方式：

```powershell
ssh -p 2222 deck@127.0.0.1
```

## 5. 首次启动后看到的“异常”并非都是真故障

### 5.1 没有 KDE 菜单和终端快捷键

该恢复/OOBE 镜像启动的是裸 X 会话，而不是完整 KDE Plasma 桌面。因此下列现象在初期是预期行为：

- 没有开始菜单；
- Windows/Super 键没有桌面菜单；
- `Ctrl+Alt+T` 不会打开终端；
- 图形界面更像安装/恢复环境，而不像标准桌面。

正确的管理方式是尽快启用 SSH，通过宿主终端操作，而不是依赖来宾 GUI。

### 5.2 第二块盘的用途

系统根分区和 `/home` 空间很紧张，后续 `/home` 一度只剩约 226 MB。最终把源码、构建环境、包缓存、游戏和测试证据迁移到大容量数据盘，例如：

```text
/mnt/games/signriver-e2e
/mnt/games/.local/share/Steam
```

不要把大型 Python 虚拟环境、Steam 游戏、PyInstaller 构建目录或 pacman 缓存长期放在恢复系统根盘。

## 6. 显示问题：从 640×480 到可用分辨率

这是整个 SteamOS 路线中最耗时的问题之一。

### 6.1 初始症状

- `VMSVGA` 下只能得到约 640×480；
- 宿主窗口缩放只会把画面放大并裁切，不会真正增加来宾分辨率；
- 原恢复内核没有为当前 `VMSVGA` 路径正常加载 `vmwgfx`；
- Xorg 回退到 EFI framebuffer。

### 6.2 无效或不稳定尝试

#### 改用 `VBoxSVGA` / `VBoxVGA`

两者都实际试过，但出现过花屏、启动画面损坏或更差的兼容性，最终均放弃并回到 `VMSVGA`。

#### 只修改 EFI/固件分辨率

这不能解决 Xorg 驱动缺失问题。固件阶段的分辨率设置不会自动变成 X 会话的可用模式。

#### 仅在宿主侧缩放

这只是视觉放大，不是来宾新增显示模式，因此会产生裁切。

### 6.3 早期过渡方案：独立 Xorg + `vboxvideo`

在更换内核前，曾通过独立 Xorg 服务和 `xrandr` 获得 1440×900。历史服务如下：

```ini
[Unit]
Description=SignRiver test Xorg display
After=systemd-user-sessions.service
Conflicts=display-manager.service

[Service]
ExecStart=/usr/lib/Xorg :0 -ac -noreset
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical.target
```

分辨率服务：

```ini
[Unit]
Description=Set SignRiver test display resolution
After=signriver-xorg.service
Requires=signriver-xorg.service

[Service]
Type=oneshot
ExecStart=/usr/bin/bash -c 'for i in {1..20}; do DISPLAY=:0 /usr/bin/xrandr --output VGA-1 --mode 1440x900 && exit 0; sleep 1; done; exit 1'
RemainAfterExit=yes

[Install]
WantedBy=graphical.target
```

历史启用方式：

```bash
sudo install -m 644 \
  /home/deck/signriver-xorg.service \
  /home/deck/signriver-resolution.service \
  /home/deck/signriver-client.service \
  /etc/systemd/system/

sudo systemctl disable sddm
sudo systemctl daemon-reload
sudo systemctl enable --now \
  signriver-xorg \
  signriver-resolution \
  signriver-client
```

这是过渡方案，不是最终结论。换用 LTS 内核后输出名可能变为 `Virtual-1`，不能继续假定一定是 `VGA-1`。每次都应先运行：

```bash
DISPLAY=:0 XAUTHORITY=/home/deck/.Xauthority xrandr --current
```

### 6.4 最终方案：保留原内核，新增 Arch LTS 测试内核

在修改内核前先创建快照：

```powershell
$VBoxManage = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
& $VBoxManage snapshot SteamOS take 'before-arch-lts-vmsvga' `
  --description 'SteamOS validation state before installing Arch LTS kernel for VirtualBox VMSVGA 3D support'
```

解除只读并安装 LTS 内核。本次仓库返回并安装的是 `linux-lts 6.18.44-1`：

```bash
sudo steamos-readonly disable 2>/dev/null || true
sudo pacman -S --noconfirm --needed linux-lts
```

`pacman` 会按来宾 `/etc/pacman.d/mirrorlist` 自动选择镜像，因此当时终端命令中没有固定的单一下载 URL。可用下面的官方入口定位资源：

- [Arch Linux 当前 `linux-lts` 包页面](https://archlinux.org/packages/core/x86_64/linux-lts/)
- [`linux-lts-6.18.44-1` 固定归档包](https://archive.archlinux.org/packages/l/linux-lts/linux-lts-6.18.44-1-x86_64.pkg.tar.zst)
- [该归档包的 detached signature](https://archive.archlinux.org/packages/l/linux-lts/linux-lts-6.18.44-1-x86_64.pkg.tar.zst.sig)

固定归档只用于需要复现当前快照中的确切版本；正常安装仍优先使用 `pacman`，由包管理器完成依赖解析和签名检查。

根分区空间不足后，将 pacman 缓存迁到数据盘：

```bash
sudo mkdir -p /mnt/games/signriver-e2e/pacman-cache
sudo pacman -S --noconfirm --needed \
  --cachedir /mnt/games/signriver-e2e/pacman-cache \
  linux-lts
```

安装过程还遇到 SteamOS 包依赖中把 `initramfs` 当作依赖能力、但仓库解析不顺的问题，历史上最终使用过：

```bash
sudo pacman -S --noconfirm --needed \
  --assume-installed=initramfs \
  --cachedir /mnt/games/signriver-e2e/pacman-cache \
  linux-lts
```

这条命令是针对当时恢复镜像仓库状态的兼容处理，不应在其他系统上无条件照抄。执行前应确认现有 initramfs 工具链和 `/boot` 状态。

重新生成 SteamOS 的 EFI GRUB 配置前先备份：

```bash
sudo cp /efi/EFI/steamos/grub.cfg \
  /mnt/games/signriver-e2e/evidence/grub.cfg.before-lts
sudo grub-mkconfig -o /efi/EFI/steamos/grub.cfg
sudo grep -E '^menuentry |^submenu ' /efi/EFI/steamos/grub.cfg
find /usr/lib/modules -name 'vmwgfx.ko*' -print
```

先只让下一次启动进入 LTS，验证成功后再固定：

```bash
entry='gnulinux-advanced-651004c4-7509-4853-b71c-cacc991d8c8d>gnulinux-linux-lts-advanced-651004c4-7509-4853-b71c-cacc991d8c8d'
sudo grub-editenv /efi/EFI/steamos/grubenv set next_entry="$entry"
sudo grub-editenv /efi/EFI/steamos/grubenv list
sudo systemctl poweroff
```

随后在宿主侧确认 `VMSVGA`、3D 和 256 MB 显存：

```powershell
& $VBoxManage modifyvm SteamOS `
  --graphicscontroller vmsvga `
  --accelerate-3d on `
  --vram 256
& $VBoxManage startvm SteamOS --type gui
```

启动后验证：

```bash
uname -r
lspci -nnk | sed -n '/VGA compatible controller/,+5p'
lsmod | grep vmwgfx
DISPLAY=:0 XAUTHORITY=/home/deck/.Xauthority glxinfo -B
DISPLAY=:0 XAUTHORITY=/home/deck/.Xauthority xrandr --current
```

历史实操为了快速固定测试快照，复制生成后的 `grub.cfg`，把 `set default="0"` 改为下面的 LTS 条目，再装回 `/efi/EFI/steamos/grub.cfg`：

```text
gnulinux-advanced-651004c4-7509-4853-b71c-cacc991d8c8d>gnulinux-linux-lts-advanced-651004c4-7509-4853-b71c-cacc991d8c8d
```

必须注意：`grub.cfg` 是生成文件，再次执行 `grub-mkconfig` 会覆盖手工修改。当前做法依赖快照和已保存的配置副本；如果要长期维护，应改为从 `/etc/default/grub` 或自定义 GRUB 脚本生成默认项，而不是反复直接编辑生成文件。

原 `linux-neptune-616` 内核仍保留在 GRUB 高级启动项中，因此 LTS 失败时仍可回退。

## 7. ACPI 电源按钮不能关机

### 7.1 症状与根因

VirtualBox 发送 ACPI 电源按钮后系统无反应。检查合并后的 logind 配置发现：

```ini
HandlePowerKey=ignore
```

### 7.2 修复

创建 `/etc/systemd/logind.conf.d/zz-signriver-poweroff.conf`：

```ini
[Login]
HandlePowerKey=poweroff
PowerKeyIgnoreInhibited=no
```

安装并重启 logind：

```bash
sudo install -m 644 \
  /home/deck/zz-signriver-poweroff.conf \
  /etc/systemd/logind.conf.d/zz-signriver-poweroff.conf

sudo systemctl restart systemd-logind
systemd-analyze cat-config systemd/logind.conf
```

宿主侧验证：

```powershell
& $VBoxManage controlvm SteamOS acpipowerbutton
```

该修复已完成真实关机、重新启动和服务恢复验证。

## 8. Steam 启动与登录状态丢失

### 8.1 不要使用 OOBE 包装器

`/usr/bin/steam` 在该镜像中指向 `steam-jupiter` 包装流程，会执行 OOBE 初始化并清理 Steam 配置，曾导致 Steam 更新后登录状态消失。

最终直接启动真正的 Steam 客户端：

```bash
/usr/lib/steam/steam
```

### 8.2 systemd 临时服务缺少用户会话环境

只设置 `DISPLAY=:0` 时，Steam Runtime Launch Service 会因为没有用户运行目录和 D-Bus 会话而崩溃。正确的环境至少包括：

```bash
sudo systemd-run \
  --unit=signriver-steam \
  --property=Restart=no \
  --uid=deck \
  --working-directory=/home/deck \
  --setenv=HOME=/home/deck \
  --setenv=DISPLAY=:0 \
  --setenv=XDG_RUNTIME_DIR=/run/user/1000 \
  --setenv=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
  --setenv=XAUTHORITY=/home/deck/.Xauthority \
  /usr/lib/steam/steam -skipinitialbootstrap
```

如果 UI 仍受虚拟 GPU 限制，可按当时测试方式额外加入 `-cef-disable-gpu -cef-disable-gpu-compositing`。

Steam 客户端本体已经包含在恢复镜像中；首次启动后的更新由客户端自动下载，并非手工下载一个固定安装包。排障时确认过的官方更新/运行时入口包括：

- [Steam Linux 客户端更新端点](https://client-update.akamai.steamstatic.com/steam_client_ubuntu12)
- [Steam Runtime 仓库入口](https://repo.steampowered.com/steamrt)
- [Steam Runtime 4 镜像目录](https://repo.steampowered.com/steamrt4/images/)

这些地址会由 Steam 自行选择具体清单和文件，不应把某次 CDN 响应缓存成长期固定安装包。

## 9. VirtualBox 无 Vulkan：使用 Lavapipe 软件渲染

VirtualBox 图形栈无法提供游戏需要的原生 Vulkan。最终使用 Mesa 的 Lavapipe 软件 Vulkan 驱动。

### 9.1 64 位 `vulkan-swrast`

本次先由 SteamOS/Arch 仓库安装 64 位包，实际版本为 `1:26.1.6-1`：

```bash
sudo steamos-readonly disable
sudo pacman -Syy --noconfirm
sudo pacman -S --noconfirm --needed vulkan-swrast
```

下载入口：

- [Arch Linux 当前 `vulkan-swrast` 包页面](https://archlinux.org/packages/extra/x86_64/vulkan-swrast/)
- [`vulkan-swrast-1:26.1.6-1` 固定归档包](https://archive.archlinux.org/packages/v/vulkan-swrast/vulkan-swrast-1%3A26.1.6-1-x86_64.pkg.tar.zst)
- [该归档包的 detached signature](https://archive.archlinux.org/packages/v/vulkan-swrast/vulkan-swrast-1%3A26.1.6-1-x86_64.pkg.tar.zst.sig)

和 LTS 内核一样，实际安装流量由 `pacman` 的 mirrorlist 决定；固定归档链接用于版本回溯。

### 9.2 32 位驱动：先失败，再回退到匹配 LLVM 的归档版本

32 位 Steam/游戏组件还需要 32 位 Lavapipe。最初下载了当时 Arch multilib 镜像中的新包：

- [失败尝试：`lib32-vulkan-icd-loader 1.4.357.0-1`](https://geo.mirror.pkgbuild.com/multilib/os/x86_64/lib32-vulkan-icd-loader-1.4.357.0-1-x86_64.pkg.tar.zst)
- [失败尝试：`lib32-vulkan-swrast 1:26.1.7-1`](https://geo.mirror.pkgbuild.com/multilib/os/x86_64/lib32-vulkan-swrast-1%3A26.1.7-1-x86_64.pkg.tar.zst)

直接执行 `pacman -U` 时，旧 SteamOS 仓库无法解析 `lib32-expat`、`lib32-libdrm`、`lib32-llvm-libs` 等一整套新依赖。强行只提取新包中的 `libvulkan_lvp.so` 后，`ldd` 又显示它要求不存在的 `libLLVM.so.22.1`。因此这两个新包只属于失败排障记录，不能用于当前镜像。

最终从 Arch Linux Archive 下载与来宾现有 `libLLVM.so.20.1` 匹配的旧版：

- [最终包：`lib32-vulkan-swrast 1:25.1.6-1`](https://archive.archlinux.org/packages/l/lib32-vulkan-swrast/lib32-vulkan-swrast-1%3A25.1.6-1-x86_64.pkg.tar.zst)
- [最终包签名](https://archive.archlinux.org/packages/l/lib32-vulkan-swrast/lib32-vulkan-swrast-1%3A25.1.6-1-x86_64.pkg.tar.zst.sig)
- [Arch Archive 版本目录](https://archive.archlinux.org/packages/l/lib32-vulkan-swrast/)

宿主下载命令：

```powershell
curl.exe -fL --retry 3 `
  -o .test-artifacts\lib32-vulkan-swrast-25.1.6.pkg.tar.zst `
  'https://archive.archlinux.org/packages/l/lib32-vulkan-swrast/lib32-vulkan-swrast-1%3A25.1.6-1-x86_64.pkg.tar.zst'

curl.exe -fL --retry 3 `
  -o .test-artifacts\lib32-vulkan-swrast-25.1.6.pkg.tar.zst.sig `
  'https://archive.archlinux.org/packages/l/lib32-vulkan-swrast/lib32-vulkan-swrast-1%3A25.1.6-1-x86_64.pkg.tar.zst.sig'
```

本次下载文件核对结果：

```text
大小：2159250 bytes
SHA256：17e5023b1a0e07c32bbe4bf4b5e6d5fd26b764fd88a021f9294dff3e03138993
签名文件大小：119 bytes
```

由于旧 SteamOS 的 multilib 仓库依赖不完整，最终没有把整个包注册进 pacman 数据库，而是先验签，再只提取所需的 32 位共享库：

```bash
pacman-key --verify \
  /tmp/lib32-vulkan-swrast-25.1.6.pkg.tar.zst.sig \
  /tmp/lib32-vulkan-swrast-25.1.6.pkg.tar.zst

sudo bsdtar -xpf \
  /tmp/lib32-vulkan-swrast-25.1.6.pkg.tar.zst \
  -C / usr/lib32/libvulkan_lvp.so
sudo ldconfig
file /usr/lib32/libvulkan_lvp.so
ldd /usr/lib32/libvulkan_lvp.so | grep -E 'LLVM|not found'
```

验收时 `ldd` 成功解析到 `/usr/lib32/libLLVM.so.20.1`。这种“只提取单个文件”的方式是针对旧恢复镜像的受控兼容措施，不适合作为普通 Arch Linux 的通用安装方法；升级 Mesa/LLVM 后必须重新核对 ABI。

### 9.3 启动时强制软件渲染

```bash
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe
export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/lvp_icd.json
export VK_DRIVER_FILES=/usr/share/vulkan/icd.d/lvp_icd.json
```

这适合功能验收，不代表有可接受的游戏性能。

## 10. 下载、空间与构建环境问题

### 10.1 根分区空间不足

`/home` 一度只剩约 226 MB。解决原则：

- 源码和构建目录放到 `/mnt/games/signriver-e2e`；
- Steam 游戏库放到大容量盘；
- pacman 缓存放到大容量盘；
- 完成内核安装后清理 pacman 缓存；
- 不要在根盘保留多个 PyInstaller 临时目录。

必要时检查：

```bash
df -h
sudo du -xhd1 / /home /var 2>/dev/null | sort -h
```

### 10.2 同步内容过多导致超时

首次同步误带缓存和历史测试目录，产生大量无用传输并超时。最终只同步：

- 受控源码；
- 测试；
- 配置；
- 构建脚本；
- 必要的本地包与证据。

确认某个临时副本不完整后才删除，避免误删唯一源码。

### 10.3 PyPI 下载过慢

当时官方 PyPI 约 40 KB/s，清华镜像约 400–480 KB/s，但仍不足以稳定完成全部构建依赖。最终由 Windows 宿主下载与 Linux x64/Python 3.14 匹配的 manylinux2014 x86_64 wheels，再通过 SSH/SCP 传入离线安装。

本次实际使用的下载入口：

- [官方 PyPI](https://pypi.org/)
- [清华 PyPI 镜像 simple index](https://pypi.tuna.tsinghua.edu.cn/simple)
- 排障测速时还测试过 [阿里云 PyPI 镜像](https://mirrors.aliyun.com/pypi/simple/ruff/)，但最终批量下载命令使用清华镜像。

宿主侧最终命令：

```powershell
python -m pip download `
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple `
  --only-binary=:all: `
  --platform manylinux2014_x86_64 `
  --python-version 3.14 `
  --implementation cp `
  --abi cp314 `
  --dest '.test-artifacts\steamos-wheels' `
  'customtkinter>=5.2,<6' `
  'Pillow>=10,<13' `
  'pytest>=8,<10' `
  'pyinstaller>=6,<7' `
  'ruff>=0.12,<1'
```

直接依赖的最终版本与稳定项目页：

| 包 | 本次 wheel | PyPI 固定版本页 |
| --- | --- | --- |
| CustomTkinter | `customtkinter-5.2.2-py3-none-any.whl` | [5.2.2](https://pypi.org/project/customtkinter/5.2.2/) |
| Pillow | `pillow-12.2.0-cp314-cp314-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` | [12.2.0](https://pypi.org/project/Pillow/12.2.0/) |
| pytest | `pytest-9.1.1-py3-none-any.whl` | [9.1.1](https://pypi.org/project/pytest/9.1.1/) |
| PyInstaller | `pyinstaller-6.22.0-py3-none-manylinux2014_x86_64.whl` | [6.22.0](https://pypi.org/project/pyinstaller/6.22.0/) |
| Ruff | `ruff-0.16.3-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | [0.16.3](https://pypi.org/project/ruff/0.16.3/) |

`pip download` 同时解析并下载了以下传递依赖；这些固定版本页也可用于以后手工补包：

- [altgraph 0.17.5](https://pypi.org/project/altgraph/0.17.5/)
- [colorama 0.4.6](https://pypi.org/project/colorama/0.4.6/)
- [darkdetect 0.8.0](https://pypi.org/project/darkdetect/0.8.0/)
- [iniconfig 2.3.0](https://pypi.org/project/iniconfig/2.3.0/)
- [packaging 26.3](https://pypi.org/project/packaging/26.3/)
- [pluggy 1.6.0](https://pypi.org/project/pluggy/1.6.0/)
- [Pygments 2.20.0](https://pypi.org/project/Pygments/2.20.0/)
- [pyinstaller-hooks-contrib 2026.6](https://pypi.org/project/pyinstaller-hooks-contrib/2026.6/)
- [setuptools 84.0.0](https://pypi.org/project/setuptools/84.0.0/)
- [pefile 2024.8.26](https://pypi.org/project/pefile/2024.8.26/) 和 [pywin32-ctypes 0.2.3](https://pypi.org/project/pywin32-ctypes/0.2.3/) 也进入了宿主下载目录，但 Linux 来宾安装时未选用这两个 Windows 相关依赖。

随后将整个目录复制到 `/mnt/games/signriver-wheels`，在来宾里用 `--no-index --find-links` 离线安装。最终完成了 pytest、Ruff、PyInstaller 和项目虚拟环境。

## 11. 快照与回滚

当前快照链：

1. `pre-signriver-0.2.0`
   SignRiver 0.2.0 原生构建和 HOI4 验收前。
2. `before-arch-lts-vmsvga`
   安装 Arch LTS 测试内核并切换最终 VMSVGA 路线前。
3. `steamos-0.2.0-validated`
   当前快照；描述为：`SteamOS 0.2.0 final native build, update rollback, HOI4 SmokeAPI and DLC lifecycle validated`。

列出快照：

```powershell
$VBoxManage = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
& $VBoxManage snapshot SteamOS list --machinereadable
```

恢复前应先正常关机：

```powershell
& $VBoxManage controlvm SteamOS acpipowerbutton
& $VBoxManage snapshot SteamOS restore 'before-arch-lts-vmsvga'
```

恢复快照会丢弃该快照之后的来宾磁盘状态。项目源码或证据如果只存在虚拟机里，恢复前必须先导出。

## 12. 日常操作

```powershell
$VBoxManage = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'

# GUI 启动
& $VBoxManage startvm SteamOS --type gui

# 无界面启动
& $VBoxManage startvm SteamOS --type headless

# 请求正常关机
& $VBoxManage controlvm SteamOS acpipowerbutton

# 查看配置与状态
& $VBoxManage showvminfo SteamOS --machinereadable

# 查看快照
& $VBoxManage snapshot SteamOS list --machinereadable
```

SSH：

```powershell
ssh -p 2222 deck@127.0.0.1
```

## 13. 当前验收结果

在 `steamos-0.2.0-validated` 状态已完成：

验收资源下载入口：

- [Hearts of Iron IV（Steam App ID 394360）](https://store.steampowered.com/app/394360/Hearts_of_Iron_IV/)，由 Steam 客户端下载到数据盘；
- [SmokeAPI v4.1.3 发布页](https://github.com/acidicoala/SmokeAPI/releases/tag/v4.1.3)；
- [SmokeAPI-v4.1.3.zip 直接下载](https://github.com/acidicoala/SmokeAPI/releases/download/v4.1.3/SmokeAPI-v4.1.3.zip)；
- [SmokeAPI 安装文档](https://smokeapi.readthedocs.io/en/latest/user/install.html) 和 [Quickstart](https://smokeapi.readthedocs.io/en/latest/user/quickstart.html)。

本次 SmokeAPI ZIP 大小为 `6852049` bytes，SHA256 为 `8a443b5b4c434a4904b272ea4d93ad7e13e212626c0e49466176cb828c1d2a3b`。

- 最新源码 pytest、Ruff、compileall；
- SteamOS 原生 tar.gz 和更新 ZIP 构建；
- 冻结包启动冒烟；
- 冻结包全量更新、自动重启、用户数据保留和事务确认；
- 注入损坏后的失败回滚；
- HOI4 原版进入主菜单；
- SmokeAPI v4.1.3 proxy 模式真实运行；
- DLC 安装后从 4 个 Active DLC 增加到 5 个；
- 安装审计 `healthy`；
- 人为损坏识别为 `modified`；
- 修复后恢复 `healthy`；
- 安全卸载并恢复原版 `libsteam_api.so`；
- 原版游戏再次启动成功。

最新产物哈希与大小以 `docs/current-progress.md` 为准，避免在两份文档中重复维护后产生不一致。

## 14. 已知限制

1. 这是恢复镜像改造的测试机，不是官方支持的通用 PC SteamOS 安装形态。
2. LTS 内核和直接固定生成后的 GRUB 配置属于测试基础设施调整，SteamOS 更新可能覆盖它们。
3. Lavapipe/llvmpipe 是软件渲染，只用于功能验证，性能不能代表真实 Steam Deck 或 Linux 游戏 PC。
4. 双向剪贴板和拖放已配置，但不应替代 SSH/SCP 作为可靠文件传输方式。
5. 默认 `deck` 账户只应作为恢复阶段入口；长期使用必须换密码并使用独立公钥。
6. 恢复快照前先导出项目产物和测试证据，避免回滚磁盘时一起丢失。
