#!/usr/bin/env python3
"""Weibo Backup Monitor - 后端服务"""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from sqlite_store import (
    count_weibos as sqlite_count_weibos,
    date_counts as sqlite_date_counts,
    fetch_weibos as sqlite_fetch_weibos,
    get_user as sqlite_get_user,
    latest_publish_date as sqlite_latest_publish_date,
    resolve_db_path,
)

app = FastAPI(title="微博备份监控")

DEFAULT_BACKUP_DIR = Path(__file__).resolve().parents[1]
BACKUP_DIR = Path(os.environ.get("WEIBO_BACKUP_DIR", str(DEFAULT_BACKUP_DIR))).resolve()
SPIDER_DIR = BACKUP_DIR / "weiboSpider"
DATA_DIR = BACKUP_DIR
CONFIG_PATH = SPIDER_DIR / "config.json"
LOGS_DIR = BACKUP_DIR / "logs"
BACKUP_PID_PATH = LOGS_DIR / "backup.pid"
BACKUP_LOG_PATH = LOGS_DIR / "backup-run.log"
AUTH_CONFIG_PATH = Path(
    os.environ.get("WEIBO_DASHBOARD_AUTH_PATH", str(LOGS_DIR / "dashboard-auth.json"))
).expanduser()
AUTH_COOKIE_NAME = "weibo_dashboard_session"
PASSWORD_MIN_LENGTH = 8
PASSWORD_HASH_ITERATIONS = 260_000
SESSION_DURATION = timedelta(days=14)
SPIDER_PYTHON_ENV = os.environ.get("WEIBO_SPIDER_PYTHON")
SPIDER_PYTHON = Path(SPIDER_PYTHON_ENV).expanduser() if SPIDER_PYTHON_ENV else None
ROOT_VENV_PYTHON = BACKUP_DIR / ".venv" / "bin" / "python"
EXCLUDED_DATA_DIRS = {
    "__pycache__",
    "archive",
    "data",
    "dashboard",
    "logs",
    "scripts",
    "tests",
    "weiboSpider",
}
COOKIE_PLACEHOLDER_FRAGMENTS = (
    "PASTE_YOUR_WEIBO_COOKIE",
    "YOUR_WEIBO_COOKIE",
    "你的微博 COOKIE",
)
USER_ID_PLACEHOLDER_VALUES = {
    "YOUR_WEIBO_USER_ID",
    "你的微博用户ID",
}
DEFAULT_AUTO_BACKUP_HOUR = 3
DEFAULT_AUTO_BACKUP_TIMEZONE = "Asia/Shanghai"
AUTO_BACKUP_TIMEZONE_ENV = "WEIBO_AUTO_BACKUP_TIMEZONE"
AUTO_BACKUP_TASK: Optional[asyncio.Task] = None
PUBLIC_AUTH_PATHS = {
    "/",
    "/api/auth/status",
    "/api/auth/setup",
    "/api/auth/login",
}


def utc_now():
    return datetime.now(timezone.utc)


def b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def password_hash(password: str, salt: str, iterations: int) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        b64decode(salt),
        iterations,
    )
    return b64encode(digest)


def read_dashboard_auth_config() -> dict:
    try:
        return json.loads(AUTH_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def dashboard_auth_configured() -> bool:
    config = read_dashboard_auth_config()
    return bool(
        config.get("password_hash")
        and config.get("password_salt")
        and config.get("session_secret")
    )


def create_dashboard_auth_config(password: str) -> dict:
    password = str(password or "")
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"密码至少需要 {PASSWORD_MIN_LENGTH} 个字符")

    salt = b64encode(secrets.token_bytes(32))
    config = {
        "password_alg": "pbkdf2_sha256",
        "password_hash": password_hash(password, salt, PASSWORD_HASH_ITERATIONS),
        "password_salt": salt,
        "password_iterations": PASSWORD_HASH_ITERATIONS,
        "session_secret": b64encode(secrets.token_bytes(32)),
        "created_at": utc_now().isoformat(),
    }
    AUTH_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(AUTH_CONFIG_PATH, config)
    try:
        AUTH_CONFIG_PATH.chmod(0o600)
    except Exception:
        pass
    return config


