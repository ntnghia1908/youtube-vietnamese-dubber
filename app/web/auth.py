"""Xác thực bằng mật khẩu cho Web UI khi mở ra LAN (WEB-AUTH, ADR-001 mục 9).

Chỉ dùng stdlib và KHÔNG import fastapi để test được mà không cần extra ``web``.
Phiên là stateless: cookie tự mang hạn dùng và chữ ký HMAC, khoá ký suy ra từ
chính mật khẩu — đổi mật khẩu thì mọi phiên cũ mất hiệu lực, restart server
thì không ai bị đăng xuất, và không phải lưu gì xuống đĩa.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import threading
import time
from collections.abc import Callable

# Tên biến môi trường, không phải key config: mật khẩu không bao giờ nằm trong file.
PASSWORD_ENV = "DUBBER_WEB_PASSWORD"
COOKIE_NAME = "dubber_session"
SESSION_SECONDS = 30 * 24 * 3600
MAX_FAILURES = 5  # mỗi IP
FAILURE_WINDOW_SECONDS = 300  # quá MAX_FAILURES lần sai trong cửa sổ -> khoá tới khi cửa sổ trôi qua
PUBLIC_PATHS = ("/login",)  # + mọi path bắt đầu "/static/"

# Cho phép lệch đồng hồ nhỏ khi kiểm expiry tương lai.
_CLOCK_SKEW_SECONDS = 60


def is_loopback(host: str) -> bool:
    """True nếu ``host`` chỉ nghe được từ chính máy này."""
    host = host.strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_password(candidate: str, password: str) -> bool:
    # compare_digest để không lộ độ dài tiền tố đúng qua thời gian phản hồi.
    return hmac.compare_digest(candidate.encode("utf-8"), password.encode("utf-8"))


def _key(password: str) -> bytes:
    return hashlib.sha256(b"dubber-web-session\0" + password.encode("utf-8")).digest()


def _sign(password: str, expiry: str) -> str:
    return hmac.new(_key(password), expiry.encode("ascii"), hashlib.sha256).hexdigest()


def make_session(password: str, *, now: float | None = None) -> str:
    now = time.time() if now is None else now
    expiry = str(int(now) + SESSION_SECONDS)
    return f"{expiry}.{_sign(password, expiry)}"


def verify_session(cookie: str | None, password: str, *, now: float | None = None) -> bool:
    if not cookie or not password:
        return False
    expiry, sep, signature = cookie.partition(".")
    if not sep or not expiry.isascii() or not expiry.isdigit():
        return False
    if not hmac.compare_digest(signature.encode("utf-8"), _sign(password, expiry).encode("ascii")):
        return False
    now = time.time() if now is None else now
    expiry_unix = int(expiry)
    # Hạn quá xa trong tương lai chỉ có thể do cookie không do server này cấp.
    return now <= expiry_unix <= now + SESSION_SECONDS + _CLOCK_SKEW_SECONDS


def safe_next(value: str | None) -> str:
    """Chỉ chấp nhận path tương đối nội bộ, chặn open redirect (``//evil``, ``https://``)."""
    if not value or not value.startswith("/"):
        return "/"
    if value.startswith("//") or value.startswith("/\\"):
        return "/"
    if any(ch in value for ch in ("\r", "\n", "\\")):
        return "/"
    return value


class LoginThrottle:
    """Giới hạn đăng nhập sai theo IP: quá ``max_failures`` lần trong ``window`` giây thì khoá."""

    def __init__(
        self,
        *,
        max_failures: int = MAX_FAILURES,
        window: float = FAILURE_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_failures
        self._window = window
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}

    def _prune(self, now: float) -> None:
        for client in list(self._failures):
            kept = [t for t in self._failures[client] if now - t < self._window]
            if kept:
                self._failures[client] = kept
            else:
                del self._failures[client]

    def blocked(self, client: str) -> float:
        with self._lock:
            now = self._clock()
            self._prune(now)
            times = self._failures.get(client, [])
            if len(times) < self._max:
                return 0.0
            # Bị khoá tới khi lần sai cũ nhất trôi khỏi cửa sổ.
            return max(0.0, times[0] + self._window - now)

    def record_failure(self, client: str) -> None:
        with self._lock:
            now = self._clock()
            self._prune(now)
            self._failures.setdefault(client, []).append(now)

    def reset(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)
