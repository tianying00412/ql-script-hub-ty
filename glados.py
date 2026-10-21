#!/usr/bin/env python3
"""
GLaDOS Cloud 自动签到脚本（修正版）

与原版的区别：
  1. code=-2 时明确提示 Cookie 失效，并以失败状态退出
     （原版会继续跑完并显示“完成”，青龙面板看不出失败）
  2. 启动时校验 Cookie 格式：必须同时包含 koa:sess 和 koa:sess.sig，
     并自动去掉误粘的 "cookie:" 前缀
  3. code=4 / device-mismatch 时，读取服务端返回的 loginDevice，
     自动切换对应平台的 User-Agent 重试一次
     （原版写死了 macOS 的 UA，从 Windows 浏览器取的 Cookie 容易对不上）

用法（青龙面板）：
  环境变量名必须一字不差：GLADOS_COOKIE
  值只填 Cookie 本身，格式参考：
    koa:sess=xxxx; koa:sess.sig=xxxx;
  可选环境变量 GLADOS_PLATFORM：Windows / macOS / Linux / Android / iPhone
  不填默认 Windows（即您取 Cookie 的那个浏览器的平台）
"""

import os
import sys
import requests
from datetime import datetime, timezone

BASE_URL = "https://glados.cloud"

PLATFORM_UA = {
    "Windows": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "macOS": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Linux": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Android": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "iPhone": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
}


def log(msg, level="INFO"):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{now}] [{level}] {msg}")


def clean_cookie(raw):
    cookie = (raw or "").strip()
    # 误把 "cookie:" 这一行前缀一起粘进来时自动去掉
    if cookie.lower().startswith("cookie:"):
        cookie = cookie.split(":", 1)[1].strip()
    return cookie


def platform_from_device(device):
    d = str(device or "").lower()
    if "win" in d:
        return "Windows"
    if "mac" in d or "darwin" in d:
        return "macOS"
    if "android" in d:
        return "Android"
    if "iphone" in d or "ios" in d:
        return "iPhone"
    if "linux" in d:
        return "Linux"
    return None


def make_session(cookie, platform):
    session = requests.Session()
    session.headers.update({
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9",
        "content-type": "application/json;charset=UTF-8",
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/console/checkin",
        "user-agent": PLATFORM_UA[platform],
        "cookie": cookie,
    })
    return session


def do_checkin(session):
    resp = session.post(
        f"{BASE_URL}/api/user/checkin",
        json={"token": "glados.cloud"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    cookie = clean_cookie(os.environ.get("GLADOS_COOKIE", ""))
    if not cookie or cookie == "你的Cookie粘贴到这里":
        log("未配置 GLADOS_COOKIE 环境变量，或仍是占位文字", "ERROR")
        sys.exit(1)
    if "koa:sess=" not in cookie:
        log("Cookie 里没有 koa:sess，应该是复制不完整，请从 Network 请求头里整行复制 Cookie", "ERROR")
        sys.exit(1)
    if "koa:sess.sig=" not in cookie:
        log("Cookie 里没有 koa:sess.sig，应该是复制不完整，请从 Network 请求头里整行复制 Cookie", "ERROR")
        sys.exit(1)

    platform = os.environ.get("GLADOS_PLATFORM", "Windows")
    if platform not in PLATFORM_UA:
        log(f"GLADOS_PLATFORM={platform} 不认识，改用 Windows", "WARN")
        platform = "Windows"

    session = make_session(cookie, platform)

    log(f"正在发送签到请求...（平台 UA: {platform}）")
    try:
        result = do_checkin(session)
    except requests.RequestException as e:
        log(f"签到请求失败: {e}", "ERROR")
        sys.exit(1)

    # 设备平台不匹配：按服务端返回的 loginDevice 换 UA 重试一次
    if result.get("code") == 4 and result.get("reason") == "device-mismatch":
        device = result.get("loginDevice") or (result.get("data") or {}).get("loginDevice")
        new_platform = platform_from_device(device)
        log(f"设备平台不匹配，服务端记录的登录设备: {device}", "WARN")
        if new_platform and new_platform != platform:
            log(f"切换为 {new_platform} 的 UA 重试...")
            session = make_session(cookie, new_platform)
            try:
                result = do_checkin(session)
            except requests.RequestException as e:
                log(f"重试请求失败: {e}", "ERROR")
                sys.exit(1)

    code = result.get("code")
    message = result.get("message", "")

    if code == 0:
        log(f"签到成功！{message}（本次 +{result.get('points', 0)} 积分）")
    elif code == 1:
        log(f"今天已签到：{message}（code=1）")
    elif code == -2:
        log("没有权限（code=-2）：Cookie 已失效或登录态已过期。"
            "请重新登录 glados.cloud，手动签到一次，再刷新 Cookie 并更新青龙的 GLADOS_COOKIE 后重试", "ERROR")
        sys.exit(1)
    elif code == 4:
        log(f"服务端拒绝签到（code=4, reason={result.get('reason')}），请检查账户风控状态", "ERROR")
        sys.exit(1)
    else:
        log(f"签到响应：{message}（code={code}）", "WARN")
        sys.exit(1)

    # 查询账户状态
    try:
        resp = session.get(f"{BASE_URL}/api/user/status", timeout=15)
        resp.raise_for_status()
        status = resp.json()
        if status.get("code") not in (0, None):
            log(f"状态接口返回 code={status.get('code')}：{status.get('message', '')}，登录态可能有问题", "WARN")
        data = status.get("data") or {}
        log(f"账户: {data.get('email', 'N/A')} | VIP={data.get('vip', 'N/A')} | 剩余天数={data.get('leftDays', 'N/A')}")
    except requests.RequestException as e:
        log(f"查询账户状态失败: {e}", "WARN")

    log("完成。")


if __name__ == "__main__":
    main()
