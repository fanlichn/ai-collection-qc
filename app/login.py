import hashlib
import hmac
import time
from pathlib import Path

from fastapi import HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from .config import settings

SESSION_COOKIE = 'qc_session'
SESSION_SECONDS = 8 * 60 * 60


def credentials_match(username: str, password: str) -> bool:
    user_ok = hmac.compare_digest(username.encode(), settings.admin_user.encode())
    password_ok = hmac.compare_digest(password.encode(), settings.admin_password.encode())
    return user_ok and password_ok


def verify_origin(request: Request):
    url = request.base_url
    if request.headers.get('origin') != f'{url.scheme}://{url.netloc}':
        raise HTTPException(403, 'Invalid request origin')


def _signature(expires: str) -> str:
    message = f'qc-session\0{expires}\0{settings.admin_user}\0{settings.admin_password}'
    return hmac.new(settings.secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()


def session_user(request: Request) -> str | None:
    value = request.cookies.get(SESSION_COOKIE, '')
    expires, _, signature = value.partition('.')
    if (not expires.isascii() or not expires.isdecimal() or len(expires) > 12
            or len(signature) != 64 or not signature.isascii()
            or int(expires) <= time.time()):
        return None
    return settings.admin_user if hmac.compare_digest(signature, _signature(expires)) else None


def start_session(request: Request, response: Response):
    expires = str(int(time.time()) + SESSION_SECONDS)
    secure = request.url.scheme == 'https'
    response.set_cookie(SESSION_COOKIE, f'{expires}.{_signature(expires)}',
                        max_age=SESSION_SECONDS, httponly=True, secure=secure,
                        samesite='none' if secure else 'lax')
    if secure:
        # Starlette on Python 3.10 cannot set the Partitioned attribute directly.
        name, value = response.raw_headers[-1]
        response.raw_headers[-1] = (name, value + b'; Partitioned')


def login_page(*, invalid: bool = False) -> HTMLResponse:
    template = Path('web/login.html').read_text(encoding='utf-8')
    error = '<p role="alert">账号或密码错误，请重试。</p>' if invalid else ''
    return HTMLResponse(template.replace('<!-- LOGIN_ERROR -->', error),
                        status_code=401 if invalid else 200, headers={'Cache-Control': 'no-store'})