def verify_dashboard_password(password: str, config: dict) -> bool:
    try:
        expected = str(config["password_hash"])
        salt = str(config["password_salt"])
        iterations = int(config.get("password_iterations", PASSWORD_HASH_ITERATIONS))
        actual = password_hash(str(password or ""), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def session_secret(config: dict) -> bytes:
    return b64decode(str(config["session_secret"]))


def create_dashboard_session_cookie(config: dict) -> str:
    expires_at = int((utc_now() + SESSION_DURATION).timestamp())
    payload = f"{expires_at}:{secrets.token_urlsafe(18)}"
    signature = hmac.new(session_secret(config), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def valid_dashboard_session_cookie(cookie: str, config: dict) -> bool:
    try:
        expires_at, nonce, signature = str(cookie or "").split(":", 2)
        payload = f"{expires_at}:{nonce}"
        expected = hmac.new(session_secret(config), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return False
        return int(expires_at) > int(utc_now().timestamp())
    except Exception:
        return False


def dashboard_path_requires_auth(path: str) -> bool:
    return path not in PUBLIC_AUTH_PATHS


def request_is_authenticated(request: Request, config: dict) -> bool:
    return valid_dashboard_session_cookie(
        request.cookies.get(AUTH_COOKIE_NAME, ""),
        config,
    )


def dashboard_cookie_secure(request: Request) -> bool:
    configured = os.environ.get("WEIBO_DASHBOARD_COOKIE_SECURE", "").lower()
    if configured in {"1", "true", "yes", "on"}:
        return True
    if configured in {"0", "false", "no", "off"}:
        return False
    return request.url.scheme == "https"


def set_dashboard_session_cookie(response: JSONResponse, request: Request, config: dict):
    response.set_cookie(
        AUTH_COOKIE_NAME,
        create_dashboard_session_cookie(config),
        max_age=int(SESSION_DURATION.total_seconds()),
        httponly=True,
        secure=dashboard_cookie_secure(request),
        samesite="lax",
        path="/",
    )


@app.middleware("http")
async def dashboard_auth_middleware(request: Request, call_next):
    if not dashboard_path_requires_auth(request.url.path):
        return await call_next(request)

    config = read_dashboard_auth_config()
    if not dashboard_auth_configured():
        return JSONResponse(
            {"ok": False, "auth_required": True, "configured": False, "message": "请先设置访问密码"},
            status_code=401,
        )
    if not request_is_authenticated(request, config):
        return JSONResponse(
            {"ok": False, "auth_required": True, "configured": True, "message": "请先登录"},
            status_code=401,
        )
    return await call_next(request)


def find_user_dir():
    for d in sorted(DATA_DIR.iterdir(), key=lambda path: path.name):
        if (
            d.is_dir()
            and not d.name.startswith(".")
            and d.name not in EXCLUDED_DATA_DIRS
            and any(f.is_file() for f in d.glob("*.json"))
        ):
            return d
    return None


def read_json_data():
    user_dir = find_user_dir()
    if not user_dir:
        return None
    candidates = sorted(
        user_dir.glob("*.json"),
        key=lambda f: (not f.stem.isdigit(), f.name),
    )
    for f in candidates:
        if f.stat().st_size > 100:
            with open(f, encoding='utf-8') as fh:
                return json.load(fh)
    return None


def read_backup_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def cookie_is_configured(config: dict) -> bool:
    cookie = str(config.get("cookie") or "").strip()
    if not cookie or "=" not in cookie:
        return False
    normalized = cookie.upper()
    return not any(fragment in normalized for fragment in COOKIE_PLACEHOLDER_FRAGMENTS)


def user_ids_are_configured(config: dict) -> bool:
    user_ids = parse_user_ids(config.get("user_id_list"))
    if not user_ids:
        return False
    return not any(user_id in USER_ID_PLACEHOLDER_VALUES for user_id in user_ids)


def backup_config_issues(config: dict) -> list[str]:
    issues = []
    if not user_ids_are_configured(config):
        issues.append("账号 ID 未配置或仍是示例值，请先填写 user_id_list")
    if not cookie_is_configured(config):
        issues.append("cookie 未配置或仍是示例值，请在 NAS 的 weiboSpider/config.json 中填写有效微博 cookie")
    return issues


def sqlite_db_path():
    return resolve_db_path(CONFIG_PATH)


def write_json_atomic(path: Path, payload: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_user_ids(value):
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def bool_to_int(value):
    if isinstance(value, str):
        return 1 if value.lower() in {"1", "true", "yes", "on"} else 0
    return 1 if value else 0


def normalize_auto_backup_hour(value, default: int = DEFAULT_AUTO_BACKUP_HOUR) -> int:
    try:
        hour = int(value)
    except (TypeError, ValueError):
        return default
    if 0 <= hour <= 23:
        return hour
    return default


def auto_backup_settings(config: dict) -> dict:
    return {
        "enabled": bool(bool_to_int(config.get("auto_backup_enabled", False))),
        "hour": normalize_auto_backup_hour(config.get("auto_backup_hour", DEFAULT_AUTO_BACKUP_HOUR)),
    }


def auto_backup_timezone():
    name = os.environ.get(AUTO_BACKUP_TIMEZONE_ENV, DEFAULT_AUTO_BACKUP_TIMEZONE)
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_AUTO_BACKUP_TIMEZONE)


def sanitize_backup_config(incoming: dict, current: dict) -> dict:
    config = dict(current)
    if "user_id_list" in incoming:
        user_ids = parse_user_ids(incoming.get("user_id_list"))
        if user_ids:
            config["user_id_list"] = user_ids
    for key in ("since_date", "end_date"):
        value = str(incoming.get(key, "")).strip()
        if value:
            if key == "end_date" and value == today_string():
                value = "now"
            config[key] = value
    if "pic_download" in incoming:
        config["pic_download"] = bool_to_int(incoming.get("pic_download"))
    if "video_download" in incoming:
        config["video_download"] = bool_to_int(incoming.get("video_download"))
    if "write_mode" in incoming:
        write_mode = incoming.get("write_mode")
        if isinstance(write_mode, list) and write_mode:
            config["write_mode"] = [str(v).strip() for v in write_mode if str(v).strip()]
    if "cookie" in incoming:
        cookie = str(incoming.get("cookie") or "").strip()
        if cookie:
            config["cookie"] = cookie
    if "auto_backup_enabled" in incoming:
        config["auto_backup_enabled"] = bool(bool_to_int(incoming.get("auto_backup_enabled")))
    if "auto_backup_hour" in incoming:
        config["auto_backup_hour"] = normalize_auto_backup_hour(incoming.get("auto_backup_hour"))
    return config


def today_string():
    return datetime.now().strftime("%Y-%m-%d")


def latest_backed_up_date():
    try:
        return sqlite_latest_publish_date(sqlite_db_path())
    except Exception:
        data = read_json_data()
        if not data or not data.get("weibo"):
            return None
        dates = []
        for weibo in data["weibo"]:
            publish_time = str(weibo.get("publish_time") or "").strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}", publish_time):
                dates.append(publish_time[:10])
        return max(dates) if dates else None


def incremental_backup_dates(config: dict):
    return {
        "since_date": latest_backed_up_date() or config.get("since_date", "2010-01-01"),
        "end_date": today_string(),
    }


def read_pid(path: Optional[Path] = None) -> Optional[int]:
    path = path or BACKUP_PID_PATH
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def process_state(pid: int) -> str:
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def get_backup_process_status():
    pid = read_pid()
    if not pid:
        return {"running": False, "status": "stopped", "pid": None}
    state = process_state(pid)
    if not state:
        return {"running": False, "status": "stopped", "pid": pid}
    status = "paused" if state.startswith("T") else "running"
    return {"running": True, "status": status, "pid": pid, "state": state}


def get_backup_run_summary():
    if not BACKUP_LOG_PATH.exists():
        return {}
    try:
        with open(BACKUP_LOG_PATH, "rb") as fh:
            fh.seek(max(0, BACKUP_LOG_PATH.stat().st_size - 500_000))
            content = fh.read().decode("utf-8", errors="ignore")
    except Exception:
        return {}

    summary = {}
    if "信息抓取完毕" in content:
        summary["status"] = "completed"
    count_matches = re.findall(r"共爬取(\d+)条微博", content)
    if count_matches:
        summary["last_run_weibo_count"] = int(count_matches[-1])
    return summary


def ensure_logs_dir():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def executable_file(path: Optional[Path]) -> bool:
    return bool(path and path.is_file() and os.access(path, os.X_OK))


def usable_python(path: Optional[Path]) -> bool:
    if not executable_file(path):
        return False
    try:
        result = subprocess.run(
            [str(path), "-c", "import sys"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def spider_command():
    python = next(
        (
            candidate
            for candidate in [SPIDER_PYTHON, Path(sys.executable), ROOT_VENV_PYTHON]
            if usable_python(candidate)
        ),
        Path(sys.executable),
    )
    return [
        str(python),
        "-m",
        "weibo_spider",
        f"--config_path={CONFIG_PATH}",
        f"--output_dir={BACKUP_DIR}",
    ]


def start_backup_process() -> dict:
    status = get_backup_process_status()
    if status["running"]:
        return {"ok": False, "status": status, "message": "backup already running"}
    try:
        config = read_backup_config()
    except Exception as exc:
        return {
            "ok": False,
            "message": f"启动失败：无法读取 weiboSpider/config.json：{exc}",
            "status_code": 400,
        }
    issues = backup_config_issues(config)
    if issues:
        return {
            "ok": False,
            "message": "启动失败：" + "；".join(issues),
            "config_issues": issues,
            "status_code": 400,
        }
    ensure_logs_dir()
    command = spider_command()
    try:
        with BACKUP_LOG_PATH.open("ab") as log_fh:
            process = subprocess.Popen(
                command,
                cwd=str(SPIDER_DIR),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except Exception as exc:
        return {
            "ok": False,
            "message": f"启动失败：{exc}",
            "command": command,
            "cwd": str(SPIDER_DIR),
            "log_path": str(BACKUP_LOG_PATH),
            "status_code": 500,
        }
    BACKUP_PID_PATH.write_text(str(process.pid) + "\n", encoding="utf-8")
    return {"ok": True, "pid": process.pid, "log_path": str(BACKUP_LOG_PATH)}


def json_response_from_result(result: dict) -> JSONResponse:
    status_code = int(result.get("status_code", 200))
    payload = {key: value for key, value in result.items() if key != "status_code"}
    return JSONResponse(payload, status_code=status_code)


def next_auto_backup_at(hour: int, now: Optional[datetime] = None, tz=None) -> datetime:
    tz = tz or auto_backup_timezone()
    if now is None:
        now = datetime.now(tz)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)
    target = now.replace(hour=normalize_auto_backup_hour(hour), minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


async def run_scheduled_backup_once() -> dict:
    status = get_backup_process_status()
    if status["running"]:
        return {"ok": False, "status": "skipped", "reason": "backup already running", "backup_status": status}
    return start_backup_process()


async def auto_backup_scheduler():
    while True:
        try:
            config = read_backup_config()
            settings = auto_backup_settings(config)
        except Exception:
            settings = {"enabled": False, "hour": DEFAULT_AUTO_BACKUP_HOUR}

        if not settings["enabled"]:
            await asyncio.sleep(60)
            continue

        target = next_auto_backup_at(settings["hour"])
        settings_changed = False
        while True:
            delay = (target - datetime.now(target.tzinfo)).total_seconds()
            if delay <= 0:
                break
            await asyncio.sleep(min(delay, 60))
            try:
                latest_settings = auto_backup_settings(read_backup_config())
            except Exception:
                latest_settings = {"enabled": False, "hour": DEFAULT_AUTO_BACKUP_HOUR}
            if latest_settings != settings:
                settings_changed = True
                break
        if settings_changed:
            continue

        try:
            current_settings = auto_backup_settings(read_backup_config())
        except Exception:
            current_settings = {"enabled": False, "hour": DEFAULT_AUTO_BACKUP_HOUR}
        if current_settings["enabled"] and current_settings["hour"] == settings["hour"]:
            await run_scheduled_backup_once()


@app.on_event("startup")
async def start_auto_backup_scheduler():
    global AUTO_BACKUP_TASK
    if AUTO_BACKUP_TASK is None or AUTO_BACKUP_TASK.done():
        AUTO_BACKUP_TASK = asyncio.create_task(auto_backup_scheduler())


@app.on_event("shutdown")
async def stop_auto_backup_scheduler():
    global AUTO_BACKUP_TASK
    if AUTO_BACKUP_TASK is not None:
        AUTO_BACKUP_TASK.cancel()
        try:
            await AUTO_BACKUP_TASK
        except asyncio.CancelledError:
            pass
        AUTO_BACKUP_TASK = None


def get_stats():
    user_dir = find_user_dir()
    if not user_dir:
        return {"weibo_count": 0, "img_count": 0, "video_count": 0, "total_size_mb": 0}

    try:
        weibo_count = sqlite_count_weibos(sqlite_db_path())
    except Exception:
        weibo_count = 0

    img_count = 0
    img_size = 0
    for sub in ['原创微博图片', '转发微博图片', '头像图片']:
        img_dir = user_dir / 'img' / sub
        if img_dir.exists():
            for f in img_dir.iterdir():
                if f.is_file() and not f.name.startswith('.'):
                    img_count += 1
                    img_size += f.stat().st_size

    video_count = 0
    video_size = 0
    video_dir = user_dir / 'video'
    if video_dir.exists():
        for f in video_dir.iterdir():
            if f.is_file() and not f.name.startswith('.') and f.name != 'not_downloaded.txt':
                video_count += 1
                video_size += f.stat().st_size

    total_size = img_size + video_size
    for f in user_dir.glob("*.*"):
        if f.is_file():
            total_size += f.stat().st_size

    return {
        "weibo_count": weibo_count,
        "img_count": img_count,
        "video_count": video_count,
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "img_size_mb": round(img_size / 1024 / 1024, 2),
        "video_size_mb": round(video_size / 1024 / 1024, 2),
    }


def get_spider_status():
    result = {
        "running": False,
        "current_page": 0,
        "total_pages": 0,
        "status": "unknown",
        "next_wait": 0,
        "process_count": 0,
    }

    try:
        out = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=5)
        for line in out.stdout.splitlines():
            if "weibo_spider" in line and "grep" not in line:
                result["process_count"] += 1
                result["running"] = True
    except Exception:
        pass

    log_candidates = []
    logs_dir = BACKUP_DIR / "logs"
    if logs_dir.exists():
        log_candidates.extend(logs_dir.glob("spider*.log"))
    log_candidates.extend([SPIDER_DIR / "all.log", SPIDER_DIR / "error.log"])

    newest_log_time = 0
    for log_path in log_candidates:
        if not log_path.exists() or log_path.stat().st_size == 0:
            continue
        try:
            newest_log_time = max(newest_log_time, log_path.stat().st_mtime)
            with open(log_path, "rb") as fh:
                fh.seek(max(0, log_path.stat().st_size - 2_000_000))
                content = fh.read().decode("utf-8", errors="ignore")

            pages = [int(p) for p in re.findall(r"已获取.*?第(\d+)页微博", content)]
            if pages:
                result["current_page"] = max(result["current_page"], pages[-1])

            progress_matches = re.findall(
                r"Progress:\s*(\d+)%\|.*?\|\s*(\d+)/(\d+)", content)
            for _, current, total in progress_matches[-1:]:
                result["current_page"] = max(result["current_page"], int(current))
                result["total_pages"] = max(result["total_pages"], int(total))

            if "即将进入全局等待时间" in content[-5000:]:
                result["status"] = "global_waiting"
        except Exception:
            pass

    if not result["running"]:
        result["status"] = "stopped"
    elif result["status"] == "unknown":
        result["status"] = "running"

    backup_process = get_backup_process_status()
    if backup_process["running"]:
        result["running"] = True
        result["pid"] = backup_process["pid"]
        result["process_count"] = max(result["process_count"], 1)
        result["status"] = backup_process["status"]
    else:
        backup_summary = get_backup_run_summary()
        if backup_summary.get("status") == "completed":
            result["status"] = "completed"
            result.update(backup_summary)

    if newest_log_time:
        result["last_log_time"] = datetime.fromtimestamp(
            newest_log_time).strftime("%Y-%m-%d %H:%M:%S")

    return result


def get_user_info():
    try:
        return sqlite_get_user(sqlite_db_path())
    except Exception:
        return {}


def read_weibos_page(
    page: int = 1,
    per_page: int = 20,
    date: Optional[str] = None,
    post_type: str = "all",
    media_type: str = "all",
):
    return sqlite_fetch_weibos(
        sqlite_db_path(),
        page=page,
        per_page=per_page,
        date=date,
        post_type=post_type,
        media_type=media_type,
    )


def get_local_video_url(user_dir: Path, weibo: dict):
    publish_time = weibo.get("publish_time", "")
    weibo_id = weibo.get("id", "")
    if not publish_time or not weibo_id:
        return None

    date_prefix = publish_time[:10].replace("-", "")
    video_path = user_dir / "video" / f"{date_prefix}_{weibo_id}.mp4"
    if not video_path.exists():
        return None

    relative_path = video_path.relative_to(DATA_DIR).as_posix()
    return "/media/" + quote(relative_path)


def media_url(path: Path):
    relative_path = path.relative_to(DATA_DIR).as_posix()
    return "/media/" + quote(relative_path)


def first_existing_media(pattern: str):
    matches = sorted(Path(pattern).parent.glob(Path(pattern).name))
    for match in matches:
        if match.is_file() and not match.name.startswith("."):
            return match
    return None


def get_local_picture_urls(user_dir: Path, weibo: dict, source_key: str, subdir: str):
    urls = weibo.get(source_key) or []
    if not urls:
        return []

    publish_time = weibo.get("publish_time", "")
    weibo_id = weibo.get("id", "")
    if not publish_time or not weibo_id:
        return []

    date_prefix = publish_time[:10].replace("-", "")
    file_prefix = f"{date_prefix}_{weibo_id}"
    picture_dir = user_dir / "img" / subdir
    if not picture_dir.exists():
        return []

    local_urls = []
    if len(urls) == 1:
        match = first_existing_media(str(picture_dir / f"{file_prefix}.*"))
        if match:
            local_urls.append(media_url(match))
        return local_urls

    for index in range(1, len(urls) + 1):
        match = first_existing_media(str(picture_dir / f"{file_prefix}_{index}.*"))
        if match:
            local_urls.append(media_url(match))
    return local_urls


def with_local_media_urls(weibos, owner_user_id: str = ""):
    user_dir = find_user_dir()
    if not user_dir:
        return [dict(weibo, owner_user_id=owner_user_id) for weibo in weibos]

    enriched = []
    for weibo in weibos:
        item = dict(weibo)
        item["owner_user_id"] = str(item.get("user_id") or owner_user_id or "")
        local_video_url = get_local_video_url(user_dir, item)
        if local_video_url:
            item["local_video_url"] = local_video_url
        local_original = get_local_picture_urls(
            user_dir, item, "original_pictures_list", "原创微博图片")
        if local_original:
            item["local_original_pictures_list"] = local_original
        local_retweet = get_local_picture_urls(
            user_dir, item, "retweet_pictures_list", "转发微博图片")
        if local_retweet:
            item["local_retweet_pictures_list"] = local_retweet
        enriched.append(item)
    return enriched


def sort_weibos_chronologically(weibos):
    return sorted(
        weibos,
        key=lambda w: (
            not bool(w.get("publish_time")),
            str(w.get("publish_time") or ""),
            str(w.get("id") or ""),
        ),
    )


# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding='utf-8'))


@app.get("/api/auth/status")
async def auth_status(request: Request):
    config = read_dashboard_auth_config()
    configured = dashboard_auth_configured()
    return JSONResponse(
        {
            "configured": configured,
            "authenticated": bool(configured and request_is_authenticated(request, config)),
        }
    )


@app.post("/api/auth/setup")
async def setup_dashboard_auth(request: Request, payload: dict):
    if dashboard_auth_configured():
        return JSONResponse({"ok": False, "message": "访问密码已设置"}, status_code=400)
    try:
        config = create_dashboard_auth_config(payload.get("password", ""))
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)

    response = JSONResponse({"ok": True, "configured": True, "authenticated": True})
    set_dashboard_session_cookie(response, request, config)
    return response


@app.post("/api/auth/login")
async def login_dashboard_auth(request: Request, payload: dict):
    config = read_dashboard_auth_config()
    if not dashboard_auth_configured():
        return JSONResponse({"ok": False, "message": "请先设置访问密码"}, status_code=400)
    if not verify_dashboard_password(payload.get("password", ""), config):
        return JSONResponse({"ok": False, "message": "密码错误"}, status_code=401)

    response = JSONResponse({"ok": True, "configured": True, "authenticated": True})
    set_dashboard_session_cookie(response, request, config)
    return response


@app.post("/api/auth/logout")
async def logout_dashboard_auth():
    response = JSONResponse({"ok": True})
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    return response


@app.get("/media/{media_path:path}")
async def media(media_path: str):
    decoded_path = unquote(media_path)
    target_path = (DATA_DIR / decoded_path).resolve()
    data_root = DATA_DIR.resolve()

    if not target_path.is_file() or data_root not in target_path.parents:
        raise HTTPException(status_code=404, detail="Media not found")

    return FileResponse(target_path)


@app.get("/api/stats")
async def stats():
    return JSONResponse(get_stats())


@app.get("/api/spider-status")
async def spider_status():
    return JSONResponse(get_spider_status())


@app.get("/api/weibo")
async def weibo_list(
    page: int = 1,
    per_page: int = 20,
    date: Optional[str] = None,
    post_type: str = "all",
    media_type: str = "all",
):
    try:
        if post_type not in {"all", "original"}:
            post_type = "all"
        if media_type not in {"all", "text", "text_image", "text_image_video"}:
            media_type = "all"
        weibos, total = read_weibos_page(
            page=page,
            per_page=per_page,
            date=date,
            post_type=post_type,
            media_type=media_type,
        )
    except Exception:
        return JSONResponse({"weibo": [], "total": 0, "page": page})

    owner_user_id = str(get_user_info().get("id") or "")
    return JSONResponse({
        "weibo": with_local_media_urls(weibos, owner_user_id),
        "total": total,
        "page": page,
        "per_page": per_page,
    })


@app.get("/api/dates")
async def date_summary():
    try:
        dates = sqlite_date_counts(sqlite_db_path())
    except Exception:
        return JSONResponse({"dates": {}})
    return JSONResponse({"dates": dates})


@app.get("/api/user")
async def user_info():
    return JSONResponse(get_user_info())


@app.get("/api/backup-config")
async def backup_config():
    config = read_backup_config()
    default_dates = incremental_backup_dates(config)
    issues = backup_config_issues(config)
    schedule = auto_backup_settings(config)
    return JSONResponse(
        {
            "user_id_list": config.get("user_id_list", []),
            "since_date": default_dates["since_date"],
            "end_date": default_dates["end_date"],
            "pic_download": bool(config.get("pic_download")),
            "video_download": bool(config.get("video_download")),
            "write_mode": config.get("write_mode", ["csv", "txt", "json", "sqlite"]),
            "auto_backup_enabled": schedule["enabled"],
            "auto_backup_hour": schedule["hour"],
            "cookie_configured": cookie_is_configured(config),
            "config_issues": issues,
            "status": get_backup_process_status(),
        }
    )


@app.post("/api/backup-config")
async def save_backup_config(payload: dict):
    current = read_backup_config()
    next_config = sanitize_backup_config(payload, current)
    ensure_logs_dir()
    backup_path = CONFIG_PATH.with_suffix(
        f".before-dashboard-{time.strftime('%Y%m%d-%H%M%S')}.json"
    )
    backup_path.write_bytes(CONFIG_PATH.read_bytes())
    write_json_atomic(CONFIG_PATH, next_config)
    return JSONResponse(
        {
            "ok": True,
            "backup_path": str(backup_path),
            "cookie_configured": cookie_is_configured(next_config),
            "config_issues": backup_config_issues(next_config),
        }
    )


@app.post("/api/backup/start")
async def start_backup():
    return json_response_from_result(start_backup_process())


def signal_backup_process(pid: int, sig: int):
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        raise
    except Exception:
        os.kill(pid, sig)


@app.post("/api/backup/pause")
async def pause_backup():
    status = get_backup_process_status()
    if not status["running"]:
        return JSONResponse({"ok": False, "status": status, "message": "backup is not running"})
    signal_backup_process(int(status["pid"]), signal.SIGSTOP)
    return JSONResponse({"ok": True, "status": get_backup_process_status()})


@app.post("/api/backup/resume")
async def resume_backup():
    status = get_backup_process_status()
    if not status["running"]:
        return JSONResponse({"ok": False, "status": status, "message": "backup is not running"})
    signal_backup_process(int(status["pid"]), signal.SIGCONT)
    return JSONResponse({"ok": True, "status": get_backup_process_status()})


@app.post("/api/backup/stop")
async def stop_backup():
    status = get_backup_process_status()
    if not status["running"]:
        return JSONResponse({"ok": False, "status": status, "message": "backup is not running"})
    signal_backup_process(int(status["pid"]), signal.SIGTERM)
    return JSONResponse({"ok": True, "status": "stopping", "pid": status["pid"]})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
