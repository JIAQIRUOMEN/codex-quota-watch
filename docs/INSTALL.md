# 安装 Codex Quota Watch（Codex 额度重置检测）

需要 Python 3.10 或更新版本。运行时只使用 Python 标准库。工具不包含 X 登录或内置抓取器；请提供 JSON 快照，或配置你信任的数据源命令。

**安装不等于启用：**安装 Python 包或 Codex Skill 都不会自动轮询、开始监测或创建定时任务。要启用，请明确告诉 Codex：“启用额度监测”或“每3小时监测”。必须先能通过可用登录读取真实帖子，并成功建立静默基线；否则设置保持待完成。

从 GitHub 安装 Python 包或 Skill 都意味着信任仓库内容。安装前请检查源码和 Skill 指令；如需完整性校验，可用 `SHA256SUMS` 验证下载文件。哈希可以发现文件变化，但不能独立证明发布者身份。

## 两个下载包各自做什么

打开仓库的 [GitHub Releases](https://github.com/JIAQIRUOMEN/codex-quota-watch/releases)，按需下载一个或两个包：

- `codex-quota-watch-source.zip`：包含 Python 命令行工具、Windows 提醒窗口、示例和文档。要在本机运行轮询，需要安装这个包。
- `codex-quota-watch-skill.zip`：只包含 Codex 使用的 `SKILL.md` 指令，可让 Codex 协助配置；不含 Python 程序，也不会自行运行或定时。

`SHA256SUMS` 列出两个压缩包的 SHA-256。直接下载：[source ZIP](https://github.com/JIAQIRUOMEN/codex-quota-watch/releases/latest/download/codex-quota-watch-source.zip)、[Skill ZIP](https://github.com/JIAQIRUOMEN/codex-quota-watch/releases/latest/download/codex-quota-watch-skill.zip)。只有发布了包含这些附件的 Release 后，链接才可下载。

## Install the Python package

下载 source ZIP 后解压，进入其中包含 `pyproject.toml` 的 `codex-quota-watch` 目录，再运行：

```powershell
Expand-Archive .\codex-quota-watch-source.zip -DestinationPath .\codex-quota-watch-source
Set-Location .\codex-quota-watch-source\codex-quota-watch
python -m pip install .
codex-quota-watch --help
```

也可以从 GitHub 安装（需要已安装 Git）：

```powershell
python -m pip install "git+https://github.com/JIAQIRUOMEN/codex-quota-watch.git"
codex-quota-watch --help
```

从本地源码安装时，在仓库根目录运行 `python -m pip install .`。也可以用 `python -m codex_quota_watch` 调用命令行工具。

## Install the Skill ZIP on Windows

Skill ZIP 中只有一层目录和一个文件：`codex-quota-watch/SKILL.md`。请直接解压到 Codex 的 skills 根目录，最终路径只应出现一次 `codex-quota-watch`。PowerShell 中 `$HOME` 默认为 Windows 用户目录，通常是 `C:\Users\你的用户名`。如果设置了自定义 `CODEX_HOME`，Codex 会使用它下面的 `skills` 子目录。

```powershell
$skillRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $HOME '.codex\skills' }
New-Item -ItemType Directory -Force -Path $skillRoot | Out-Null
Expand-Archive -LiteralPath .\codex-quota-watch-skill.zip -DestinationPath $skillRoot -Force
Get-Content (Join-Path $skillRoot 'codex-quota-watch\SKILL.md') -TotalCount 12
```

默认会得到 `$HOME\.codex\skills\codex-quota-watch\SKILL.md`；自定义 `CODEX_HOME` 时，路径为 `$env:CODEX_HOME\skills\codex-quota-watch\SKILL.md`。不要再套一层同名目录，否则 Codex 找不到 Skill。Skill ZIP 不含 Python 代码；如果要让 Codex 运行监测命令行工具，还需单独安装 Python 包。你可以在明确要求 Codex 帮你设置时，让它代为安装。

安装 Skill 后，新开一个 Codex 回合并调用 `$codex-quota-watch`。如果 Codex 不认识这个名称，请重启 Codex 后再试。

也可以使用 [skills CLI](https://www.skills.sh/docs/cli) 直接从 GitHub 安装：

```powershell
npx skills add JIAQIRUOMEN/codex-quota-watch
```

如果 CLI 提示选择 Skill，请选 `codex-quota-watch`，然后新开一个 Codex 回合。此方式只安装指令，不会安装 Python 包或启动监测。

## Verify and initialize

```powershell
codex-quota-watch --help
codex-quota-watch --state-dir .\codex-quota-watch-state init
codex-quota-watch --state-dir .\codex-quota-watch-state status
```

状态、SQLite 数据库、事件文件和回执保存在所选目录。真实数据请使用本地私有目录。只做 JSON 验证时，运行 `poll --input FILE --dry-run`；source ZIP 中的 fixtures 都是合成样例。首次轮询会建立静默基线。

## First-run activation: from installation to recurring checks

1. **分别安装。** 要运行命令行工具，安装 Python source 包；要让 Codex 协助配置，再单独安装 Skill。Skill ZIP 不含 Python 包；两个压缩包都不会自动运行或定时。
2. **新开回合并调用 Skill。** 在新的 Codex 回合输入 `$codex-quota-watch`。若名称未识别，请重启 Codex 后再试。没有监测意图时，Skill 会问你只做一次测试还是启用定时监测。
3. **明确要求启用。** 说“启用额度监测”或“每3小时监测”，并提供实际来源命令/路径及本地状态目录。要使用 CLI 时，可以明确请 Codex 代为安装 Python 包。
4. **验证真实、可刷新的数据。** 确认来源能用可访问的登录读取目标账号真实帖子。示例 fixtures 和未变化的静态文件不算。来源、登录或 Python 环境不可用时，设置保持待完成；不会声称监测或定时自动化已启用。
5. **建基线、安排并验证。** 首次成功读取会静默建立基线。宿主支持自动化时，Codex 先检查已有匹配任务，再为当前聊天创建或复用每三小时一次的 heartbeat，并使用已验证的来源和状态目录。没有宿主自动化工具时，可在保持打开的终端运行前台 `watch --interval 10800`。不会安装后台服务、Windows 开机任务或自动运行脚本。

监测和 heartbeat 需要本机可用。关闭应用、网络中断、电脑休眠或离线都会延迟检查；这不是全天候云端监控。工具不能发送桌宠消息或切换正在运行的 Codex 模型。

Windows 弹窗由包内 PowerShell/WPF 程序显示。`displayed` 表示窗口已呈现，不代表用户已确认；只有点击确认按钮或执行 `ack ID` 才会清除提醒。关闭窗口、成功启动进程都不算确认。回执会在下一次轮询时同步。
