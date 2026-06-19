import importlib.util
import json
import unittest
from pathlib import Path


def load_cookie_helper():
    script_path = Path(__file__).parents[1] / "scripts" / "cookie_helper.py"
    spec = importlib.util.spec_from_file_location("cookie_helper", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CookieHelperTests(unittest.TestCase):
    def test_allows_dashboard_origin_only(self):
        helper = load_cookie_helper()

        self.assertTrue(helper.is_allowed_origin("https://weibo.jinshanweb.com:8765"))
        self.assertTrue(helper.is_allowed_origin("http://127.0.0.1:8765"))
        self.assertFalse(helper.is_allowed_origin("https://example.com"))

    def test_valid_cookie_payload_returns_cookie_for_local_dashboard(self):
        helper = load_cookie_helper()

        payload, status = helper.build_cookie_payload(
            "1639733600",
            cookie_reader=lambda: ("SUB=new-cookie", None),
            cookie_inspector=lambda cookie, probe_url: {
                "state": "valid",
                "valid": True,
                "message": "Cookie 有效",
                "probe_url": probe_url,
            },
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["cookie"], "SUB=new-cookie")
        self.assertEqual(payload["cookie_status"]["state"], "valid")

    def test_invalid_cookie_payload_does_not_leak_cookie(self):
        helper = load_cookie_helper()

        payload, status = helper.build_cookie_payload(
            "1639733600",
            cookie_reader=lambda: ("SUB=expired-cookie", None),
            cookie_inspector=lambda cookie, probe_url: {
                "state": "expired",
                "valid": False,
                "message": "Cookie 疑似已过期",
                "probe_url": probe_url,
            },
        )

        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertNotIn("expired-cookie", json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
