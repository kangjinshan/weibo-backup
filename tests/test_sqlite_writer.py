import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "weiboSpider"))

from weibo_spider.weibo import Weibo
from weibo_spider.writer.sqlite_writer import SqliteWriter


class SqliteWriterTests(unittest.TestCase):
    def test_existing_weibo_table_is_migrated_before_insert(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "weibo.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE weibo (
                        id varchar(10) NOT NULL,
                        user_id varchar(12),
                        content varchar(2000),
                        article_url varchar(200),
                        original_pictures varchar(3000),
                        retweet_pictures varchar(3000),
                        original BOOLEAN NOT NULL DEFAULT 1,
                        video_url varchar(300),
                        publish_place varchar(100),
                        publish_time DATETIME NOT NULL,
                        publish_tool varchar(30),
                        up_num INT NOT NULL,
                        retweet_num INT NOT NULL,
                        comment_num INT NOT NULL,
                        PRIMARY KEY (id)
                    )
                    """
                )
                connection.commit()
            finally:
                connection.close()

            writer = SqliteWriter(str(db_path))
            writer.user = SimpleNamespace(id="1234567890")
            weibo = Weibo()
            weibo.id = "R0u0"
            weibo.content = "增量测试"
            weibo.article_url = ""
            weibo.original_pictures = "无"
            weibo.retweet_pictures = "无"
            weibo.original_pictures_list = []
            weibo.retweet_pictures_list = []
            weibo.media = {}
            weibo.original = True
            weibo.video_url = "无"
            weibo.publish_place = "无"
            weibo.publish_time = "2026-05-21 23:23"
            weibo.publish_tool = "Web"
            weibo.up_num = 0
            weibo.retweet_num = 0
            weibo.comment_num = 0

            writer.write_weibo([weibo])

            connection = sqlite3.connect(db_path)
            try:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(weibo)")}
                row = connection.execute("SELECT id, content FROM weibo WHERE id = ?", ("R0u0",)).fetchone()
            finally:
                connection.close()

        self.assertIn("original_pictures_list", columns)
        self.assertIn("retweet_pictures_list", columns)
        self.assertIn("media", columns)
        self.assertEqual(row, ("R0u0", "增量测试"))


if __name__ == "__main__":
    unittest.main()
