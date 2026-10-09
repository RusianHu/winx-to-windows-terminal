---
name: winx-to-windows-terminal
description: 检查、切换或恢复 Windows Win+X 菜单中已有的两项旧版 Windows PowerShell 快捷方式，使其打开 Windows Terminal 或 PowerShell 7。用户要求让 Win+X、右键开始菜单打开新终端，修复此次切换或回滚时使用。仅处理当前用户已有的 legacy PowerShell .lnk；已有 Windows 11 原生终端菜单或只需设置默认终端、默认配置文件时，优先使用系统内置设置。
compatibility: Requires native Windows Python 3.10+ and local execution as the target Windows user. Installation requires pywin32, a working Windows Terminal or PowerShell 7, and both existing legacy PowerShell WinX shortcuts. Rollback requires the validated backup but no pywin32 or COM.
---

# 切换 Win+X 旧版 PowerShell 项

## 入口和执行环境

- 使用 [scripts/install_winx_wt.py](scripts/install_winx_wt.py) 检查和安装；使用 [scripts/revert_winx.py](scripts/revert_winx.py) 回滚。
- 用户要求回滚时，完成对应环境和备份检查后直接执行第 5 节；无需先安装目标程序、运行安装脚本或校验已损坏的现有链接。
- 从宿主提供的本 `SKILL.md` 路径确定技能根目录。所有附带文件相对该目录解析，不依赖用户当前工作目录或某个宿主专有目录、变量、工具名称。
- 在目标 Windows 用户环境中执行 Windows 原生 Python 3.10+。没有相应执行能力时，提供检查结果和可由用户运行的命令，并明确尚未修改其 Windows 环境。
- 按用户已授权的操作推进。只读检查使用 `--dry-run`；已获授权的安装或回滚，在检查通过后继续执行，无需重复索要同一操作的确认。

以下 PowerShell 示例中的 `$skillRoot` 必须先设置为实际技能目录的完整路径：

```powershell
$skillRoot = "D:\Tools\winx-to-windows-terminal"
python -c "import sys; print(sys.executable); print(sys.version); print(sys.platform)"
```

## 1. 检查是否适用

1. 安装时确认当前用户 Group3 内已有 `01a - Windows PowerShell.lnk` 和 `02a - Windows PowerShell.lnk`，完整目录为 `%LOCALAPPDATA%\Microsoft\Windows\WinX\Group3`。缺少任一项时停止安装，不创建替代链接、不改 CMD 项、不套用到 Windows 11 原生“终端”项。回滚可从完整备份恢复缺失的目标文件，但原 Group3 目录必须存在。
2. 如果需求仅是调整原生终端或默认 shell，按[微软设置指南](https://learn.microsoft.com/en-us/windows/terminal/install)使用 Windows Terminal“设置 → 启动”中的受支持选项。不要把默认终端和 Terminal 默认配置文件当成同一个设置。
3. 确认 Python 为 Windows 原生解释器且版本满足要求。安装需要同一解释器的 `pywin32`，缺少时用 `python -m pip install pywin32` 安装。回滚不需要此依赖。依赖下载需要网络，已有依赖的本地修改流程不需要联网。
4. 安装时确认至少一个目标程序已经安装并适配当前 OS。使用 `PATH`、WindowsApps、Program Files 等环境路径发现程序；特殊安装位置通过命令行覆盖。不要仅根据“Windows 10/11/Server”名称宣称兼容。
5. 使用需要修改菜单的用户身份；核实其 Group3 和备份目录可写。不要为了设置管理员菜单项而自动切换为其他管理员账户。

涉及旧 Server、缺失链接、UAC、hash 不匹配或旧版备份时，读取[技术说明](references/technical-notes.md)。

## 2. 选择目标并预览

默认目标为 `auto`：

| 发现的程序 | 行为 |
|---|---|
| Terminal 和 PowerShell 7 | 用 Terminal 新窗口显式启动 `pwsh.exe` 完整路径，菜单名为 PowerShell 7 |
| 只有 Terminal | 用 Terminal 新窗口启动默认配置文件，菜单名为 Windows Terminal |
| 只有 PowerShell 7 | 直接启动 `pwsh.exe`，菜单名为 PowerShell 7 |
| 均未发现 | 停止并报告缺少目标 |

普通项和管理员项使用相同目标，管理员项保留对应提升标志。不要把“只有 Terminal”报告为已安装或已启动 PowerShell 7。

```powershell
python (Join-Path $skillRoot "scripts\install_winx_wt.py") --dry-run
```

按用户需求追加参数，并在正式执行时复用相同参数：

- `--target terminal`：强制使用 Terminal，缺少该程序时停止。
- `--target pwsh`：强制直接使用 PowerShell 7，缺少该程序时停止。
- `--terminal-path EXE`、`--pwsh-path EXE`：覆盖自动发现，传入实际可执行文件完整路径。
- `--backup-dir DIR`：更换备份位置；后续回滚必须使用同一参数。

检查预览中的目标用户目录、程序路径、启动参数、菜单名称和备份位置。`--dry-run` 不改写 WinX 快捷方式或创建备份。出现 hash 不匹配、文件缺失、备份损坏或路径不符时，解决原因后重新预览，不绕过校验。

## 3. 执行安装

预览通过且安装已获授权后，去掉 `--dry-run` 执行：

```powershell
python (Join-Path $skillRoot "scripts\install_winx_wt.py")
```

脚本会先校验两份当前链接及已有备份，在临时副本上修改并复验；首次备份完整建立或已有备份验证通过后，才替换正式文件。默认备份为 `%LOCALAPPDATA%\winx-to-windows-terminal\backup`，包括两份原始 `.lnk` 和绑定目标 Group3 的 SHA256 清单 `manifest.json`。重复执行不覆盖首次备份；安装及回滚都不改写 `desktop.ini`。

如果命令失败，检查其异常和恢复结果。可捕获的替换异常会触发当次文件恢复；断电、强制终止或恢复失败仍需根据实际文件状态处理，不宣称两文件更新具有整体原子性。

## 4. 刷新和验证

1. 不自动结束 Explorer。提示用户先保存资源管理器中的操作；需要刷新时，可在任务管理器重启当前用户的 Windows 资源管理器。
2. 验证 Win+X 两项可见、名称符合所选目标。
3. 分别启动普通项和管理员项，验证实际 shell、Terminal 新窗口行为及 UAC 提升情况。无法操作目标桌面时，明确这些检查待用户实测。
4. 报告实际采用的目标程序、启动方式、备份位置，以及文件校验和真实菜单验证各自的结果。不要根据退出码单独宣称所有 Windows 版本或真实菜单均已通过。

## 5. 回滚

```powershell
python (Join-Path $skillRoot "scripts\revert_winx.py") --dry-run
python (Join-Path $skillRoot "scripts\revert_winx.py")
```

使用自定义备份目录时，两次命令都追加同一 `--backup-dir DIR`。回滚只接受属于当前 Group3 且两份文件校验均通过的清单备份，只恢复这两份 `.lnk`；缺少清单、备份文件损坏或目录不符时停止。完成后按上节刷新并验证。

旧版 `scripts/backup` 的无清单文件需要人工核对来源。保留旧文件，确认确为本用户原始备份后，仅手动恢复两份 PowerShell `.lnk` 到原 Group3；不要恢复 `desktop.ini` 或伪造新版清单。处理方法见[技术说明](references/technical-notes.md)。
