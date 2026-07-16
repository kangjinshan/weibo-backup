import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
EXTENSION_DIR = ROOT / "chrome-extension"


class ChromeExtensionTests(unittest.TestCase):
    def test_manifest_uses_exact_manifest_v3_permissions(self):
        manifest = json.loads(
            (EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8")
        )

        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(manifest["minimum_chrome_version"], "92")
        self.assertEqual(
            set(manifest["permissions"]),
            {"activeTab", "cookies", "scripting"},
        )
        self.assertEqual(
            set(manifest["host_permissions"]),
            {
                "https://*.weibo.cn/*",
                "https://*.weibo.com/*",
                "https://weibo.jinshanweb.com:8765/*",
            },
        )
        self.assertEqual(manifest["action"]["default_popup"], "popup.html")
        self.assertNotIn("background", manifest)

    def test_popup_exposes_only_manual_fill_controls(self):
        html = (EXTENSION_DIR / "popup.html").read_text(encoding="utf-8")

        self.assertIn('id="fillCookieButton"', html)
        self.assertIn('id="status"', html)
        self.assertIn('type="module" src="popup.js"', html)
        self.assertNotIn("保存设置", html)

    def test_source_avoids_storage_clipboard_logging_and_backend_calls(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(EXTENSION_DIR.glob("*.js"))
        )

        for forbidden in (
            "chrome.storage",
            "localStorage",
            "indexedDB",
            "navigator.clipboard",
            "console.log",
            "fetch(",
            "/api/backup-config",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn('document.querySelector("#backupModal")', source)
        self.assertIn('document.querySelector("#configCookieInput")', source)


if __name__ == "__main__":
    unittest.main()
