"""NAS-only HTTPS client. Credentials and Cookie values never enter UI status."""
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MESSAGES = {
    'not_configured': '尚未配置 Azure 微博会话服务',
    'unavailable': '暂时无法连接 Azure 微博会话服务',
    'unauthorized': 'Azure 会话服务认证失败，请检查服务配置',
    'login_required': 'Azure 微博登录已失效，请打开 Azure 登录页扫码',
    'verification_required': 'Azure 微博需要在登录页完成验证',
    'unknown': 'Azure 暂时无法确认微博登录状态',
    'invalid_response': 'Azure 会话服务返回了无效响应',
}


class BrokerError(Exception):
    def __init__(self, code):
        self.code = code if code in MESSAGES else 'unavailable'
        super().__init__(MESSAGES[self.code])


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class CookieBrokerClient:
    def __init__(self, config_path):
        try:
            config = json.loads(Path(config_path).read_text(encoding='utf-8'))
            self.base = str(config['url']).rstrip('/')
            self.token = str(config['token'])
            url = urlsplit(self.base)
            if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or len(self.token) < 32:
                raise ValueError()
        except Exception:
            raise BrokerError('not_configured') from None
        self.opener = build_opener(NoRedirect())

    def request(self, path, payload=None, binary=False):
        # Every caller supplies a constant path; redirects are never followed.
        req = Request(self.base + path, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            with self.opener.open(req, timeout=45) as response:
                data = response.read(2_000_001)
                if len(data) > 2_000_000:
                    raise BrokerError('invalid_response')
                if binary:
                    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                        raise BrokerError('invalid_response')
                    return data
                result = json.loads(data)
                if not isinstance(result, dict):
                    raise BrokerError('invalid_response')
                return result
        except HTTPError as exc:
            code = 'unauthorized' if exc.code in (401, 403) else 'unavailable'
            if exc.code == 409:
                try:
                    code = json.loads(exc.read(4096)).get('code', 'login_required')
                except Exception:
                    code = 'login_required'
            exc.close()
            raise BrokerError(code) from None
        except BrokerError:
            raise
        except Exception:
            raise BrokerError('unavailable') from None

    def cookie(self):
        result = self.request('/v1/cookie')
        cookie = result.get('cookie')
        if not isinstance(cookie, str) or not cookie or len(cookie) > 65536 or '\r' in cookie or '\n' in cookie:
            raise BrokerError('invalid_response')
        return cookie

    def status(self):
        result = self.request('/v1/session')
        allowed_states = {'valid', 'expired', 'missing', 'unknown', 'rate_limited', 'verification_required', 'starting'}
        state = result.get('state')
        return {'configured': True, 'state': state if state in allowed_states else 'unknown',
                'valid': result.get('valid') is True, 'checked_at': result.get('checked_at'),
                'login_url': '/azure-login'}
