---
name: winx-to-windows-terminal
description: 把 Windows Win+X 菜单中的 "Windows PowerShell" 项切换为新版终端（Windows Terminal / PowerShell 7）。适用于 Windows 10/11 及 Windows Server 2016/2019/2022，尤其是没有 Microsoft Store、无法通过设置界面更改默认终端的服务器系统。核心是解决 Win+X 快捷方式的 TWINUI hash 校验问题——直接修改 .lnk 会导致菜单项消失。当用户要求"让 Win+X 打开新终端/PowerShell 7/Windows Terminal"时使用。
---

# Win+X → Windows Terminal 切换指南

## 目标

让 Win+X（右键开始按钮）菜单中的两项 PowerShell 打开**新版终端**：

- 首选目标：`wt.exe`（Windows Terminal），默认配置文件指向 PowerShell 7 (`pwsh.exe`)
- 无 Windows Terminal 时退而求其次：直接指向 `pwsh.exe`

## 关键知识（不读会踩坑）

### 1. Win+X 菜单项存放位置

```
%LOCALAPPDATA%\Microsoft\Windows\WinX\Group3\
├── 01a - Windows PowerShell.lnk   ← 普通项（任务栏设置开启"用 PowerShell 替换 CMD"时显示）
├── 02a - Windows PowerShell.lnk   ← 管理员项（带 RunAsUser 标志）
└── desktop.ini                    ← [LocalizedFileNames] 显示名映射（见第 4 条坑）
```

`01`/`02`（不带 a）是 CMD 版本，与 `01a`/`02a` 按任务栏设置二选一显示。

### 2. TWINUI hash 校验（最大的坑）

Windows 8+ 的 Win+X 菜单会校验每个 .lnk 中存储的 hash（属性键 `PKEY_WINX_HASH`，
fmtid `{FB8D2D7B-90D1-4E34-BF60-6EAC09922BBF}` pid 2，VT_UI4）。
**用普通方式创建/修改的快捷方式没有有效 hash，菜单项会直接消失，且无任何报错。**

hash 算法（Rafael Rivera 逆向，hashlnk 项目）：

```
blob = generalize(targetPath) + arguments + SALT
SALT = "do not prehash links.  this should only be done by the user."
hash = shlwapi!HashData(UTF16LE(lowercase(blob)), 4 bytes out)
```

`generalize()` 把已知文件夹前缀替换为 GUID 字符串（大写带花括号）：

| 前缀 | 替换为 |
|---|---|
| `%ProgramFiles%`（WOW64 下用 `%ProgramW6432%`） | `{905E63B6-C1BF-494E-B29C-65B732D3D21A}` |
| `%SystemRoot%\System32` | `{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}` |
| `%SystemRoot%` | `{F38BF404-1D43-42F2-9305-67DE0B28FC23}` |

**写入方式**：COM `IPropertyStore::SetValue` 在部分系统（如 Server 2022）上会返回
`STG_E_ACCESSDENIED`。可靠做法是**二进制原位替换**：在 .lnk 的 PropertyStoreDataBlock
中定位 fmtid 字节 `7B 2D 8D FB D1 90 34 4E BF 60 6E AC 09 92 2B BF`，其后找到
`00 13 00 00 00`（Reserved+VT_UI4+Padding），随后 4 字节即旧 hash，直接覆盖为新值。
旧值与新值同为 VT_UI4，长度一致，原位写不会破坏文件结构。

**自校验技巧**：修改前先用原快捷方式的 target 算一遍 hash，与文件内存储的旧值对比，
一致即证明算法实现正确（微软原厂文件的 hash 就是基准答案）。

### 3. 管理员标志位

"以管理员身份运行"存储在 .lnk 文件头 LinkFlags 的 `RunAsUser (0x2000)` 位，
即文件偏移 **21 (0x15)** 字节的 `0x20` 位。WScript.Shell / IShellLink 保存后该位
可能丢失，需用二进制方式补写。注意：此修改不影响 hash（hash 只覆盖 target+args）。

### 4. 菜单显示名的坑

Win+X 菜单显示的文本来自 **.lnk 的 Description（备注）字段**，不是 desktop.ini！
desktop.ini 的 `[LocalizedFileNames]` 只在 Description 为空时兜底。
所以改名字要 `IShellLink::SetDescription()`，改 desktop.ini 没用。

### 5. 顺手推荐：默认终端应用程序

把系统默认终端设为 Windows Terminal（任何方式启动的控制台都进新窗口）：

```
HKCU\Console\%%Startup
  DelegationConsole = {2EACA947-7F5F-4CFA-BA87-8F7FBEEFBE69}
  DelegationTerminal = {E12CFF52-A866-4C77-9A90-F570A7AA2C6B}
```

## 执行步骤

1. **前置检查**
   - `wt.exe`：Windows Terminal 通常在 `%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe`（应用执行别名）
   - `pwsh.exe`：PowerShell 7 通常在 `C:\Program Files\PowerShell\7\pwsh.exe`
   - 两者都没有就先安装其一，否则没有意义

2. **运行 scripts/install_winx_wt.py**（需 `pip install pywin32`）
   - 自动选择目标（有 wt.exe 用 wt，否则用 pwsh）
   - 自动备份原文件到 `./backup/`
   - 改写两个 .lnk 的 target/icon/description/runas 标志
   - 重新计算并原位写入 WinX hash
   - 写入前自动用原文件做算法自校验

3. **重启 Explorer**：`Stop-Process -Name explorer -Force; Start-Process explorer.exe`

4. **验证**：按 Win+X，应出现 "PowerShell 7" 与 "PowerShell 7 （管理员）"，
   点击打开 Windows Terminal 新窗口

## 回滚

把 `backup/` 中的文件复制回 `%LOCALAPPDATA%\Microsoft\Windows\WinX\Group3\`，
重启 Explorer 即可（原文件的 hash 本来有效，无需重算）。
也可运行 `scripts/revert_winx.py`。

## 已知边界情况

- **内置 Administrator + EnableLUA=0（常见于 Windows Server）**：系统上不存在
  非提升进程，两个菜单项打开的窗口都会显示"管理员"，这是真实令牌状态，不是 bug。
- **UAC 开启的普通系统**：管理员项会弹 UAC，正常。
- **Windows 11 22H2+**：系统原生支持在 设置→隐私和安全性→开发者→终端 中选择
  Windows Terminal，且 Win+X 已自带"终端"项，一般不需要本 skill。
