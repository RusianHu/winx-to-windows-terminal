# 技术说明与故障排查

## 支持的菜单结构

目标为当前用户的 `%LOCALAPPDATA%\Microsoft\Windows\WinX\Group3`，仅处理以下两个已有文件：

| 文件名 | 用途 |
|---|---|
| `01a - Windows PowerShell.lnk` | 普通 PowerShell 项 |
| `02a - Windows PowerShell.lnk` | 管理员 PowerShell 项 |

安装时两份文件必须都存在并通过校验。菜单使用 CMD 变体、链接被删除、原始布局不同或 Windows 11 使用原生 Terminal 项时，不通过创建空链接或借用其他用户链接来绕过检查。回滚可从完整清单备份恢复缺失的目标文件，要求原 Group3 目录仍存在。

安装和回滚不修改 `desktop.ini`，不改动 Group3 中的其他项目。脚本修改 `.lnk` 的目标、参数、描述、图标和管理员标志；真实显示效果仍需打开当前系统菜单验证。

## 目标程序与系统兼容性

Windows Terminal 是终端宿主，PowerShell 7 是 shell。程序是否已安装、能否在该 OS 上运行、以及 WinX 是否仍使用上述链接，是分别需要检查的条件。

- 当前 [Terminal 官方 README](https://github.com/microsoft/terminal#installing-and-running-windows-terminal)要求 Windows 10 2004（build 19041）或更新版本。不要把它推广为所有 Windows Server 版本均支持；Server 2016/2019 应评估微软支持该系统的 PowerShell 7 版本，并在需要时使用 `--target pwsh`。
- PowerShell 版本受自身和 Windows 支持周期约束，具体组合查阅[微软支持周期](https://learn.microsoft.com/en-us/powershell/scripting/install/powershell-support-lifecycle)及[安装指南](https://learn.microsoft.com/en-us/powershell/scripting/install/install-powershell-on-windows)。本仓库不安装或升级 PowerShell。
- 自动模式优先使用 Terminal；同时发现 PowerShell 7 时，生成 `-w new new-tab` 加 `pwsh.exe` 完整路径的启动参数。这样不需要用户拥有某个固定名称的 Terminal 配置文件。只有 Terminal 时，使用其默认配置文件，不保证其为 PowerShell 7。
- `-w new` 用于指定新窗口；参数语义见 [Terminal 命令行文档](https://learn.microsoft.com/en-us/windows/terminal/command-line-arguments)。直接运行 PowerShell 时，承载窗口由系统默认终端配置决定。
- 非标准安装目录应使用 `--terminal-path` 或 `--pwsh-path`。发现一个路径仅证明候选文件存在，不证明该程序能在当前 OS 正常启动；需要实机启动验证。

默认终端应用程序与 WinX 链接目标是不同配置。[微软安装指南](https://learn.microsoft.com/en-us/windows/terminal/install#set-your-default-terminal-application)把默认终端设置列为所有 Windows 11，以及安装 KB5026435 后的 Windows 10 22H2 支持的功能。优先使用 Terminal“设置 → 启动”中的选项；不要将固定注册表委托 GUID 当作跨系统、跨安装版本的通用接口。

## WinX hash 与快捷方式标志

WinX 快捷方式处理参考 [Rafael Rivera 的 hashlnk 实现](https://github.com/riverar/hashlnk/blob/master/hashlnk.cpp)。这是对 WinX 行为的研究，不是微软承诺稳定的跨版本配置 API。

核心过程以快捷方式目标路径、参数和固定 salt 为输入，按已知文件夹规则归一化后计算 hash。修改目标或参数后，需要更新对应的 `PKEY_WINX_HASH` 属性。仅通过普通 COM 接口保存改写后的 `.lnk`，不足以证明 WinX 会接受它。

安装脚本在修改前，先根据**两份当前文件各自的目标和参数**重算 hash，并与文件内属性比较；两份都通过才继续。该检查用于发现当前文件与实现的不一致，不能证明文件一定来自微软，也不能替代实际 Explorer 验证。自校验失败时，检查系统版本、链接来源、路径及当前内容，不直接覆盖旧值继续安装。

`.lnk` 的 `LinkFlags` 包含 `RunAsUser` 标志，参见微软 [MS-SHLLINK LinkFlags](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-shllink/ae350202-3ba9-4790-9e9e-98935f4ee5af)。管理员项需要在保存及复验时保留对应标志；普通项不应因为修改而变成管理员项。该标志不能替代 Windows 的 UAC 策略，实际令牌及提示行为需在目标会话验证。

## 备份与失败恢复

默认目录为 `%LOCALAPPDATA%\winx-to-windows-terminal\backup`。每个备份集包含两份原始快捷方式和 `manifest.json`：

- 清单记录目标 Group3 路径及两份备份的 SHA256，防止把另一个用户目录的备份直接恢复过来，并检测文件损坏。
- SHA256 提供文件一致性校验；它不验证发布者身份，也不会使不明来源的备份变得可信。
- 首次备份在后续安装中保留。指定 `--backup-dir` 后，回滚需要指向同一备份集。
- 安装先校验全部现有文件，在临时副本中完成改写和复验，再替换两份目标文件。
- 回滚先验证整个备份集，再恢复清单中的两份文件；不枚举目录中其他 `.lnk` 或 `desktop.ini` 进行批量复制。
- 发生可捕获的替换错误时，脚本尝试恢复本次操作前的状态；若恢复本身失败，依据报错和现存文件处理，不把失败视为成功。

单个文件替换不等于两个文件组成的事务。断电、进程被强制终止等情况可能留下只更新其中一项的状态。不要同时运行安装和回滚；保留首次备份，重新检查两份链接后再选择恢复。

## 旧版备份迁移

旧版可能在技能的 `scripts/backup` 下存有 `.lnk` 或 `desktop.ini`，但没有新版所需的清单。新版不会自动导入或信任这些文件，也不会将缺失清单当作一个有效备份集。

1. 保留原来的 `scripts/backup`，核对其产生时间、原 Windows 用户和系统来源。
2. 需要从旧版恢复且已确认来源时，仅把两份原始 `01a - Windows PowerShell.lnk`、`02a - Windows PowerShell.lnk` 恢复到该用户原 Group3 目录。不要复制其他链接或 `desktop.ini`。
3. 恢复后重新执行新版安装预览；预览和 hash 自校验通过后，正式安装建立新版备份。不要为未知文件手工生成 `manifest.json` 来绕过来源检查。

若只剩修改后的文件，不能将其命名为“原厂备份”或宣称已经恢复。需要先取得来源明确、与当前用户及系统匹配的原始文件。

## 验证与排查

| 现象 | 检查方向 |
|---|---|
| 提示不是 Windows 或缺少 COM 依赖 | 确认使用 Windows 原生 Python 3.10+；用相同解释器执行 `python -m pip install pywin32`。回滚不依赖 COM |
| 缺少任意一个 PowerShell `.lnk` | 检查当前用户和 WinX 实际布局；不要创建空文件继续安装。有完整备份时可回滚 |
| 未发现程序或发现了错误版本 | 检查安装及应用执行别名，使用显式 EXE 完整路径，并验证程序能实际启动 |
| 原文件 hash 自校验失败 | 保留文件，核对链接来源和系统适用性；不要跳过校验 |
| 备份缺失、校验失败或目录不匹配 | 核对 `--backup-dir`、清单及用户目录；不要使用其他机器或用户的未知备份 |
| 文件写入成功但菜单尚未变化 | 保存 Explorer 操作后，在任务管理器重启当前用户的 Windows 资源管理器，再验证 |
| 菜单可见但程序未正常启动 | 单独检查目标 EXE、系统兼容性和启动参数，区分文件校验与运行时问题 |
| 普通项和管理员项都显示管理员身份 | 检查当前登录会话、已提升进程及 UAC 策略；不要通过关闭 UAC 修复 |

验证记录应区分：元数据/代码检查、备份及文件校验、真实 Windows 菜单和程序启动。模拟 COM 或文件系统的测试可以覆盖失败路径，但不能替代 Explorer 显示、UAC 和真实 Terminal 启动的实机结果。
