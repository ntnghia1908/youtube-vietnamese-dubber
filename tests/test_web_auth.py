"""Test thuần stdlib cho ``app.web.auth`` — AC5–AC7."""

from __future__ import annotations

import unittest

from app.web import auth


class TestPassword(unittest.TestCase):
    def test_check_password(self) -> None:
        self.assertTrue(auth.check_password("mật-khẩu", "mật-khẩu"))
        self.assertFalse(auth.check_password("mật-khẩU", "mật-khẩu"))
        self.assertFalse(auth.check_password("", "x"))


class TestSession(unittest.TestCase):
    def test_roundtrip(self) -> None:
        c = auth.make_session("pw", now=1000)
        self.assertTrue(auth.verify_session(c, "pw", now=1001))

    def test_tampered_signature(self) -> None:
        c = auth.make_session("pw", now=1000)
        bad = c[:-1] + ("0" if c[-1] != "0" else "1")
        self.assertFalse(auth.verify_session(bad, "pw", now=1001))

    def test_tampered_expiry(self) -> None:
        expiry, sig = auth.make_session("pw", now=1000).split(".")
        self.assertFalse(auth.verify_session(f"{int(expiry) + 1}.{sig}", "pw", now=1001))

    def test_expired(self) -> None:
        c = auth.make_session("pw", now=1000)
        self.assertFalse(auth.verify_session(c, "pw", now=1000 + auth.SESSION_SECONDS + 1))

    def test_expiry_too_far_in_future(self) -> None:
        # Chữ ký đúng nhưng hạn xa bất thường -> không phải cookie server cấp.
        expiry = str(10_000 + auth.SESSION_SECONDS + 3600)
        c = f"{expiry}.{auth._sign('pw', expiry)}"
        self.assertFalse(auth.verify_session(c, "pw", now=10_000))

    def test_other_password(self) -> None:
        c = auth.make_session("pw", now=1000)
        self.assertFalse(auth.verify_session(c, "pw2", now=1001))

    def test_garbage(self) -> None:
        for bad in (None, "", "abc", ".", "12.", ".abc", "x.y", "1.2.3", "１２.ab"):
            self.assertFalse(auth.verify_session(bad, "pw", now=1), repr(bad))
        self.assertFalse(auth.verify_session("1.a", "", now=1))


class TestSafeNext(unittest.TestCase):
    def test_keeps_internal(self) -> None:
        self.assertEqual(auth.safe_next("/ep/x?y=1"), "/ep/x?y=1")
        self.assertEqual(auth.safe_next("/"), "/")

    def test_rejects_external(self) -> None:
        for bad in ("//a", "/\\a", "https://a", "javascript:alert(1)", "", None, "ep/x", "/a\r\nb"):
            self.assertEqual(auth.safe_next(bad), "/", repr(bad))


class TestThrottle(unittest.TestCase):
    def test_block_and_expire(self) -> None:
        now = [0.0]
        t = auth.LoginThrottle(max_failures=3, window=100, clock=lambda: now[0])
        for _ in range(2):
            t.record_failure("a")
        self.assertEqual(t.blocked("a"), 0)
        t.record_failure("a")
        self.assertEqual(t.blocked("a"), 100)
        self.assertEqual(t.blocked("b"), 0)  # IP khác không bị ảnh hưởng
        now[0] = 60
        self.assertEqual(t.blocked("a"), 40)
        now[0] = 101
        self.assertEqual(t.blocked("a"), 0)

    def test_reset(self) -> None:
        t = auth.LoginThrottle(max_failures=1)
        t.record_failure("a")
        self.assertGreater(t.blocked("a"), 0)
        t.reset("a")
        self.assertEqual(t.blocked("a"), 0)


class TestLoopback(unittest.TestCase):
    def test_is_loopback(self) -> None:
        for h in ("127.0.0.1", "localhost", "::1", "127.0.0.5", "LOCALHOST"):
            self.assertTrue(auth.is_loopback(h), h)
        for h in ("0.0.0.0", "10.8.102.102", "::", "example.com", ""):
            self.assertFalse(auth.is_loopback(h), h)


if __name__ == "__main__":
    unittest.main()
