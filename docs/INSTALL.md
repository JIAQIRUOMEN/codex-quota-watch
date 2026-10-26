# 安装 Codex Quota Watch（Codex 额度重置检测）

需要 Python 3.10 或更新版本。Python CLI 只接收 JSON 快照或你配置的数据源命令，不负责登录 X 或抓取帖子。Skill 有另一条读取路线：宿主支持 browser 工具时，可复用浏览器会话读取 Tibo 主页和本人回复。

**安装不等于启用：**安装 Python 包或 Codex Skill 都不会自动轮询、开始监测或创建定时任务。要启用，请明确告诉 Codex：“启用额度监测”或“每3小时监测”。必须先能通过可用登录读取真实帖子，并成功建立静默基线；否则设置保持待完成。

从 GitHub 安装 Python 包或 Skill 都意味着信任仓库内容。安装前请检查源码和 Skill 指令；如需完整性校验，可用 `SHA256SUMS` 验证下载文件。哈希可以发现文件变化，但不能独立证明发布者身份。

## 两个下载包各自做什么

打开仓库的 [GitHub Releases](https://github.com/JIAQIRUOMEN/codex-quota-watch/releases)，按需下载一个或两个包：

- `codex-quota-watch-source.zip`：包含 Python 命令行工具、Windows 提醒窗口、示例和文档。要在本机运行轮询，需要安装这个包。
- `codex-quota-watch-skill.zip`：包含 Codex 指令、浏览器读取教程和只读 DOM 脚本；不含 Python CLI，也不会自行运行或定时。

`SHA256SUMS` 列出两个压缩包的 SHA-256。直接下载：[source ZIP](https://github.com/JIAQIRUOMEN/codex-quota-watch/releases/latest/download/codex-quota-watch-source.zip)、[Skill ZIP](https://github.com/JIAQIRUOMEN/codex-quota-watch/releases/latest/download/codex-quota-watch-skill.zip)。

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

Skill ZIP 中是一层目录、三个文件。解压后结构如下：

```text
codex-quota-watch/
├── SKILL.md
├── references/
│   └── browser-source.md
└── scripts/
    └── extract-posts.js
```

请直接解压到 Codex 的 skills 根目录，最终路径只应出现一次 `codex-quota-watch`。PowerShell 中 `$HOME` 默认为 Windows 用户目录，通常是 `C:\Users\你的用户名`。如果设置了自定义 `CODEX_HOME`，Codex 会使用它下面的 `skills` 子目录。

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
3. **明确要求启用。** 说“启用额度监测”或“每3小时监测”。使用默认浏览器路线时，只需选定实际本地状态目录，不必提供 source command；宿主没有 browser 工具时，才需要接入自己的来源命令或 JSON。要使用 CLI 时，可以明确请 Codex 代为安装 Python 包。
4. **验证真实、可刷新的数据。** Skill 默认尝试使用宿主 browser 工具打开 `https://x.com/thsottiaux` 与本人 Replies，再用只读 DOM 脚本提取可见正文、作者、时间和链接。浏览器路线只需选择实际状态目录，不必自己提供 source command。首次需要登录时，请你直接在浏览器登录一次，后续复用该会话；不要把密码或 Cookie 发给 Codex，也不承诺保存密码或 Cookie。示例 fixtures 和旧的静态 JSON 不算真实来源。登录失效、正文为空或浏览器无法访问时，设置保持待完成。若宿主没有 browser 工具，才需要你接入自己的数据源；没有真实可刷新的来源就保持待配置。
5. **建基线、安排并验证。** 首次成功读取会静默建立基线。宿主支持自动化时，Codex 先检查已有匹配任务，再为当前聊天创建或复用每三小时一次的 heartbeat，并使用已验证的来源和状态目录。没有宿主自动化工具时，只有已配置真实可刷新的来源命令才能运行前台 CLI 轮询，例如 `codex-quota-watch --state-dir STATE_DIR watch --source-command-json '["your-refreshable-source","--json"]' --interval 10800`；不要用 `--input` 指向静态快照来冒充定时读取。终端必须保持打开。不会安装后台服务、Windows 开机任务或自动运行脚本。

普通用户使用 Skill 的浏览器读取路线时，不需要自己制作 JSON。`skills/codex-quota-watch/scripts/extract-posts.js` 随 Skill ZIP 提供，依赖宿主的 browser 工具并只读可见 DOM；它不是 Python/pip 库内置的 X 抓取器，也不是云服务。CLI 单独使用时仍只接受 `--input` JSON 或 `--source-command-json` 命令。

### 常见问题

- **Codex 不认识 `$codex-quota-watch`：**确认 Skill 位于 `$HOME\.codex\skills\codex-quota-watch\SKILL.md`（自定义 `CODEX_HOME` 时位于其 `skills` 子目录），新开一个回合；仍无法识别就重启 Codex。
- **没有 browser 工具：**Skill 无法替你访问 X。请配置自己可用的来源命令或 JSON；没有真实、可刷新来源时监测会保持待配置。
- **X 显示未登录或要求登录：**请在打开的 X 浏览器窗口中自行登录，然后让 Skill 重试。不要把密码或导出的 Cookie 粘贴给 Codex。
- **正文为空或只有旧 JSON：**空正文表示本轮无法验证成功；旧 JSON 快照不能代替本轮来源刷新。若浏览器已真实刷新并读到可见帖子，即使没有新帖也属于成功读取，监测保持安静。
- **Skill ZIP 与 CLI 混淆：**Skill ZIP 只含指令和浏览器读取脚本，不含 Python CLI。要使用本地 `codex-quota-watch` 命令，需另装 source ZIP 或 pip 包；它本身不提供 X 抓取器。

更详细的浏览器操作与异常处理见 [Skill 浏览器来源教程](../skills/codex-quota-watch/references/browser-source.md)。

监测和 heartbeat 需要本机可用。关闭应用、网络中断、电脑休眠或离线都会延迟检查；这不是全天候云端监控。工具不能发送桌宠消息或切换正在运行的 Codex 模型。

Windows 弹窗由包内 PowerShell/WPF 程序显示。`displayed` 表示窗口已呈现，不代表用户已确认；只有点击确认按钮或执行 `ack ID` 才会清除提醒。关闭窗口、成功启动进程都不算确认。回执会在下一次轮询时同步。

## 可选：北京时间每日暂停

CLI 默认值是 `confirmed` 和 UTC+08:00（480 分钟）。先查看当前值：

```powershell
codex-quota-watch --state-dir .\codex-quota-watch-state settings
```

由用户决定并只执行一种策略：

```powershell
# 明确报告已完成后暂停当天抓取（默认）
codex-quota-watch --state-dir .\codex-quota-watch-state settings --daily-pause confirmed --utc-offset-minutes 480

# 当天出现重置公告就暂停抓取
codex-quota-watch --state-dir .\codex-quota-watch-state settings --daily-pause announcement --utc-offset-minutes 480

# 关闭每日暂停
codex-quota-watch --state-dir .\codex-quota-watch-state settings --daily-pause off --utc-offset-minutes 480
```

触发条件是：本轮成功读取并首次识别到非基线事件、来源时间明确属于北京时间当天、且 CLI 阶段符合所选策略。`confirmed` 只匹配 `confirmed` 阶段；`announcement` 匹配 `announcement` 或 `confirmed` 阶段。旧帖、静默基线和未知/缺失的原帖时间不触发。这里按原帖时间判断，不把浏览器人工核验的上下文推断为 CLI `confirmed`；例如“today is a reset”仍须以 CLI 明确阶段为准。

`announcement` 会在公告后立即暂停，可能错过当天稍后的作者确认，也可能延迟模型切换判定；`confirmed` 保留当天后续确认的观察机会；`off` 不暂停抓取。“一天一次”仅是减少本地来源调用的策略，不是官方重置周期或服务保证。模式更改会清除当前每日 gate，但保留已有提醒记录。

监测每三小时的心跳继续按原安排运行。每次对 X、browser 或来源命令操作前，CLI `gate` 先检查本地状态；返回 `should_fetch=false` 时，不访问来源、不生成快照、不更新 `monitor.json` 中的来源成功时间或基线，而只运行：

```powershell
codex-quota-watch --state-dir .\codex-quota-watch-state tick
```

`tick` 仅重试已有待确认提醒并同步回执，不抓取、不创建新提醒。`gate` 本身也不安排定时器；它返回的 `resume_at` 是次日北京时间午夜的 UTC 表示。到达午夜后，实际抓取在下一次原定心跳恢复，而不是午夜立即运行。心跳仍会唤醒并可能消耗宿主/模型资源；此策略省去的是 browser 和来源调用，不承诺零成本。
