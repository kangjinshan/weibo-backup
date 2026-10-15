import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from azure_session import server as broker
from cookie_broker_client import BrokerError, CookieBrokerClient, NoRedirect
from cookie_health import classify_page
from dashboard import server


VALID = {'state': 'valid', 'valid': True, 'message': 'ok'}
EXPIRED = {'state': 'expired', 'valid': False, 'message': 'expired'}


class CookiePolicyTests(unittest.TestCase):
    def test_cookie_header_keeps_domain_path_and_expiry_boundaries(self):
        cookies = [
            {'name': 'SUB', 'value': 'cn', 'domain': '.weibo.cn', 'path': '/', 'expires': -1},
            {'name': 'SUB', 'value': 'com', 'domain': '.weibo.com', 'path': '/', 'expires': -1},
            {'name': 'old', 'value': 'expired', 'domain': '.weibo.cn', 'path': '/', 'expires': 1},
            {'name': 'private', 'value': 'wrong-path', 'domain': '.weibo.cn', 'path': '/settings'},
            {'name': 'elsewhere', 'value': 'other', 'domain': '.example.com', 'path': '/'},
        ]
        self.assertEqual(broker.cookie_header(cookies), 'SUB=cn')

    def test_network_and_rate_limits_are_not_login_expiry(self):
        self.assertEqual(classify_page('https://weibo.cn/12345/info', '', 429)['state'], 'rate_limited')
        self.assertIsNone(classify_page('https://weibo.cn/12345/info', '<title>维护中</title>')['valid'])
        self.assertEqual(classify_page('https://passport.weibo.com/sso/signin', '')['state'], 'expired')

    def test_client_rejects_non_https_and_redirects(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            for url in ['http://example.com', 'https://user:password@example.com', 'https://example.com/?secret=x']:
                path.write_text(json.dumps({'url': url, 'token': 'test-token-' * 5}))
                with self.assertRaises(BrokerError):
                    CookieBrokerClient(path)
        self.assertIsNone(NoRedirect().redirect_request(None, None, None, None, None, None))


class NASRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({'cookie': 'SUB=old', 'user_id_list': ['1234567890'], 'since_date': '2020-01-01'}))
        for name, value in [('CONFIG_PATH', self.config), ('LOGS_DIR', self.root), ('COOKIE_SESSION_STATUS', {})]:
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_valid_local_cookie_does_not_fetch_azure(self):
        with patch.object(server, 'broker_configured', return_value=True), patch.object(server, 'inspect_cookie_health', return_value=VALID), patch.object(server, 'acquire_azure_cookie') as acquire:
            self.assertTrue(server.ensure_backup_cookie(server.read_backup_config()))
            acquire.assert_not_called()

    def test_expired_cookie_is_verified_before_persisting(self):
        with patch.object(server, 'broker_configured', return_value=True), patch.object(server, 'inspect_cookie_health', side_effect=[EXPIRED, VALID]), patch.object(CookieBrokerClient, '__init__', return_value=None), patch.object(CookieBrokerClient, 'cookie', return_value='SUB=new'):
            self.assertTrue(server.ensure_backup_cookie(server.read_backup_config()))
        self.assertEqual(server.read_backup_config()['cookie'], 'SUB=new')
        self.assertEqual(server.read_backup_config()['since_date'], '2020-01-01')
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('SUB=', json.dumps(server.COOKIE_SESSION_STATUS))

    def test_cookie_rejected_on_nas_preserves_original_file(self):
        before = self.config.read_bytes()
        with patch.object(server, 'inspect_cookie_health', return_value=EXPIRED), patch.object(CookieBrokerClient, '__init__', return_value=None), patch.object(CookieBrokerClient, 'cookie', return_value='SUB=rejected'):
            ok, _ = server.acquire_azure_cookie(server.read_backup_config())
        self.assertFalse(ok)
        self.assertEqual(self.config.read_bytes(), before)

    def test_broker_outage_and_unknown_probe_preserve_credentials(self):
        before = self.config.read_bytes()
        with patch.object(server, 'broker_configured', return_value=True), patch.object(server, 'inspect_cookie_health', return_value=EXPIRED), patch.object(server, 'acquire_azure_cookie', side_effect=BrokerError('unavailable')):
            self.assertFalse(server.ensure_backup_cookie(server.read_backup_config()))
        with patch.object(server, 'broker_configured', return_value=True), patch.object(server, 'inspect_cookie_health', return_value={'state': 'unknown', 'valid': None}), patch.object(server, 'acquire_azure_cookie') as acquire:
            self.assertFalse(server.ensure_backup_cookie(server.read_backup_config()))
            acquire.assert_not_called()
        self.assertEqual(self.config.read_bytes(), before)

    def test_single_launcher_lock_prevents_second_process(self):
        with server.BACKUP_LAUNCH_LOCK, patch.object(server, 'launch_backup_process_locked') as launch:
            result, _ = server.launch_backup_process()
        self.assertFalse(result['ok'])
        launch.assert_not_called()

    def test_zombie_is_not_a_running_backup(self):
        with patch.object(server, 'read_pid', return_value=123), patch.object(server, 'process_state', return_value='Z'):
            self.assertEqual(server.get_backup_process_status()['status'], 'stopped')

    def test_linux_status_uses_procfs_not_busybox_ps(self):
        with patch.object(server.sys, 'platform', 'linux'), patch.object(Path, 'read_text', return_value='123 (name with spaces) T 1 2 3'), patch.object(server.subprocess, 'run') as ps:
            self.assertEqual(server.process_state(123), 'T')
            ps.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'POSIX process control')
    def test_real_process_pause_resume_and_stop_while_paused(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
        pidfile = self.root / 'backup.pid'
        pidfile.write_text(str(child.pid))
        def wait_state(expected):
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if server.get_backup_process_status()['status'] == expected:
                    return
                time.sleep(.05)
            self.fail('process did not reach ' + expected)
        try:
            with patch.object(server, 'BACKUP_PID_PATH', pidfile):
                wait_state('running')
                asyncio.run(server.pause_backup())
                wait_state('paused')
                asyncio.run(server.resume_backup())
                wait_state('running')
                asyncio.run(server.pause_backup())
                wait_state('paused')
                asyncio.run(server.stop_backup())
                child.wait(timeout=3)
                wait_state('stopped')
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


class HTTPAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_media_and_login_routes_require_auth_and_block_private_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account = root / 'account'
            (account / 'img').mkdir(parents=True)
            (account / '1234567890.json').write_text('{}')
            (account / 'img' / 'ok.jpg').write_bytes(b'image')
            (root / 'logs').mkdir()
            (root / 'logs' / 'private.jpg').write_bytes(b'private')
            (account / 'img' / 'link.jpg').symlink_to(root / 'logs' / 'private.jpg')
            with patch.object(server, 'DATA_DIR', root), patch.object(server, 'AUTH_CONFIG_PATH', root / 'auth.json'):
                auth = server.create_dashboard_auth_config('a-long-test-password')
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://test') as client:
                    response = await client.get('/azure-login')
                    self.assertEqual(response.status_code, 303)
                    self.assertEqual(response.headers['location'], '/?next=/azure-login')
                    for path in ['/api/azure-session/frame', '/media/account/img/ok.jpg']:
                        self.assertEqual((await client.get(path)).status_code, 401)
                    client.cookies.set(server.AUTH_COOKIE_NAME, server.create_dashboard_session_cookie(auth))
                    self.assertEqual((await client.get('/media/account/img/ok.jpg')).content, b'image')
                    for path in ['/media/logs/private.jpg', '/media/account/img/link.jpg', '/media/account/1234567890.json', '/media/auth.json']:
                        self.assertEqual((await client.get(path)).status_code, 404)
                    with patch.object(server, 'broker_configured', return_value=True), patch.object(server, 'inspect_cookie_health', return_value=EXPIRED), patch.object(server, 'read_backup_config', return_value={'cookie': 'SUB=old', 'user_id_list': ['1234567890']}), patch.object(server, 'acquire_azure_cookie', return_value=(True, VALID)):
                        response = await client.post('/api/backup/refresh-cookie', json={})
                        self.assertEqual(response.status_code, 200)
                        self.assertNotIn('SUB=', response.text)

    async def test_broker_requires_machine_token_and_returns_no_cookie_on_expiry(self):
        broker.app.state.token = 'synthetic-machine-token-' * 3
        with patch.object(broker.session, 'state', EXPIRED), patch.object(broker.session, 'refresh', new=AsyncMock(return_value=EXPIRED)):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=broker.app), base_url='http://test') as client:
                for path in ['/v1/cookie', '/v1/session', '/v1/login/frame']:
                    self.assertEqual((await client.get(path)).status_code, 401)
                response = await client.get('/v1/cookie', headers={'Authorization': 'Bearer ' + broker.app.state.token})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json(), {'code': 'login_required'})
                self.assertEqual(response.headers['cache-control'], 'no-store')
