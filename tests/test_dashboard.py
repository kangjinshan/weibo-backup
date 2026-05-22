import asyncio
import json
import tempfile
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class _FakeFastAPI:
    def __init__(self, *args, **kwargs):
        pass

    def get(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator

    def post(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator


class _FakeJSONResponse:
    def __init__(self, content):
        self.body = json.dumps(content).encode("utf-8")


fastapi_module = types.ModuleType("fastapi")
fastapi_module.FastAPI = _FakeFastAPI
fastapi_module.HTTPException = Exception
responses_module = types.ModuleType("fastapi.responses")
responses_module.FileResponse = object
responses_module.HTMLResponse = str
responses_module.JSONResponse = _FakeJSONResponse
staticfiles_module = types.ModuleType("fastapi.staticfiles")
staticfiles_module.StaticFiles = object
sys.modules.setdefault("fastapi", fastapi_module)
sys.modules.setdefault("fastapi.responses", responses_module)
sys.modules.setdefault("fastapi.staticfiles", staticfiles_module)

from dashboard import server


class DashboardTests(unittest.TestCase):
    def test_weibo_list_returns_oldest_posts_first(self):
        data = {
            "user": {"id": "1234567890"},
            "weibo": [
                {"id": "new", "publish_time": "2026-05-21 10:00"},
                {"id": "old", "publish_time": "2024-01-01 10:00"},
                {"id": "middle", "publish_time": "2025-06-01 10:00"},
            ]
        }

        with (
            patch.object(server, "read_weibos_page", return_value=(server.sort_weibos_chronologically(data["weibo"]), 3)),
            patch.object(server, "get_user_info", return_value=data["user"]),
        ):
            response = asyncio.run(server.weibo_list(page=1, per_page=20))

        payload = json.loads(response.body)
        self.assertEqual([item["id"] for item in payload["weibo"]], ["old", "middle", "new"])
        self.assertEqual(payload["weibo"][0]["owner_user_id"], "1234567890")

    def test_find_user_dir_ignores_service_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logs").mkdir()
            (root / "logs" / "status.json").write_text('{"status": "completed"}', encoding="utf-8")
            (root / "archive").mkdir()
            (root / "测试账号").mkdir()
            (root / "测试账号" / "1234567890.json").write_text(
                json.dumps({"user": {"id": "1234567890"}, "weibo": []}),
                encoding="utf-8",
            )

            with patch.object(server, "DATA_DIR", root):
                self.assertEqual(server.find_user_dir(), root / "测试账号")

    def test_auto_refresh_updates_progress_without_reloading_weibo_list(self):
        html = (Path(__file__).parents[1] / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn("setInterval(refreshProgressOnly, 15000)", html)
        self.assertIn("async function refreshProgressOnly()", html)

    def test_backup_modal_exposes_config_and_process_controls(self):
        html = (Path(__file__).parents[1] / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")

        for expected in [
            "id=\"backupModal\"",
            "id=\"configUserIds\"",
            "id=\"configSinceDate\"",
            "id=\"configEndDate\"",
            "id=\"configPicDownload\"",
            "id=\"configVideoDownload\"",
            "/api/backup-config",
            "/api/backup/${action}",
            "startBackupFromModal",
            "backupAction('pause')",
            "backupAction('stop')",
        ]:
            self.assertIn(expected, html)

    def test_feed_links_lightbox_zoom_and_calendar_extremes_are_available(self):
        html = (Path(__file__).parents[1] / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")

        for expected in [
            "function weiboProfileUrl",
            "https://weibo.com/n/",
            "function weiboDetailUrl",
            "https://weibo.com/${ownerId}/${encodeURIComponent(weibo.id || '')}",
            "打开原文",
            "jumpToDateBoundary('first')",
            "jumpToDateBoundary('last')",
            "function zoomLightbox",
            "function resetLightboxZoom",
            "lightboxViewport",
            "event.target === this && closeLightbox()",
            "e.target !== document.getElementById('lightboxImg')",
            "wheel",
        ]:
            self.assertIn(expected, html)

    def test_keyboard_paging_month_boundary_and_adaptive_images_are_available(self):
        html = (Path(__file__).parents[1] / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")

        for expected in [
            "function navigatePage",
            "function jumpToAdjacentMonth",
            "hasAdjacentMonth(1)",
            "hasAdjacentMonth(-1)",
            "jumpToAdjacentMonth(1, 'first')",
            "jumpToAdjacentMonth(-1, 'last')",
            "e.key === 'ArrowLeft' || e.key === 'ArrowRight'",
            "navigatePage(e.key === 'ArrowLeft' ? -1 : 1)",
            "max-height: min(60vh, 520px)",
            "max-width: min(92vw, 1400px)",
            "max-height: min(86vh, 1000px)",
            "object-fit: contain",
        ]:
            self.assertIn(expected, html)

    def test_feed_filters_are_available(self):
        html = (Path(__file__).parents[1] / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")

        for expected in [
            "id=\"postTypeFilter\"",
            "setPostTypeFilter('original')",
            "id=\"mediaTypeFilter\"",
            "setMediaTypeFilter('text')",
            "setMediaTypeFilter('text_image')",
            "setMediaTypeFilter('text_image_video')",
            "post_type=${encodeURIComponent(postTypeFilter)}",
            "media_type=${encodeURIComponent(mediaTypeFilter)}",
        ]:
            self.assertIn(expected, html)

    def test_sanitize_backup_config_normalizes_web_form_values(self):
        current = {
            "user_id_list": ["old"],
            "filter": 0,
            "since_date": "2010-01-01",
            "end_date": "now",
            "write_mode": ["csv", "txt", "json", "sqlite"],
            "pic_download": 1,
            "video_download": 0,
            "cookie": "keep-cookie",
        }
        incoming = {
            "user_id_list": "123, 456",
            "since_date": "2020-01-02",
            "end_date": "2020-12-31",
            "pic_download": False,
            "video_download": True,
        }

        normalized = server.sanitize_backup_config(incoming, current)

        self.assertEqual(normalized["user_id_list"], ["123", "456"])
        self.assertEqual(normalized["since_date"], "2020-01-02")
        self.assertEqual(normalized["end_date"], "2020-12-31")
        self.assertEqual(normalized["pic_download"], 0)
        self.assertEqual(normalized["video_download"], 1)
        self.assertEqual(normalized["write_mode"], current["write_mode"])
        self.assertEqual(normalized["cookie"], "keep-cookie")

    def test_sanitize_backup_config_uses_now_for_today_end_date(self):
        current = {
            "user_id_list": ["old"],
            "since_date": "2010-01-01",
            "end_date": "2020-08-25",
            "pic_download": 1,
            "video_download": 0,
        }

        with patch.object(server, "today_string", return_value="2026-05-22", create=True):
            normalized = server.sanitize_backup_config(
                {"since_date": "2026-05-21", "end_date": "2026-05-22"},
                current,
            )

        self.assertEqual(normalized["since_date"], "2026-05-21")
        self.assertEqual(normalized["end_date"], "now")

    def test_backup_status_reports_paused_for_stopped_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_path = Path(tmp) / "backup.pid"
            pid_path.write_text("123\n", encoding="utf-8")
            with patch.object(server, "BACKUP_PID_PATH", pid_path), patch.object(server, "process_state", return_value="T"):
                status = server.get_backup_process_status()

        self.assertEqual(status["status"], "paused")
        self.assertTrue(status["running"])

    def test_backup_config_defaults_to_latest_backed_up_date_and_today(self):
        current_config = {
            "user_id_list": ["1234567890"],
            "since_date": "2010-01-01",
            "end_date": "2020-08-25",
            "write_mode": ["csv", "txt", "json", "sqlite"],
            "pic_download": 1,
            "video_download": 0,
        }
        with (
            patch.object(server, "read_backup_config", return_value=current_config),
            patch.object(server, "latest_backed_up_date", return_value="2020-03-04"),
            patch.object(server, "today_string", return_value="2026-05-22", create=True),
            patch.object(server, "get_backup_process_status", return_value={"running": False, "status": "stopped", "pid": None}),
        ):
            response = asyncio.run(server.backup_config())

        payload = json.loads(response.body)
        self.assertEqual(payload["since_date"], "2020-03-04")
        self.assertEqual(payload["end_date"], "2026-05-22")

    def test_spider_status_does_not_synthesize_progress_from_archive_count(self):
        with (
            patch.object(server, "process_state", return_value=""),
            patch.object(server, "get_user_info", return_value={"weibo_num": 39400}),
            patch.object(server, "sqlite_count_weibos", return_value=39385),
        ):
            status = server.get_spider_status()

        self.assertEqual(status["status"], "stopped")
        self.assertEqual(status["current_page"], 0)
        self.assertEqual(status["total_pages"], 0)

    def test_spider_status_reports_completed_backup_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            backup_log = tmp_path / "backup-run.log"
            backup_log.write_text("共爬取3条微博\n信息抓取完毕\n", encoding="utf-8")
            pid_path = tmp_path / "backup.pid"
            pid_path.write_text("123\n", encoding="utf-8")
            data = {"user": {"weibo_num": 10}, "weibo": [{"publish_time": "2026-05-21"}]}

            with (
                patch.object(server, "BACKUP_LOG_PATH", backup_log),
                patch.object(server, "BACKUP_PID_PATH", pid_path),
                patch.object(server, "process_state", return_value=""),
                patch.object(server, "get_user_info", return_value=data["user"]),
                patch.object(server, "sqlite_count_weibos", return_value=len(data["weibo"])),
            ):
                status = server.get_spider_status()

        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["last_run_weibo_count"], 3)


if __name__ == "__main__":
    unittest.main()
