# winx-to-windows-terminal

把 Windows **Win+X 菜单中已有的旧版 Windows PowerShell 快捷方式**改为打开 Windows Terminal 或 PowerShell 7，保留普通项和管理员项，并提供预览、备份和回滚。

本仓库也是一个采用 [Agent Skills 标准](https://agentskills.io/specification)的技能目录，可交给能够执行 Windows 本地命令的 Agent 使用。`SKILL.md` 是技能入口，脚本也可以单独运行。

## 适用范围

安装前需要满足以下条件；回滚只需 Windows 原生 Python、仍存在的原 Group3 目录，以及完整有效的备份，不要求目标程序或两份现有链接仍在：

- 当前 Windows 用户的 `%LOCALAPPDATA%\Microsoft\Windows\WinX\Group3` 中，已存在 `01a - Windows PowerShell.lnk` 和 `02a - Windows PowerShell.lnk`。缺少任意一项时安装脚本停止；它不会创建 CMD 菜单项或 Windows 11 原生“终端”菜单项。
- 使用 **Windows 原生 Python 3.10 或以上版本**。安装脚本需要同一 Python 环境中的 `pywin32`；回滚不需要 `pywin32` 或 COM。WSL/Linux Python 不能用于修改本机快捷方式。
- 已安装且能够在当前系统上运行 Windows Terminal、PowerShell 7，或两者。脚本不会替你安装这些应用。
- 以需要修改菜单的 Windows 用户运行，并能够写入其 Group3 和备份目录。更换账户运行会操作另一个用户的配置；创建管理员菜单项本身不要求把整个脚本以其他管理员账户运行。

**Windows 11 已有原生“终端”菜单项时，优先使用系统和 Terminal 的内置设置。** 如果只是选择默认终端应用程序或默认 PowerShell 配置文件，参见下方“默认终端设置”。

当前 Windows Terminal 官方要求 **Windows 10 2004（build 19041）或更新系统**。Windows Server 2016/2019 不能笼统视为支持当前 Terminal；只有在能使用微软支持该系统的 PowerShell 7 版本时，才考虑 `--target pwsh` 直连。其他 Windows/Server 版本也必须满足上述前置条件，具体菜单行为需要在对应系统上实测。参见 [Terminal 系统要求](https://github.com/microsoft/terminal#installing-and-running-windows-terminal)及 [PowerShell 支持周期](https://learn.microsoft.com/en-us/powershell/scripting/install/powershell-support-lifecycle)。

## 使用

以下是 PowerShell 命令。把 `$skillRoot` 改为实际存放本仓库的完整路径；命令不依赖当前工作目录。

```powershell
$skillRoot = "D:\Tools\winx-to-windows-terminal"
python --version
python -m pip install pywin32
python (Join-Path $skillRoot "scripts\install_winx_wt.py") --dry-run
```

`--dry-run` 检查现有快捷方式、目标程序和备份条件，并显示修改计划；它不改写 WinX 快捷方式，也不建立备份。确认输出中的当前用户目录和目标程序符合预期后执行：

```powershell
python (Join-Path $skillRoot "scripts\install_winx_wt.py")
```

默认 `--target auto` 的选择如下：

| 可用程序 | 启动行为 | 菜单名称 |
|---|---|---|
| Windows Terminal 和 PowerShell 7 | 在 Terminal 新窗口中，显式运行发现的 `pwsh.exe` 完整路径 | PowerShell 7 / PowerShell 7（管理员） |
| 只有 Windows Terminal | 在 Terminal 新窗口中使用其默认配置文件 | Windows Terminal / Windows Terminal（管理员） |
| 只有 PowerShell 7 | 直接启动 `pwsh.exe`，窗口宿主取决于系统配置 | PowerShell 7 / PowerShell 7（管理员） |
| 两者都没有 | 停止并报告缺少目标程序 | 不修改菜单 |

同时安装两个程序时，脚本不依赖 Terminal 中名为“PowerShell”的配置文件，也不需要修改其默认配置文件。Terminal 的新窗口参数参见[微软命令行文档](https://learn.microsoft.com/en-us/windows/terminal/command-line-arguments)。

### 选择目标或指定路径

```powershell
# 强制直接使用 PowerShell 7
python (Join-Path $skillRoot "scripts\install_winx_wt.py") --target pwsh --dry-run

# 使用指定的 Terminal 和 PowerShell 可执行文件
python (Join-Path $skillRoot "scripts\install_winx_wt.py") `
  --target terminal `
  --terminal-path "D:\Apps\Terminal\WindowsTerminal.exe" `
  --pwsh-path "D:\Apps\PowerShell\pwsh.exe" `
  --dry-run
```

上述示例通过后，去掉 `--dry-run` 执行同一计划。

| 参数 | 用途 |
|---|---|
| `--dry-run` | 检查并预览 |
| `--target auto\|terminal\|pwsh` | 自动选择、强制 Terminal 或强制直连 PowerShell 7；强制的目标缺失时停止 |
| `--terminal-path EXE` | 指定 Terminal 可执行文件的完整路径，覆盖自动发现 |
| `--pwsh-path EXE` | 指定 PowerShell 7 可执行文件的完整路径，覆盖自动发现 |
| `--backup-dir DIR` | 指定备份目录；之后回滚时必须指定同一目录 |
| `--help` | 查看当前脚本支持的参数 |

自动发现会检查 `PATH`、当前用户的 WindowsApps 应用执行别名及 Program Files 等相关环境路径。安装位置特殊或发现了非预期版本时，使用显式路径。

### 刷新菜单并验证

脚本完成后，先保存资源管理器中正在进行的操作；如菜单尚未刷新，可在任务管理器中重启**当前用户的 Windows 资源管理器**，再打开 Win+X。脚本不会自动结束 Explorer 进程。

分别打开普通项和管理员项，检查名称、目标 shell、是否新开窗口，以及管理员项是否按当前 UAC 策略请求提升。脚本的文件校验成功不等于已经验证了真实菜单和启动结果。排查细节见[技术说明](references/technical-notes.md)。

## 备份与回滚

默认备份位于：

```text
%LOCALAPPDATA%\winx-to-windows-terminal\backup
```

备份包含两份原始 `.lnk` 和 `manifest.json`。清单记录所属 Group3 目录及文件 SHA256；重复安装会验证并保留首次备份。安装前先校验两份当前快捷方式的 WinX hash，在临时副本上完成修改和复验后才替换原文件。

回滚先预览，再恢复：

```powershell
python (Join-Path $skillRoot "scripts\revert_winx.py") --dry-run
python (Join-Path $skillRoot "scripts\revert_winx.py")
```

如果安装时使用了 `--backup-dir "D:\Backups\WinX"`，两条回滚命令也需要追加相同参数。回滚只恢复清单中的两份快捷方式；备份缺失、损坏或属于另一个 Group3 目录时拒绝恢复。只要原 Group3 目录仍存在且备份完整，回滚也可以恢复已经删除的这两项。安装和回滚都不改写 `desktop.ini`。

发生可捕获的替换异常时，脚本会尝试恢复本次操作前的文件，并报告失败。两文件更新不具备断电或进程被强制终止时的整体原子性；保留备份，并在中断后检查两项状态。

**从旧版本迁移：** 旧版 `scripts/backup` 中没有新版清单的备份不会被自动信任或导入。先保留旧文件，人工核对它们确为当前用户对应系统的原始备份；需要恢复时，仅将其中两份原始 PowerShell `.lnk` 复制回原 Group3 目录，再运行新版。不要覆盖 `desktop.ini`，也不要自行补写清单来绕过校验。

## 作为 Agent Skill 安装

把本仓库完整目录放入宿主支持的技能位置，并保持目录名为 `winx-to-windows-terminal`。保留 `SKILL.md`、`scripts/` 和 `references/` 的相对位置。

| 宿主 | 用户级技能目录示例 |
|---|---|
| Codex | `%USERPROFILE%\.agents\skills\winx-to-windows-terminal\` |
| Claude Code | `%USERPROFILE%\.claude\skills\winx-to-windows-terminal\` |
| 其他兼容 Agent | 按该宿主文档选择目录，读取同一份 `SKILL.md` |

宿主发现目录由各产品决定，Agent Skills 格式本身不强制安装位置。参见 [Codex 技能文档](https://developers.openai.com/codex/skills)和 [Claude Code 技能文档](https://code.claude.com/docs/en/skills)。本技能需要在目标 Windows 用户环境执行脚本；只有云端或 Linux 执行环境的 Agent 可以审查和提供命令，但不能据此声称已修改本机菜单。

## 默认终端设置

“Win+X 快捷方式目标”“默认终端应用程序”和“Terminal 默认配置文件”是三个不同设置。本脚本只处理前者。

在系统支持时，打开 **Windows Terminal → 设置 → 启动**，选择“默认终端应用程序”或“默认配置文件”。微软目前将默认终端应用程序设置列为所有 Windows 11，以及安装 KB5026435 后的 Windows 10 22H2 支持的功能；其他版本请查阅对应系统文档。参见[微软安装和设置指南](https://learn.microsoft.com/en-us/windows/terminal/install#set-your-default-terminal-application)。

## 文件说明

| 文件 | 内容 |
|---|---|
| [SKILL.md](SKILL.md) | Agent 执行流程、依赖及边界 |
| [scripts/install_winx_wt.py](scripts/install_winx_wt.py) | 检查、备份、替换快捷方式 |
| [scripts/revert_winx.py](scripts/revert_winx.py) | 校验备份并恢复快捷方式 |
| [references/technical-notes.md](references/technical-notes.md) | WinX hash、权限、备份及故障排查 |

## 开发验证

在仓库根目录运行 `python -m unittest discover -s tests -v`。测试使用合成的 `.lnk` 和临时目录，覆盖属性解析、目标发现、备份隔离及失败恢复；不会修改现有 WinX 菜单。Windows 上还需安装 `pywin32`，以运行临时快捷方式的原生 COM 集成测试。

[CI](.github/workflows/tests.yml) 在 Windows、Linux 和 Python 3.10、3.13 上运行这些测试。测试通过仍需与真实 Explorer 菜单、UAC 和 Terminal 启动结果分别记录。

## License

[MIT](LICENSE)。WinX hash 算法研究来源见 [Rafael Rivera 的 hashlnk](https://github.com/riverar/hashlnk)。
