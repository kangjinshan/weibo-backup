#!/usr/bin/env python3
"""SQLite storage helpers for the Weibo backup archive."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from backup_paths import DEFAULT_CONFIG_PATH, load_config


WEIBO_COLUMNS = {
    "id": "varchar(20) NOT NULL",
    "user_id": "varchar(20)",
    "content": "varchar(2000)",
    "article_url": "varchar(200)",
    "original_pictures": "varchar(3000)",
    "retweet_pictures": "varchar(3000)",
    "original_pictures_list": "varchar(3000)",
    "retweet_pictures_list": "varchar(3000)",
    "media": "varchar(3000)",
    "original": "BOOLEAN NOT NULL DEFAULT 1",
    "video_url": "varchar(300)",
    "publish_place": "varchar(100)",
    "publish_time": "DATETIME NOT NULL",
    "publish_tool": "varchar(30)",
    "up_num": "INT NOT NULL DEFAULT 0",
    "retweet_num": "INT NOT NULL DEFAULT 0",
    "comment_num": "INT NOT NULL DEFAULT 0",
}
USER_COLUMNS = {
    "id": "varchar(20) NOT NULL",
    "nickname": "varchar(30)",
    "gender": "varchar(10)",
    "location": "varchar(200)",
    "birthday": "varchar(40)",
    "description": "varchar(400)",
    "verified_reason": "varchar(140)",
    "talent": "varchar(200)",
    "education": "varchar(200)",
    "work": "varchar(200)",
    "weibo_num": "INT",
    "following": "INT",
    "followers": "INT",
}
JSON_FIELDS = {"original_pictures_list", "retweet_pictures_list", "media"}
WEIBO_DEFAULTS = {
    "id": "",
    "content": "",
    "article_url": "",
    "original_pictures": "无",
    "retweet_pictures": "无",
    "original_pictures_list": [],
    "retweet_pictures_list": [],
    "media": {},
    "original": True,
    "video_url": "无",
    "publish_place": "无",
    "publish_time": "",
    "publish_tool": "",
    "up_num": 0,
    "retweet_num": 0,
    "comment_num": 0,
}


def resolve_db_path(config_path: Path = DEFAULT_CONFIG_PATH) -> Path:
    config_path = config_path.resolve()
    config = load_config(config_path)
    raw = str(config.get("sqlite_config") or "weibo.db")
    path = Path(raw)
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def json_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def parse_json_value(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["original_pictures_list"] = parse_json_value(item.get("original_pictures_list"), [])
    item["retweet_pictures_list"] = parse_json_value(item.get("retweet_pictures_list"), [])
    item["media"] = parse_json_value(item.get("media"), {})
    item["original"] = bool(item.get("original"))
    return item


def ensure_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def ensure_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user (
                id varchar(20) NOT NULL,
                nickname varchar(30),
                gender varchar(10),
                location varchar(200),
                birthday varchar(40),
                description varchar(400),
                verified_reason varchar(140),
                talent varchar(200),
                education varchar(200),
                work varchar(200),
                weibo_num INT,
                following INT,
                followers INT,
                PRIMARY KEY (id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS weibo (
                id varchar(20) NOT NULL,
                user_id varchar(20),
                content varchar(2000),
                article_url varchar(200),
                original_pictures varchar(3000),
                retweet_pictures varchar(3000),
                original_pictures_list varchar(3000),
                retweet_pictures_list varchar(3000),
                media varchar(3000),
                original BOOLEAN NOT NULL DEFAULT 1,
                video_url varchar(300),
                publish_place varchar(100),
                publish_time DATETIME NOT NULL,
                publish_tool varchar(30),
                up_num INT NOT NULL DEFAULT 0,
                retweet_num INT NOT NULL DEFAULT 0,
                comment_num INT NOT NULL DEFAULT 0,
                PRIMARY KEY (id)
            )
            """
        )
        ensure_columns(connection, "user", USER_COLUMNS)
        ensure_columns(connection, "weibo", WEIBO_COLUMNS)
        connection.commit()


def insert_rows(connection: sqlite3.Connection, table: str, columns: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    placeholders = ", ".join(["?"] * len(columns))
    names = ", ".join(columns)
    sql = f"INSERT OR REPLACE INTO {table}({names}) VALUES ({placeholders})"
    values = [tuple(json_value(row.get(column)) for column in columns) for row in rows]
    connection.executemany(sql, values)


def normalize_weibo(raw: dict[str, Any], user_id: str) -> dict[str, Any]:
    item = dict(WEIBO_DEFAULTS)
    item.update(raw)
    item["id"] = str(item.get("id") or "")
    item["user_id"] = str(item.get("user_id") or user_id or "")
    for field in JSON_FIELDS:
        if isinstance(item.get(field), str):
            item[field] = parse_json_value(item[field], [] if field.endswith("_list") else {})
    return item


def replace_from_json(json_path: Path, db_path: Path) -> dict[str, Any]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    user = data.get("user") or {}
    user_id = str(user.get("id") or "")
    weibos = [normalize_weibo(item, user_id) for item in data.get("weibo", []) if item.get("id")]
    ensure_schema(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("DELETE FROM weibo")
        connection.execute("DELETE FROM user")
        insert_rows(connection, "user", list(USER_COLUMNS), [user] if user else [])
        insert_rows(connection, "weibo", list(WEIBO_COLUMNS), weibos)
        connection.commit()
    return {
        "json_path": str(json_path),
        "db_path": str(db_path),
        "user_count": 1 if user else 0,
        "weibo_count": len(weibos),
    }


def count_weibos(db_path: Path) -> int:
    ensure_schema(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM weibo").fetchone()[0])


def get_user(db_path: Path) -> dict[str, Any]:
    ensure_schema(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM user LIMIT 1").fetchone()
        return dict(row) if row else {}


def latest_publish_date(db_path: Path) -> str | None:
    ensure_schema(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute(
            """
            SELECT MAX(SUBSTR(publish_time, 1, 10))
            FROM weibo
            WHERE SUBSTR(publish_time, 1, 10) GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            """
        ).fetchone()
        return row[0] if row and row[0] else None


def date_counts(db_path: Path) -> dict[str, int]:
    ensure_schema(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT SUBSTR(publish_time, 1, 10) AS day, COUNT(*) AS count
            FROM weibo
            WHERE day GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            GROUP BY day
            """
        ).fetchall()
    return {str(day): int(count) for day, count in rows}


def fetch_weibos(db_path: Path, page: int = 1, per_page: int = 20, date: str | None = None) -> tuple[list[dict[str, Any]], int]:
    ensure_schema(db_path)
    page = max(1, int(page))
    per_page = max(1, int(per_page))
    offset = (page - 1) * per_page
    where = ""
    params: list[Any] = []
    if date:
        where = "WHERE publish_time LIKE ?"
        params.append(f"{date}%")
    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        total = int(connection.execute(f"SELECT COUNT(*) FROM weibo {where}", params).fetchone()[0])
        rows = connection.execute(
            f"""
            SELECT *
            FROM weibo
            {where}
            ORDER BY
                CASE WHEN publish_time IS NULL OR publish_time = '' THEN 1 ELSE 0 END,
                publish_time ASC,
                id ASC
            LIMIT ? OFFSET ?
            """,
            [*params, per_page, offset],
        ).fetchall()
    return [row_to_dict(row) for row in rows], total
