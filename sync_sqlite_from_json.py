#!/usr/bin/env python3
"""Rebuild the SQLite archive from the canonical JSON file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backup_paths import DEFAULT_CONFIG_PATH, resolve_archive_paths
from sqlite_store import replace_from_json, resolve_db_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--json", default=None)
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    paths = resolve_archive_paths(
        config_path=Path(args.config),
        user_id=args.user_id,
        json_path=Path(args.json) if args.json else None,
    )
    db_path = Path(args.db).resolve() if args.db else resolve_db_path(paths.config_path)
    result = replace_from_json(paths.json_path, db_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
