# winx-to-windows-terminal

让 Windows **Win+X 菜单**（右键开始按钮）打开**新版终端**（Windows Terminal + PowerShell 7），
替换掉默认的旧版 Windows PowerShell 5.1。

适用于 Windows 10 / 11 / Server 2016 / 2019 / 2022，特别适合没有 Microsoft Store、
无法通过设置界面修改默认终端的服务器环境。

## 为什么不是改个快捷方式就行？

Windows 8 起，Win+X 菜单对每个快捷方式做 **TWINUI hash 校验**：
普通方式修改或新建的 .lnk 没有有效 hash，菜单项会**直接消失且无任何提示**。
本仓库的脚本完整实现了 hash 的重新计算与原位写入（算法来自 Rafael Rivera 的
[hashlnk](https://github.com/riverar/hashlnk) 逆向成果），并解决了：

- COM `IPropertyStore` 写属性在部分系统上 `STG_E_ACCESSDENIED` → 改为二进制原位替换
- 菜单显示名实际来自 .lnk 的 **Description 字段**而非 desktop.ini
- "以管理员身份运行"标志（LinkFlags `RunAsUser`）在重写快捷方式后会丢失 → 二进制补写
- 写入前用微软原厂文件做**算法自校验**，不一致就中止，不会把菜单改坏

## 使用

```powershell
pip install pywin32
python scripts/install_winx_wt.py
Stop-Process -Name explorer -Force; Start-Process explorer.exe
```

按 `Win+X`，菜单中应出现 **PowerShell 7** 与 **PowerShell 7 （管理员）**，
点击打开 Windows Terminal 新窗口。

回滚：

```powershell
python scripts/revert_winx.py
Stop-Process -Name explorer -Force; Start-Process explorer.exe
```

## 可选：把系统默认终端也设为 Windows Terminal

```powershell
New-Item -Path "HKCU:\Console\%%Startup" -Force
New-ItemProperty -Path "HKCU:\Console\%%Startup" -Name DelegationConsole `
  -Value "{2EACA947-7F5F-4CFA-BA87-8F7FBEEFBE69}" -PropertyType String -Force
New-ItemProperty -Path "HKCU:\Console\%%Startup" -Name DelegationTerminal `
  -Value "{E12CFF52-A866-4C77-9A90-F570A7AA2C6B}" -PropertyType String -Force
```

这样从任何入口（运行框、其他软件）启动 cmd/pwsh 都会在 Windows Terminal 中打开。

## 目录结构

```
├── SKILL.md                      # 完整指南与原理（agent skill 格式）
├── scripts/
│   ├── install_winx_wt.py        # 安装脚本（自动选 wt.exe/pwsh、备份、盖 hash）
│   └── revert_winx.py            # 回滚脚本
└── LICENSE                       # MIT
```

## License

MIT
