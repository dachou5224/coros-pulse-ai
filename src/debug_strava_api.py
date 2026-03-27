"""
一次性探测 Strava API 原始 HTTP 响应，用于排查 597 / 非标准状态码。
仅依赖 requests + python-dotenv（无需安装 stravalib）。

在项目根目录执行（把下面路径换成你机器上的真实目录）：
  cd /root/coros-pulse-ai
  python3 -m pip install -q requests python-dotenv
  python3 src/debug_strava_api.py

.env 需包含：STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET / STRAVA_REFRESH_TOKEN
输出不含 access_token；请勿把完整响应发到公开处。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _refresh_access_token() -> Optional[str]:
    cid = os.getenv("STRAVA_CLIENT_ID")
    secret = os.getenv("STRAVA_CLIENT_SECRET")
    refresh = os.getenv("STRAVA_REFRESH_TOKEN")
    if not all([cid, secret, refresh]):
        print("❌ 请配置 STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET / STRAVA_REFRESH_TOKEN")
        return None
    r = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": cid,
            "client_secret": secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        },
        timeout=60,
    )
    if not r.ok:
        print(f"❌ oauth/token 失败: HTTP {r.status_code} {r.reason!r}")
        print((r.text or "")[:800])
        return None
    try:
        data = r.json()
    except json.JSONDecodeError:
        print("❌ oauth/token 返回非 JSON")
        print((r.text or "")[:800])
        return None
    token = data.get("access_token")
    if not token:
        print("❌ 响应中无 access_token")
        return None
    return str(token)


def main() -> int:
    access = _refresh_access_token()
    if not access:
        return 1

    url = "https://www.strava.com/api/v3/athlete/activities"
    params = {"page": 1, "per_page": 1}
    headers = {"Authorization": f"Bearer {access}"}

    print("📡 GET", url, params)
    try:
        r = requests.get(url, params=params, headers=headers, timeout=60)
    except requests.RequestException as e:
        print(f"❌ 请求异常（未收到完整 HTTP 响应）: {e}")
        return 1

    print(f"   状态码: {r.status_code} {r.reason!r}")
    print(f"   Content-Type: {r.headers.get('Content-Type', '(无)')}")
    rl = [
        r.headers.get("X-RateLimit-Limit"),
        r.headers.get("X-RateLimit-Usage"),
        r.headers.get("X-RateLimit-Reset"),
    ]
    if any(rl):
        print(f"   RateLimit: limit={rl[0]} usage={rl[1]} reset={rl[2]}")
    else:
        print("   RateLimit 头: （无，错误页或非 API 响应时常如此）")

    body = r.text or ""
    snippet = body.strip()[:1200]
    print(f"   正文长度: {len(body)} 字符")
    print("   正文片段:")
    print("---")
    print(snippet if snippet else "(空)")
    print("---")

    if r.ok:
        try:
            data = r.json()
            print(f"   JSON: 数组长度 {len(data) if isinstance(data, list) else type(data).__name__}")
        except json.JSONDecodeError:
            print("   ⚠️ 状态为 2xx 但正文不是 JSON")
        print("✅ 探测正常")
        return 0

    print("❌ 非成功状态。若此处已是 597，多为链路中间层；若 401 请重授权。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
