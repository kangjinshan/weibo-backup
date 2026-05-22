import json
import tempfile
import unittest
from pathlib import Path

from backup_paths import resolve_archive_paths, user_ids_from_config


class BackupPathsTests(unittest.TestCase):
    def test_resolves_archive_paths_from_config_user_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "weiboSpider"
            config_dir.mkdir()
            config_path = config_dir / "config.json"
            config_path.write_text(json.dumps({"user_id_list": ["123"]}), encoding="utf-8")
            user_dir = root / "昵称目录"
            user_dir.mkdir()
            json_path = user_dir / "123.json"
            json_path.write_text("{}", encoding="utf-8")

            paths = resolve_archive_paths(config_path=config_path)

            self.assertEqual(paths.user_id, "123")
            self.assertEqual(paths.json_path, json_path.resolve())
            self.assertEqual(paths.user_dir, user_dir.resolve())
            self.assertEqual(paths.image_dir, user_dir.resolve() / "img")
            self.assertEqual(paths.video_dir, user_dir.resolve() / "video")

    def test_user_id_list_txt_is_read_relative_to_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            user_list = Path(tmp) / "user_id_list.txt"
            user_list.write_text("123 name 2020-01-01\n456\n", encoding="utf-8")

            ids = user_ids_from_config({"user_id_list": "user_id_list.txt"}, config_path)

            self.assertEqual(ids, ["123", "456"])

    def test_explicit_user_id_overrides_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "weiboSpider"
            config_dir.mkdir()
            config_path = config_dir / "config.json"
            config_path.write_text(json.dumps({"user_id_list": ["old"]}), encoding="utf-8")
            user_dir = root / "目标"
            user_dir.mkdir()
            json_path = user_dir / "new.json"
            json_path.write_text("{}", encoding="utf-8")

            paths = resolve_archive_paths(config_path=config_path, user_id="new")

            self.assertEqual(paths.user_id, "new")
            self.assertEqual(paths.json_path, json_path.resolve())


if __name__ == "__main__":
    unittest.main()
