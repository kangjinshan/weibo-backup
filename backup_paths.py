#!/usr/bin/env python3
"""Resolve account-specific backup paths from the spider config."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = ROOT / "weiboSpider" / "config.json"
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


@dataclass(frozen=True)
class ArchivePaths:
    config_path: Path
    json_path: Path
    user_dir: Path
    image_dir: Path
    video_dir: Path
    user_id: str


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    return json.loads(config_path.read_text(encoding="utf-8"))


def user_ids_from_config(config: dict[str, Any], config_path: Path = DEFAULT_CONFIG_PATH) -> list[str]:
    raw = config.get("user_id_list", [])
    if isinstance(raw, list):
        result = []
        for item in raw:
            if isinstance(item, dict):
                value = item.get("id") or item.get("user_uri")
            else:
                value = item
            value = str(value or "").strip()
            if value:
                result.append(value)
        return result
    value = str(raw or "").strip()
    if not value:
        return []
    if value.endswith(".txt"):
        list_path = Path(value)
        if not list_path.is_absolute():
            list_path = config_path.parent / list_path
        if not list_path.is_file():
            return []
        ids = []
        for line in list_path.read_text(encoding="utf-8-sig").splitlines():
            parts = line.strip().split()
            if parts and parts[0]:
                ids.append(parts[0])
        return ids
    return [value]


def resolve_user_id(config: dict[str, Any], user_id: str | None = None, config_path: Path = DEFAULT_CONFIG_PATH) -> str:
    if user_id:
        return str(user_id).strip()
    ids = user_ids_from_config(config, config_path)
    if not ids:
        raise ValueError("weiboSpider/config.json does not contain a usable user_id_list")
    return ids[0]


def find_json_for_user(root: Path, user_id: str) -> Path:
    candidates = []
    for path in root.glob(f"*/{user_id}.json"):
        if path.parent.name in EXCLUDED_DATA_DIRS or path.parent.name.startswith("."):
            continue
        if path.is_file():
            candidates.append(path)
    if not candidates:
        raise FileNotFoundError(f"Cannot find archive JSON for user_id={user_id} under {root}")
    return sorted(candidates, key=lambda p: (p.parent.name.isascii(), p.parent.name, p.name))[0]


def resolve_archive_paths(
    *,
    root: Path | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
    user_id: str | None = None,
    json_path: Path | None = None,
    user_dir: Path | None = None,
) -> ArchivePaths:
    config_path = config_path.resolve()
    root = root.resolve() if root else config_path.parent.parent.resolve()
    config = load_config(config_path)
    resolved_user_id = resolve_user_id(config, user_id, config_path)
    resolved_json = json_path.resolve() if json_path else find_json_for_user(root, resolved_user_id).resolve()
    resolved_user_dir = user_dir.resolve() if user_dir else resolved_json.parent
    return ArchivePaths(
        config_path=config_path,
        json_path=resolved_json,
        user_dir=resolved_user_dir,
        image_dir=resolved_user_dir / "img",
        video_dir=resolved_user_dir / "video",
        user_id=resolved_user_id,
    )
