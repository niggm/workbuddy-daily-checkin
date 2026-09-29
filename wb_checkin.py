#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 每日签到脚本

原理：
  WorkBuddy 桌面端登录后的会话保存在本地文件中，脚本读取其中的
  accessToken + uid，直接调用官方签到接口完成领取：

      POST {endpoint}/v2/billing/meter/checkin-activity-status   查询今日状态
      POST {endpoint}/v2/billing/meter/daily-checkin              领取签到

  不模拟点击、不碰 UI、不修改会话文件、不自动刷新 token。

会话文件默认位置：
  Windows : %LOCALAPPDATA%\\CodeBuddyExtension\\Data\\Public\\auth\\*.info
  macOS   : ~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/*.info
  Linux   : ~/.config/CodeBuddyExtension/Data/Public/auth/*.info
  也可用环境变量 WB_CHECKIN_SESSION_FILE 直接指定文件。

网络：
  依次尝试「urllib 走代理 → urllib 直连 → curl 走代理 → curl 直连」，
  哪个通就用哪个，环境变了也不会挂。

用法：
  python wb_checkin.py              # 正常签到（今日已领则跳过）
  python wb_checkin.py --dry-run    # 只查状态，不领取
  python wb_checkin.py --verbose    # 打印接口原始返回

退出码：0 成功或今日已领取；1 失败
"""

import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------- 配置

ENDPOINT = os.environ.get("WB_CHECKIN_ENDPOINT", "https://copilot.tencent.com").rstrip("/")
STATUS_PATH = "/v2/billing/meter/checkin-activity-status"
CLAIM_PATH = "/v2/billing/meter/daily-checkin"

SESSION_DIRS = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "CodeBuddyExtension", "Data", "Public", "auth"),
    os.path.expanduser("~/Library/Application Support/CodeBuddyExtension/Data/Public/auth"),
    os.path.expanduser("~/.config/CodeBuddyExtension/Data/Public/auth"),
    os.path.join(os.path.expanduser("~"), ".workbuddy", "auth"),
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.environ.get("WB_CHECKIN_LOG", os.path.join(SCRIPT_DIR, "wb_checkin.log"))
HISTORY_FILE = os.environ.get("WB_CHECKIN_HISTORY", os.path.join(SCRIPT_DIR, "wb_checkin_history.jsonl"))

TIMEOUT = 20


# ---------------------------------------------------------------- 基础工具

def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def mask_token(t):
    return (t[:6] + "..." + t[-4:]) if t and len(t) > 12 else "***"


def find_session_file():
    override = os.environ.get("WB_CHECKIN_SESSION_FILE")
    if override and os.path.isfile(override):
        return override
    best, best_mtime = None, -1
    for d in SESSION_DIRS:
        if not d or not os.path.isdir(d):
            continue
        try:
            names = os.listdir(d)
        except Exception:
            continue
        for name in names:
            if not name.endswith(".info"):
                continue
            p = os.path.join(d, name)
            if not os.path.isfile(p):
                continue
            mtime = os.path.getmtime(p)
            if mtime > best_mtime:
                best, best_mtime = p, mtime
    return best


def load_session(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    account = data.get("account") or {}
    auth = data.get("auth") or {}
    token, uid = auth.get("accessToken"), account.get("uid")
    if not token or not uid:
        raise RuntimeError("会话文件缺少 accessToken 或 uid，请先在 WorkBuddy 中登录")
    return {
        "token": token,
        "uid": uid,
        "nickname": account.get("nickname", ""),
        "expires_at": auth.get("expiresAt", 0),
    }


def write_history(record):
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- 网络层

def _ssl_context():
    """部分网络环境下 TLS1.3 握手会被中间设备掐断，统一降到 TLS1.2。"""
    ctx = ssl.create_default_context()
    try:
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    except Exception:
        pass
    return ctx


def _build_headers(session):
    return {
        "Authorization": "Bearer %s" % session["token"],
        "X-User-Id": session["uid"],
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "workbuddy-daily-checkin/1.0",
    }


def _urllib_post(path, session, use_proxy):
    req = urllib.request.Request(
        ENDPOINT + path,
        data=b"{}",
        method="POST",
        headers=_build_headers(session),
    )
    proxy = urllib.request.ProxyHandler() if use_proxy else urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ssl_context()), proxy)
    with opener.open(req, timeout=TIMEOUT) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _curl_post(path, session, use_proxy):
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if not curl:
        raise RuntimeError("curl 不可用")
    cmd = [
        curl, "-sS", "-m", str(TIMEOUT), "-X", "POST", ENDPOINT + path,
        "-H", "Authorization: Bearer %s" % session["token"],
        "-H", "X-User-Id: %s" % session["uid"],
        "-H", "Content-Type: application/json",
        "-d", "{}",
    ]
    if not use_proxy:
        cmd += ["--noproxy", "*"]
    proc = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT + 15)
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    if not out:
        raise RuntimeError("curl 无输出: %s" % proc.stderr.decode("utf-8", errors="replace")[:200])
    return json.loads(out)


def http_post(path, session, verbose=False):
    """多通道尝试：urllib 代理 → urllib 直连 → curl 代理 → curl 直连。"""
    last_err = None
    for name, fn, use_proxy in (
        ("urllib+proxy", _urllib_post, True),
        ("urllib+direct", _urllib_post, False),
        ("curl+proxy", _curl_post, True),
        ("curl+direct", _curl_post, False),
    ):
        try:
            result = fn(path, session, use_proxy)
            if verbose:
                log("通道 %s 成功" % name)
            return result
        except Exception as e:  # noqa: BLE001
            last_err = e
            if verbose:
                log("通道 %s 失败：%s" % (name, str(e)[:120]))
            time.sleep(0.5)
    raise last_err


# ---------------------------------------------------------------- 主流程

def main():
    dry_run = "--dry-run" in sys.argv
    verbose = "--verbose" in sys.argv

    path = find_session_file()
    if not path:
        log("失败：找不到登录会话文件，请确认已在 WorkBuddy 桌面端登录，"
            "或用环境变量 WB_CHECKIN_SESSION_FILE 指定路径")
        return 1
    try:
        session = load_session(path)
    except Exception as e:
        log("失败：读取会话出错 - %s" % e)
        return 1

    log("账号 uid=%s 昵称=%s token=%s" % (session["uid"], session["nickname"], mask_token(session["token"])))

    if session["expires_at"] and session["expires_at"] * 1000 < time.time() * 1000:
        log("提示：accessToken 已过期，请打开一次 WorkBuddy 让它自动刷新后再运行本脚本")

    try:
        status_resp = http_post(STATUS_PATH, session, verbose)
    except Exception as e:
        log("失败：查询签到状态 - %s" % e)
        return 1

    if verbose:
        log("status 原始返回: %s" % json.dumps(status_resp, ensure_ascii=False)[:1500])

    if status_resp.get("code") not in (0, None):
        log("失败：查询状态返回 code=%s msg=%s" % (status_resp.get("code"), status_resp.get("msg")))
        return 1

    status = status_resp.get("data") or {}
    today_checked = status.get("today_checked_in")
    credit = status.get("today_credit", status.get("daily_credit"))
    streak = status.get("streak_days")
    log("状态：今日已签到=%s 今日积分=%s 连续天数=%s 活动=%s"
        % (today_checked, credit, streak, status.get("activity_name", "")))

    if dry_run:
        log("--dry-run：只查询，不领取")
        return 0

    if today_checked:
        log("今日已领取过签到，跳过")
        write_history({"time": datetime.now().isoformat(timespec="seconds"),
                       "result": "already", "credit": credit, "streak": streak})
        return 0

    try:
        claim_resp = http_post(CLAIM_PATH, session, verbose)
    except Exception as e:
        log("失败：领取签到 - %s" % e)
        return 1

    if verbose:
        log("claim 原始返回: %s" % json.dumps(claim_resp, ensure_ascii=False)[:1500])

    data = claim_resp.get("data") or {}
    ok = claim_resp.get("code") == 0 and not (isinstance(data, dict) and data.get("code") and "credit" not in data)

    if ok:
        got = data.get("credit") or credit
        log("签到成功：+%s 积分，连续 %s 天" % (got, data.get("streak_days") or streak))
        write_history({"time": datetime.now().isoformat(timespec="seconds"),
                       "result": "claimed", "credit": got,
                       "streak": data.get("streak_days") or streak})
        return 0

    log("签到未成功，接口返回：%s" % json.dumps(claim_resp, ensure_ascii=False)[:600])
    write_history({"time": datetime.now().isoformat(timespec="seconds"),
                   "result": "failed", "raw": claim_resp})
    return 1


if __name__ == "__main__":
    sys.exit(main())
