# workbuddy-daily-checkin

WorkBuddy 每日签到自动化脚本。纯 Python 标准库，零依赖，Windows / macOS / Linux 通用。

每天自动领取 100 积分，不打开客户端、不模拟点击、不消耗 AI 会话额度。

---

## ⚠️ 先看这段

- 本项目通过读取**本地已登录的会话文件**调用官方签到接口，属于非官方自动化。
- 多数平台的用户协议不鼓励自动化行为。日常签到风险通常很低，但**账号被风控的可能性由使用者自行承担**。
- 本项目**只做每日签到**。不包含、也不欢迎任何刷量、多账号、代抢、绕过付费的功能。
- 作者与 WorkBuddy / 腾讯官方无任何关联。

如果你不接受以上风险，请不要使用。

---

## 原理

WorkBuddy 桌面端登录后，会把会话（含 `accessToken`、`uid`）写入本地文件。脚本每次运行时**现读现用**，直接调用两个官方接口：

| 用途 | 接口 |
| --- | --- |
| 查询今日状态 | `POST /v2/billing/meter/checkin-activity-status` |
| 领取签到 | `POST /v2/billing/meter/daily-checkin` |

鉴权头：`Authorization: Bearer <accessToken>` + `X-User-Id: <uid>`。

脚本**只读**会话文件，不修改、不复制、不外传，也不保存任何密码。

### 会话文件默认位置

| 系统 | 路径 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\*.info` |
| macOS | `~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/*.info` |
| Linux | `~/.config/CodeBuddyExtension/Data/Public/auth/*.info` |

有多个 `.info` 时取最近修改的那个；也可用环境变量 `WB_CHECKIN_SESSION_FILE` 直接指定。

---

## 快速开始

```bash
# 1. 确认你已在 WorkBuddy 桌面端登录过（只需一次）

# 2. 只查询，不领取，验证能否读到会话
python3 wb_checkin.py --dry-run --verbose

# 3. 正式签到
python3 wb_checkin.py
```

参数：

- `--dry-run` 只查状态，不领取
- `--verbose` 打印接口原始返回，排错用

退出码：`0` 成功或今日已领取，`1` 失败。

需要 Python 3.8+，无第三方依赖。

---

## 设置每天自动运行

### Windows（计划任务）

以当前用户身份在 PowerShell 中执行，把两个路径换成你自己的：

```powershell
$py     = "C:\path\to\python.exe"
$script = "C:\path\to\wb_checkin.py"

$action   = New-ScheduledTaskAction -Execute $py -Argument "`"$script`"" -WorkingDirectory (Split-Path $script)
$trigger  = New-ScheduledTaskTrigger -Daily -At 09:00
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName "WorkBuddyDailyCheckin" `
  -Action $action -Trigger $trigger -Settings $settings `
  -Description "WorkBuddy daily check-in" -Force
```

`StartWhenAvailable` 保证关机错过后开机补跑。

常用管理命令：

```powershell
Disable-ScheduledTask -TaskName "WorkBuddyDailyCheckin"     # 暂停
Enable-ScheduledTask  -TaskName "WorkBuddyDailyCheckin"     # 恢复
Unregister-ScheduledTask -TaskName "WorkBuddyDailyCheckin" -Confirm:$false   # 删除
```

### macOS / Linux（cron）

```bash
# 每天 9:00，日志追加到 checkin.log
0 9 * * * /usr/bin/python3 /path/to/wb_checkin.py >> /path/to/checkin.log 2>&1
```

---

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `WB_CHECKIN_SESSION_FILE` | 直接指定会话文件路径 |
| `WB_CHECKIN_ENDPOINT` | 接口地址，默认 `https://copilot.tencent.com` |
| `WB_CHECKIN_LOG` | 日志文件路径，默认脚本同目录 `wb_checkin.log` |
| `WB_CHECKIN_HISTORY` | 历史记录路径，默认脚本同目录 `wb_checkin_history.jsonl` |

---

## 常见问题

**Q：重复运行会重复领积分吗？**
不会。脚本先查后领，今日已领取会直接跳过。

**Q：token 过期了怎么办？**
有效期约 55 天。过期后脚本会在日志里提示，打开一次 WorkBuddy 桌面端让它自动刷新即可，无需改配置。脚本**故意不做自动刷新**，因为会轮换掉桌面端的 refresh token，可能把你踢下线。

**Q：请求一直超时？**
脚本内置四级降级：`urllib+代理 → urllib+直连 → curl+代理 → curl+直连`，会自动挑能通的那条。仍失败时用 `--verbose` 看具体报错。两种已知环境坑：某些网络下 TLS 1.3 握手会被中间设备掐断（脚本已统一降到 TLS 1.2）；请求头带大 JWT 时直连可能被断连（走代理反而通）。

**Q：会消耗我的积分吗？**
不会。脚本直接调接口，不启动 AI 会话。

---

## 开发

```bash
python3 wb_checkin.py --dry-run --verbose   # 调试
```

代码单文件、无依赖，改动请保持这个特点。提交时不要带上 `wb_checkin.log` 和 `wb_checkin_history.jsonl`（已在 `.gitignore` 中）。

---

## 许可

MIT License。详见 [LICENSE](LICENSE)。
