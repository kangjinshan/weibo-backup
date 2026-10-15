"""Cookie probes shared by the NAS and the dedicated browser service."""
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def classify_page(url, text, status=200):
    host = (urlsplit(url).hostname or '').lower()
    path = urlsplit(url).path.lower()
    title_match = re.search(r'<title>(.*?)</title>', text, re.I | re.S)
    title = title_match.group(1).strip() if title_match else ''
    if status == 429 or any(value in text for value in ('访问频繁', '请求过于频繁')):
        return {'state': 'rate_limited', 'valid': None, 'message': '微博访问受限，请稍后重试'}
    if any(value in title for value in ('安全验证', '访问验证')):
        return {'state': 'verification_required', 'valid': None, 'message': '微博需要在浏览器中完成验证'}
    if host in {'passport.weibo.com', 'login.sina.com.cn'} or 'login' in path or any(value in title for value in ('登录', '通行证')):
        return {'state': 'expired', 'valid': False, 'message': '微博登录已失效，需要更新 Cookie'}
    if status == 200 and host == 'weibo.cn' and ('基本信息' in text or '资料' in title):
        return {'state': 'valid', 'valid': True, 'message': 'Cookie 有效'}
    return {'state': 'unknown', 'valid': None, 'message': '暂时无法确认微博登录状态，请稍后重试'}


def probe_cookie(cookie, user_id, timeout=12):
    if not re.fullmatch(r'\d{5,20}', str(user_id)):
        return {'state': 'unknown', 'valid': None, 'message': '微博账号 ID 不正确'}
    if not cookie:
        return {'state': 'missing', 'valid': False, 'message': '尚未登录微博'}
    req = Request(f'https://weibo.cn/{user_id}/info', headers={'User-Agent': 'Mozilla/5.0', 'Cookie': cookie})
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read(80_000)
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                text = raw.decode('gb18030', errors='replace')
            return classify_page(response.geturl(), text, response.status)
    except HTTPError as exc:
        result = classify_page(exc.url, '', exc.code)
        exc.close()
        return result
    except Exception:
        return {'state': 'unknown', 'valid': None, 'message': '连接微博失败，请稍后重试'}
