"""Private browser broker; public access requires the NAS machine credential."""
import asyncio
import hashlib
import hmac
import os
import re
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from cookie_health import probe_cookie

USER_ID = os.environ.get('WEIBO_SESSION_USER_ID', '1639733600')
PROFILE = Path(os.environ.get('WEIBO_SESSION_PROFILE', '/var/lib/weibo-session/profile'))
TOKEN_FILE = Path(os.environ.get('WEIBO_SESSION_TOKEN_FILE', '/var/lib/weibo-session/token'))
INTERVAL = max(300, int(os.environ.get('WEIBO_SESSION_INTERVAL_SECONDS', '1800')))
VIEWPORT = {'width': 1100, 'height': 820}
PROBE_URL = f'https://weibo.cn/{USER_ID}/info'


def cookie_header(cookies, host='weibo.cn'):
    selected = {}
    # Preserve domain boundaries; prefer the most specific matching domain/path.
    for item in sorted(cookies, key=lambda c: (len(c.get('domain', '')), len(c.get('path', '/'))), reverse=True):
        domain = item.get('domain', '').lstrip('.')
        if host != domain and not host.endswith('.' + domain):
            continue
        if not f'/{USER_ID}/info'.startswith(item.get('path', '/')):
            continue
        expires = item.get('expires', -1)
        if expires > 0 and expires <= time.time():
            continue
        name, value = item.get('name', ''), item.get('value', '')
        if name and not any(c in name + value for c in '\r\n;'):
            selected.setdefault(name, value)
    return '; '.join(f'{name}={value}' for name, value in sorted(selected.items()))


class BrowserSession:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.context = self.page = self.playwright = None
        self.state = {'state': 'starting', 'valid': None, 'checked_at': None}
        self.last_check = 0
        self.operator_until = 0
        self.com_cookie_digest = ''
        self.current_cookie = ''

    async def ensure_browser(self):
        if self.context is not None:
            return
        from playwright.async_api import async_playwright
        PROFILE.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.playwright = await async_playwright().start()
        try:
            self.context = await self.playwright.chromium.launch_persistent_context(
                str(PROFILE), headless=True, chromium_sandbox=True,
                viewport=VIEWPORT, locale='zh-CN', timezone_id='Asia/Shanghai',
                args=['--disable-dev-shm-usage'],
            )
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            self.page.set_default_timeout(15000)
            self.page.set_default_navigation_timeout(25000)
            await self.page.goto(PROBE_URL, wait_until='domcontentloaded')
        except Exception:
            await self.close()
            raise

    async def close(self):
        if self.context:
            with suppress(Exception):
                await self.context.close()
        if self.playwright:
            with suppress(Exception):
                await self.playwright.stop()
        self.context = self.page = self.playwright = None

    async def refresh(self, navigate=False):
        async with self.lock:
            try:
                await self.ensure_browser()
                cookies = await self.context.cookies()
                com = cookie_header(cookies, 'weibo.com')
                digest = hashlib.sha256(com.encode()).hexdigest() if com else ''
                # Exchange a newly logged-in .com session for the actual .cn crawler session.
                exchange = digest and digest != self.com_cookie_digest and any(c.get('name') == 'SUB' and c.get('domain', '').lstrip('.') == 'weibo.com' for c in cookies)
                if exchange or (navigate and self.state.get('valid') is True and time.monotonic() > self.operator_until):
                    await self.page.goto(PROBE_URL, wait_until='domcontentloaded')
                    cookies = await self.context.cookies()
                self.com_cookie_digest = digest
                candidate = cookie_header(cookies)
                health = await asyncio.to_thread(probe_cookie, candidate, USER_ID)
                self.current_cookie = candidate if health['valid'] is True else ''
                self.state = {**health, 'checked_at': datetime.now(timezone.utc).isoformat()}
                self.last_check = time.monotonic()
            except Exception:
                # Never log Playwright request details, pages, credentials, or exception text.
                self.current_cookie = ''
                self.state = {'state': 'unknown', 'valid': None, 'checked_at': datetime.now(timezone.utc).isoformat()}
                self.last_check = time.monotonic()
                if self.page is not None and self.page.is_closed():
                    await self.close()
            return dict(self.state)

    async def run(self):
        while True:
            await self.refresh(navigate=True)
            await asyncio.sleep(10 if time.monotonic() < self.operator_until else INTERVAL)


session = BrowserSession()


@asynccontextmanager
async def lifespan(_app):
    token = TOKEN_FILE.read_text().strip()
    if len(token) < 32 or not re.fullmatch(r'\d{5,20}', USER_ID):
        raise RuntimeError('Session service configuration is invalid')
    _app.state.token = token
    task = asyncio.create_task(session.run())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await session.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def authenticate(request: Request, call_next):
    if request.url.path != '/healthz':
        supplied = request.headers.get('Authorization', '')
        expected = 'Bearer ' + getattr(app.state, 'token', '')
        if not getattr(app.state, 'token', '') or not hmac.compare_digest(supplied.encode(), expected.encode()):
            return JSONResponse({'code': 'unauthorized'}, status_code=401)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.get('/healthz')
async def healthz():
    return {'ok': True}


@app.get('/v1/session')
async def status():
    if time.monotonic() - session.last_check > 60:
        await session.refresh()
    return dict(session.state)


@app.get('/v1/cookie')
async def cookie():
    await session.refresh(navigate=True)
    if session.state.get('valid') is not True:
        state = session.state.get('state')
        code = 'login_required' if state in {'expired', 'missing'} else 'verification_required' if state == 'verification_required' else 'unknown'
        return JSONResponse({'code': code}, status_code=409)
    return {'cookie': session.current_cookie}


@app.post('/v1/login/start')
async def start_login():
    async with session.lock:
        try:
            await session.ensure_browser()
            session.operator_until = time.monotonic() + 900
            await session.page.goto(PROBE_URL, wait_until='domcontentloaded')
        except Exception:
            return JSONResponse({'code': 'unavailable'}, status_code=503)
    return {'ok': True}


@app.get('/v1/login/frame')
async def frame():
    async with session.lock:
        try:
            await session.ensure_browser()
            session.operator_until = time.monotonic() + 900
            data = await session.page.screenshot(type='png')
            return Response(data, media_type='image/png')
        except Exception:
            return JSONResponse({'code': 'unavailable'}, status_code=503)


@app.post('/v1/login/action')
async def action(payload: dict):
    kind = payload.get('kind')
    if kind not in {'click', 'text', 'key', 'scroll'}:
        return JSONResponse({'code': 'invalid_action'}, status_code=400)
    async with session.lock:
        try:
            await session.ensure_browser()
            session.operator_until = time.monotonic() + 900
            if kind == 'click':
                x, y = float(payload['x']), float(payload['y'])
                if not (0 <= x < VIEWPORT['width'] and 0 <= y < VIEWPORT['height']):
                    raise ValueError()
                await session.page.mouse.click(x, y)
            elif kind == 'text':
                value = payload.get('text')
                if not isinstance(value, str) or len(value) > 256:
                    raise ValueError()
                await session.page.keyboard.insert_text(value)
            elif kind == 'key':
                key = payload.get('key')
                if key not in {'Enter', 'Tab', 'Backspace', 'Escape'}:
                    raise ValueError()
                await session.page.keyboard.press(key)
            else:
                await session.page.mouse.wheel(0, 500 if payload.get('direction') == 'down' else -500)
        except (ValueError, KeyError, TypeError):
            return JSONResponse({'code': 'invalid_action'}, status_code=400)
        except Exception:
            return JSONResponse({'code': 'unavailable'}, status_code=503)
    return {'ok': True}
