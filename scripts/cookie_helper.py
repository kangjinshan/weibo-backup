#!/usr/bin/env python3
"""Local loopback helper for reading Weibo cookies from desktop Chrome."""

from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional
from urllib import request as urllib_request
from urllib.parse import parse_qs, urlparse


HOST = os.environ.get("WEIBO_COOKIE_HELPER_HOST", "127.0.0.1")
PORT = int(os.environ.get("WEIBO_COOKIE_HELPER_PORT", "8766"))
DEFAULT_USER_ID = os.environ.get("WEIBO_COOKIE_HELPER_USER_ID", "1639733600")
COOKIE_CHECK_TIMEOUT = int(os.environ.get("WEIBO_COOKIE_HELPER_TIMEOUT", "10"))
CHROME_COOKIE_DOMAINS = tuple(
    domain.strip()
    for domain in os.environ.get("WEIBO_COOKIE_HELPER_DOMAINS", "weibo.cn,weibo.com").split(",")
    if domain.strip()
)
DEFAULT_ALLOWED_ORIGINS = (
    "https://weibo.jinshanweb.com:8765",
    "http://127.0.0.1:8765",
    "http://localhost:8765",
    "https://127.0.0.1:8765",
    "https://localhost:8765",
)


def configured_allowed_origins() -> set[str]:
    raw = os.environ.get("WEIBO_COOKIE_HELPER_ALLOWED_ORIGINS")
    if not raw:
        return set(DEFAULT_ALLOWED_ORIGINS)
    return {origin.strip() for origin in raw.split(",") if origin.strip()}


def is_allowed_origin(origin: Optional[str], allowed_origins: Optional[set[str]] = None) -> bool:
    if not origin:
        return True
    return origin in (allowed_origins or configured_allowed_origins())


def sanitize_user_id(user_id: str) -> str:
    value = str(user_id or "").strip()
    if re.fullmatch(r"\d{5,20}", value):
        return value
    return DEFAULT_USER_ID


def decode_html_text(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(encoding)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def html_title(text: str) -> str:
    match = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def read_chrome_cookie_string() -> tuple[Optional[str], Optional[str]]:
    try:
        import browser_cookie3
    except Exception as exc:
        return None, f"browser_cookie3 不可用：{exc}"

    cookie_map: dict[str, str] = {}
    errors: list[str] = []
    for domain_name in CHROME_COOKIE_DOMAINS:
        try:
            cookie_jar = browser_cookie3.chrome(domain_name=domain_name)
            for cookie in cookie_jar:
                cookie_map[cookie.name] = cookie.value
        except Exception as exc:
            errors.append(f"{domain_name}: {exc}")

    if not cookie_map:
        detail = f"（{'; '.join(errors)}）" if errors else ""
        return None, f"Chrome 中未读取到微博 Cookie{detail}"
    return "; ".join(f"{name}={value}" for name, value in cookie_map.items()), None


def inspect_cookie_health(cookie: str, probe_url: str) -> dict:
    if not cookie:
        return {
            "state": "missing",
            "valid": False,
            "message": "Cookie 未配置",
            "probe_url": probe_url,
        }

    request = urllib_request.Request(
        probe_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Cookie": cookie,
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=COOKIE_CHECK_TIMEOUT) as response:
            final_url = response.geturl()
            text = decode_html_text(response.read(40_000))
            title = html_title(text)
    except Exception as exc:
        return {
            "state": "unknown",
            "valid": None,
            "message": f"Cookie 状态检测失败：{exc}",
            "probe_url": probe_url,
        }

    redirect_login = any(flag in final_url.lower() for flag in ("login", "passport"))
    title_login = any(flag in title for flag in ("登录", "通行证", "新浪"))
    has_profile_info = "基本信息" in text or "资料" in title
    valid = (not redirect_login) and (not title_login) and has_profile_info
    return {
        "state": "valid" if valid else "expired",
        "valid": valid,
        "message": "Cookie 有效" if valid else "Cookie 疑似已过期，请重新登录微博后重试",
        "probe_url": probe_url,
        "title": title,
    }


def build_cookie_payload(
    user_id: str,
    cookie_reader: Callable[[], tuple[Optional[str], Optional[str]]] = read_chrome_cookie_string,
    cookie_inspector: Callable[[str, str], dict] = inspect_cookie_health,
) -> tuple[dict, int]:
    clean_user_id = sanitize_user_id(user_id)
    probe_url = f"https://weibo.cn/{clean_user_id}/info"
    cookie, read_error = cookie_reader()
    if not cookie:
        return {
            "ok": False,
            "message": read_error or "未找到微博 Cookie",
            "cookie_status": {
                "state": "missing",
                "valid": False,
                "message": read_error or "未找到微博 Cookie",
                "probe_url": probe_url,
            },
        }, 400

    cookie_status = cookie_inspector(cookie, probe_url)
    if cookie_status.get("valid") is not True:
        return {
            "ok": False,
            "message": cookie_status.get("message") or "未找到有效 Cookie",
            "cookie_status": cookie_status,
        }, 400

    return {
        "ok": True,
        "cookie": cookie,
        "cookie_status": cookie_status,
        "message": "已从本机 Chrome 读取有效 Cookie",
    }, 200


class CookieHelperHandler(BaseHTTPRequestHandler):
    server_version = "WeiboCookieHelper/1.0"

    def _set_cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin and is_allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send_json(self, payload: dict, status_code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        if not is_allowed_origin(self.headers.get("Origin")):
            self._send_json({"ok": False, "message": "Origin not allowed"}, 403)
            return
        self.send_response(204)
        self._set_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:
        if not is_allowed_origin(self.headers.get("Origin")):
            self._send_json({"ok": False, "message": "Origin not allowed"}, 403)
            return

        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"ok": True, "message": "Cookie helper is running"})
            return
        if parsed.path != "/api/cookie":
            self._send_json({"ok": False, "message": "Not Found"}, 404)
            return

        query = parse_qs(parsed.query)
        user_id = (query.get("user_id") or [DEFAULT_USER_ID])[0]
        payload, status_code = build_cookie_payload(user_id)
        self._send_json(payload, status_code)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), CookieHelperHandler)
    print(f"Weibo cookie helper listening on http://{HOST}:{PORT}")
    print("Keep this terminal open while using the dashboard auto-cookie button.")
    server.serve_forever()


if __name__ == "__main__":
    main()
