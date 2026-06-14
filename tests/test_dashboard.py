import asyncio
import base64
import json
import tempfile
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
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

    def middleware(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator


class _FakeJSONResponse:
    def __init__(self, content, status_code=200):
        self.body = json.dumps(content).encode("utf-8")
        self.status_code = status_code


fastapi_module = types.ModuleType("fastapi")
fastapi_module.FastAPI = _FakeFastAPI
fastapi_module.HTTPException = Exception
fastapi_module.Request = object
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
            "id=\"configCookieStatus\"",
            "id=\"configCookieHealth\"",
            "id=\"configCookieInput\"",
            "id=\"configSinceDate\"",
            "id=\"configEndDate\"",
            "id=\"configPicDownload\"",
            "id=\"configVideoDownload\"",
            "/api/backup-config",
            "/api/backup/refresh-cookie",
            "refreshCookieAutomatically",
            "/api/backup/${action}",
            "startBackupFromModal",
            "backupAction('pause')",
            "backupAction('stop')",
        ]:
            self.assertIn(expected, html)

    def test_api_helpers_report_non_json_errors(self):
        html = (Path(__file__).parents[1] / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")

        for expected in [
            "async function parseJSONResponse",
            "await response.text()",
            "response.ok",
            "throw new Error(message)",
        ]:
            self.assertIn(expected, html)

    def test_dashboard_auth_config_uses_local_hash_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth_path = Path(tmp) / "dashboard-auth.json"
            with patch.object(server, "AUTH_CONFIG_PATH", auth_path):
                self.assertFalse(server.dashboard_auth_configured())
                auth_config = server.create_dashboard_auth_config("correct horse battery staple")

                saved_text = auth_path.read_text(encoding="utf-8")
                saved = json.loads(saved_text)

        self.assertTrue(saved["password_hash"])
        self.assertTrue(saved["password_salt"])
        self.assertNotIn("correct horse", saved_text)
        self.assertEqual(saved["password_hash"], auth_config["password_hash"])
        self.assertTrue(server.verify_dashboard_password("correct horse battery staple", saved))
        self.assertFalse(server.verify_dashboard_password("wrong password", saved))

    def test_dashboard_auth_rejects_short_first_password(self):
        with self.assertRaises(ValueError):
            server.create_dashboard_auth_config("short")

    def test_dashboard_session_cookie_is_signed_and_expires(self):
        auth_config = {
            "session_secret": base64.urlsafe_b64encode(b"test-secret").decode("ascii"),
        }
        now = datetime(2026, 5, 23, tzinfo=timezone.utc)

        with patch.object(server, "utc_now", return_value=now):
            cookie = server.create_dashboard_session_cookie(auth_config)
            self.assertTrue(server.valid_dashboard_session_cookie(cookie, auth_config))
            self.assertFalse(server.valid_dashboard_session_cookie(cookie + "tampered", auth_config))

        with patch.object(server, "utc_now", return_value=now + timedelta(days=15)):
            self.assertFalse(server.valid_dashboard_session_cookie(cookie, auth_config))

    def test_dashboard_auth_path_rules_protect_data_endpoints(self):
        self.assertFalse(server.dashboard_path_requires_auth("/"))
        self.assertFalse(server.dashboard_path_requires_auth("/api/auth/status"))
        self.assertFalse(server.dashboard_path_requires_auth("/api/auth/login"))
        self.assertFalse(server.dashboard_path_requires_auth("/api/auth/setup"))
        self.assertTrue(server.dashboard_path_requires_auth("/api/stats"))
        self.assertTrue(server.dashboard_path_requires_auth("/api/backup/start"))
        self.assertTrue(server.dashboard_path_requires_auth("/media/账号/img/a.jpg"))

    def test_auth_ui_is_available(self):
        html = (Path(__file__).parents[1] / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")

        for expected in [
            "id=\"authGate\"",
            "id=\"authPassword\"",
            "id=\"authPasswordConfirm\"",
            "id=\"logoutButton\"",
            "async function loadAuthStatus",
            "async function submitAuth",
            "/api/auth/status",
            "/api/auth/setup",
            "/api/auth/login",
            "/api/auth/logout",
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

    def test_sanitize_backup_config_updates_cookie_only_when_provided(self):
        current = {
            "user_id_list": ["123"],
            "cookie": "SUB=old-cookie",
        }

        self.assertEqual(
            server.sanitize_backup_config({"cookie": "   "}, current)["cookie"],
            "SUB=old-cookie",
        )
        self.assertEqual(
            server.sanitize_backup_config({"cookie": "SUB=new-cookie"}, current)["cookie"],
            "SUB=new-cookie",
        )

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
            "cookie": "SUB=valid-cookie",
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
        self.assertTrue(payload["cookie_configured"])
        self.assertEqual(payload["config_issues"], [])
        self.assertIn("cookie_status", payload)

    def test_backup_config_reports_placeholder_cookie_without_exposing_value(self):
        current_config = {
            "user_id_list": ["1234567890"],
            "since_date": "2010-01-01",
            "end_date": "now",
            "write_mode": ["csv", "txt", "json", "sqlite"],
            "pic_download": 1,
            "video_download": 0,
            "cookie": "PASTE_YOUR_WEIBO_COOKIE_HERE",
        }

        with (
            patch.object(server, "read_backup_config", return_value=current_config),
            patch.object(server, "latest_backed_up_date", return_value=None),
            patch.object(server, "today_string", return_value="2026-05-22", create=True),
            patch.object(server, "get_backup_process_status", return_value={"running": False, "status": "stopped", "pid": None}),
        ):
            response = asyncio.run(server.backup_config())

        payload = json.loads(response.body)
        self.assertFalse(payload["cookie_configured"])
        self.assertIn("cookie", payload["config_issues"][0])
        self.assertNotIn("PASTE_YOUR_WEIBO_COOKIE_HERE", response.body.decode("utf-8"))

    def test_start_backup_refuses_to_run_without_configured_cookie(self):
        current_config = {
            "user_id_list": ["1234567890"],
            "cookie": "PASTE_YOUR_WEIBO_COOKIE_HERE",
            "write_mode": ["csv", "txt", "json", "sqlite"],
        }

        with (
            patch.object(server, "read_backup_config", return_value=current_config),
            patch.object(server, "get_backup_process_status", return_value={"running": False, "status": "stopped", "pid": None}),
            patch.object(server.subprocess, "Popen") as popen,
        ):
            response = asyncio.run(server.start_backup())

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("cookie", payload["message"])
        self.assertFalse(popen.called)

    def test_save_backup_config_returns_cookie_status_without_exposing_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.json"
            config_path.write_text(
                json.dumps({
                    "user_id_list": ["1234567890"],
                    "cookie": "PASTE_YOUR_WEIBO_COOKIE_HERE",
                    "write_mode": ["sqlite"],
                }),
                encoding="utf-8",
            )

            with (
                patch.object(server, "CONFIG_PATH", config_path),
                patch.object(server, "LOGS_DIR", tmp_path),
            ):
                response = asyncio.run(server.save_backup_config({"cookie": "SUB=new-cookie"}))

        payload = json.loads(response.body)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["cookie_configured"])
        self.assertEqual(payload["config_issues"], [])
        self.assertIn("cookie_status", payload)
        self.assertNotIn("SUB=new-cookie", response.body.decode("utf-8"))

    def test_cookie_health_reports_expired_when_redirected_to_login(self):
        class _FakeResponse:
            def __init__(self, url: str, body: str):
                self._url = url
                self._body = body.encode("utf-8")

            def geturl(self):
                return self._url

            def read(self, *_args, **_kwargs):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch.object(
            server.urllib_request,
            "urlopen",
            return_value=_FakeResponse(
                "https://passport.weibo.com/sso/login",
                "<html><title>新浪通行证</title></html>",
            ),
        ):
            status = server.inspect_cookie_health("SUB=token", "https://weibo.cn/1639733600/info")

        self.assertEqual(status["state"], "expired")
        self.assertFalse(status["valid"])

    def test_refresh_cookie_uses_chrome_cookie_when_current_is_expired(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "user_id_list": ["1639733600"],
                        "cookie": "SUB=old-cookie",
                        "write_mode": ["sqlite"],
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(server, "CONFIG_PATH", config_path),
                patch.object(server, "SPIDER_DIR", tmp_path),
                patch.object(server, "LOGS_DIR", tmp_path),
                patch.object(
                    server,
                    "inspect_cookie_health",
                    side_effect=[
                        {"state": "expired", "valid": False, "message": "expired"},
                        {"state": "valid", "valid": True, "message": "valid"},
                    ],
                ),
                patch.object(server, "get_chrome_cookie_string", return_value=("SUB=new-cookie", None)),
            ):
                response = asyncio.run(server.refresh_cookie())
                saved = json.loads(config_path.read_text(encoding="utf-8"))

        payload = json.loads(response.body)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["updated"])
        self.assertEqual(payload["source"], "chrome")
        self.assertEqual(saved["cookie"], "SUB=new-cookie")
        self.assertNotIn("SUB=new-cookie", response.body.decode("utf-8"))

    def test_refresh_cookie_returns_error_when_no_valid_source(self):
        current_config = {
            "user_id_list": ["1639733600"],
            "cookie": "SUB=old-cookie",
            "write_mode": ["sqlite"],
        }
        with (
            patch.object(server, "read_backup_config", return_value=current_config),
            patch.object(server, "inspect_cookie_health", return_value={"state": "expired", "valid": False, "message": "expired"}),
            patch.object(server, "get_chrome_cookie_string", return_value=(None, "chrome unavailable")),
            patch.object(server, "iter_backup_cookie_candidates", return_value=[]),
        ):
            response = asyncio.run(server.refresh_cookie())

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("自动获取失败", payload["message"])

    def test_spider_command_skips_non_executable_venv_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            spider_dir = tmp_path / "weiboSpider"
            stale_python = spider_dir / "venv" / "bin" / "python"
            stale_python.parent.mkdir(parents=True)
            stale_python.write_text("#!/bin/sh\n", encoding="utf-8")
            stale_python.chmod(0o644)

            with (
                patch.object(server, "SPIDER_PYTHON", None),
                patch.object(server, "ROOT_VENV_PYTHON", tmp_path / ".venv" / "bin" / "python"),
                patch.object(server, "SPIDER_DIR", spider_dir),
                patch.object(server, "CONFIG_PATH", spider_dir / "config.json"),
                patch.object(server, "BACKUP_DIR", tmp_path),
            ):
                command = server.spider_command()

        self.assertEqual(command[0], sys.executable)

    def test_spider_command_skips_python_that_cannot_be_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            spider_dir = tmp_path / "weiboSpider"
            stale_python = spider_dir / "venv" / "bin" / "python"
            stale_python.parent.mkdir(parents=True)
            stale_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            stale_python.chmod(0o755)

            def fake_run(command, *args, **kwargs):
                if command[0] == str(stale_python):
                    raise PermissionError("Permission denied")
                return types.SimpleNamespace(returncode=0)

            with (
                patch.object(server, "SPIDER_PYTHON", stale_python),
                patch.object(server, "ROOT_VENV_PYTHON", tmp_path / ".venv" / "bin" / "python"),
                patch.object(server, "SPIDER_DIR", spider_dir),
                patch.object(server, "CONFIG_PATH", spider_dir / "config.json"),
                patch.object(server, "BACKUP_DIR", tmp_path),
                patch.object(server.subprocess, "run", side_effect=fake_run),
            ):
                command = server.spider_command()

        self.assertEqual(command[0], sys.executable)

    def test_spider_status_does_not_synthesize_progress_from_archive_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with (
                patch.object(server, "BACKUP_DIR", tmp_path),
                patch.object(server, "SPIDER_DIR", tmp_path / "weiboSpider"),
                patch.object(server, "BACKUP_LOG_PATH", tmp_path / "backup-run.log"),
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

    def test_start_backup_returns_json_when_process_fails_to_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with (
                patch.object(server, "LOGS_DIR", tmp_path),
                patch.object(server, "BACKUP_LOG_PATH", tmp_path / "backup-run.log"),
                patch.object(server, "BACKUP_PID_PATH", tmp_path / "backup.pid"),
                patch.object(server, "read_backup_config", return_value={"user_id_list": ["1234567890"], "cookie": "SUB=valid-cookie"}),
                patch.object(server, "get_backup_process_status", return_value={"running": False, "status": "stopped", "pid": None}),
                patch.object(server.subprocess, "Popen", side_effect=OSError("Exec format error")),
            ):
                response = asyncio.run(server.start_backup())

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 500)
        self.assertFalse(payload["ok"])
        self.assertIn("启动失败", payload["message"])
        self.assertIn("Exec format error", payload["message"])


if __name__ == "__main__":
    unittest.main()
