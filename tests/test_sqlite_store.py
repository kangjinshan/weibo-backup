import json
import tempfile
import unittest
from pathlib import Path

from sqlite_store import date_counts, fetch_weibos, get_user, latest_publish_date, replace_from_json


class SqliteStoreTests(unittest.TestCase):
    def test_replace_from_json_and_fetch_weibos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / "123.json"
            db_path = root / "weibo.db"
            json_path.write_text(
                json.dumps(
                    {
                        "user": {"id": "123", "nickname": "测试用户", "weibo_num": 2},
                        "weibo": [
                            {
                                "id": "new",
                                "content": "new post",
                                "publish_time": "2026-02-01 10:00",
                                "original_pictures_list": ["https://img/new.jpg"],
                                "media": {"video": [{"path": "测试/video/new.mp4"}]},
                            },
                            {
                                "id": "old",
                                "content": "old post",
                                "publish_time": "2025-01-01 10:00",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = replace_from_json(json_path, db_path)
            weibos, total = fetch_weibos(db_path, page=1, per_page=20)

            self.assertEqual(result["weibo_count"], 2)
            self.assertEqual(total, 2)
            self.assertEqual([item["id"] for item in weibos], ["old", "new"])
            self.assertEqual(weibos[1]["original_pictures_list"], ["https://img/new.jpg"])
            self.assertEqual(weibos[1]["media"], {"video": [{"path": "测试/video/new.mp4"}]})
            self.assertEqual(get_user(db_path)["nickname"], "测试用户")
            self.assertEqual(latest_publish_date(db_path), "2026-02-01")
            self.assertEqual(date_counts(db_path), {"2025-01-01": 1, "2026-02-01": 1})


if __name__ == "__main__":
    unittest.main()
