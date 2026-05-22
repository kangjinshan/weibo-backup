#!/usr/bin/env python3
"""Weibo Backup Monitor - 后端服务"""

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

from fastapi import FastAPI, HTTPException
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
SPIDER_PYTHON_ENV = os.environ.get("WEIBO_SPIDER_PYTHON")
SPIDER_PYTHON = Path(SPIDER_PYTHON_ENV).expanduser() if SPIDER_PYTHON_ENV else None
ROOT_VENV_PYTHON = BACKUP_DIR / ".venv" / "bin" / "python"
SPIDER_VENV_PYTHON = SPIDER_DIR / "venv" / "bin" / "python"
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


def spider_command():
    python = next(
        (
            candidate
            for candidate in [SPIDER_PYTHON, ROOT_VENV_PYTHON, SPIDER_VENV_PYTHON]
            if candidate and candidate.is_file()
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


def read_weibos_page(page: int = 1, per_page: int = 20, date: Optional[str] = None):
    return sqlite_fetch_weibos(sqlite_db_path(), page=page, per_page=per_page, date=date)


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
async def weibo_list(page: int = 1, per_page: int = 20, date: Optional[str] = None):
    try:
        weibos, total = read_weibos_page(page=page, per_page=per_page, date=date)
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
    return JSONResponse(
        {
            "user_id_list": config.get("user_id_list", []),
            "since_date": default_dates["since_date"],
            "end_date": default_dates["end_date"],
            "pic_download": bool(config.get("pic_download")),
            "video_download": bool(config.get("video_download")),
            "write_mode": config.get("write_mode", ["csv", "txt", "json", "sqlite"]),
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
    return JSONResponse({"ok": True, "backup_path": str(backup_path)})


@app.post("/api/backup/start")
async def start_backup():
    status = get_backup_process_status()
    if status["running"]:
        return JSONResponse({"ok": False, "status": status, "message": "backup already running"})
    ensure_logs_dir()
    log_fh = BACKUP_LOG_PATH.open("ab")
    process = subprocess.Popen(
        spider_command(),
        cwd=str(SPIDER_DIR),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_fh.close()
    BACKUP_PID_PATH.write_text(str(process.pid) + "\n", encoding="utf-8")
    return JSONResponse({"ok": True, "pid": process.pid, "log_path": str(BACKUP_LOG_PATH)})


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
