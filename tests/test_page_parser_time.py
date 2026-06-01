import unittest
from datetime import datetime as real_datetime
from unittest.mock import patch

from lxml import etree

from weiboSpider.weibo_spider.parser import page_parser


class _FakeDateTime:
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return real_datetime(2026, 5, 31, 16, 10)
        return real_datetime(2026, 6, 1, 0, 10, tzinfo=tz)


def _info_with_time(text):
    selector = etree.HTML(f"<div class='c'><div><span class='ct'>{text}</span></div></div>")
    return selector.xpath("//div[@class='c']")[0]


class PageParserTimeTests(unittest.TestCase):
    def setUp(self):
        self.parser = page_parser.PageParser.__new__(page_parser.PageParser)

    def test_relative_publish_times_use_shanghai_timezone(self):
        with patch.object(page_parser, "datetime", _FakeDateTime):
            self.assertEqual(
                self.parser.get_publish_time(_info_with_time("今天 00:05 来自 Xiaomi 14")),
                "2026-06-01 00:05",
            )
            self.assertEqual(
                self.parser.get_publish_time(_info_with_time("1分钟前 来自 Xiaomi 14")),
                "2026-06-01 00:09",
            )


if __name__ == "__main__":
    unittest.main()
