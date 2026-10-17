"""Test section config ``web`` và subcommand ``web`` — AC1, AC2."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from app import cli
from app.web.auth import PASSWORD_ENV
from app.config import AppConfig, ConfigError, WebConfig, parse_config


class TestWebConfig(unittest.TestCase):
    def test_defaults(self) -> None:
        self.assertEqual(AppConfig().web, WebConfig("127.0.0.1", 8765))
        self.assertEqual(parse_config({}).web.port, 8765)

    def test_reads_section(self) -> None:
        web = parse_config({"web": {"host": "localhost", "port": 9000}}).web
        self.assertEqual((web.host, web.port), ("localhost", 9000))

    def test_invalid(self) -> None:
        for bad in (0, 65536, -1):
            with self.assertRaises(ConfigError, msg=bad):
                parse_config({"web": {"port": bad}})
        with self.assertRaises(ConfigError):
            parse_config({"web": {"port": "8765"}})
        with self.assertRaises(ConfigError):
            parse_config({"web": {"prot": 1}})
        with self.assertRaises(ConfigError):
            parse_config({"web": {"host": ""}})


class TestWebCommand(unittest.TestCase):
    def test_parser(self) -> None:
        args = cli.build_parser().parse_args(["web", "--host", "0.0.0.0", "--port", "9", "--workspace", "w"])
        self.assertEqual((args.command, args.host, args.port, args.workspace), ("web", "0.0.0.0", 9, "w"))
        args = cli.build_parser().parse_args(["web"])
        self.assertIsNone(args.host)
        self.assertIsNone(args.port)

    def test_help_lists_flags(self) -> None:
        out = subprocess.run([sys.executable, "-m", "app", "web", "--help"],
                             capture_output=True, text=True, encoding="utf-8").stdout
        for flag in ("--host", "--port", "--workspace"):
            self.assertIn(flag, out)

    def test_bad_port_flag(self) -> None:
        err = io.StringIO()
        with patch.object(cli, "_load_config", return_value=AppConfig()), redirect_stderr(err):
            code = cli.main(["web", "--port", "70000"])
        self.assertEqual(code, 1)
        self.assertIn("1–65535", err.getvalue())

    def test_missing_extra_exits_2(self) -> None:
        err = io.StringIO()
        with patch.object(cli, "_load_config", return_value=AppConfig()), \
                patch.dict(sys.modules, {"app.web.server": None}), redirect_stderr(err):
            code = cli.main(["web"])
        self.assertEqual(code, 2)
        self.assertIn('pip install -e ".[web]"', err.getvalue())

    def _run_web(self, argv, env_password):
        """Chạy `cli.main` với `run` giả; trả (exit, calls, stderr)."""
        calls = []
        fake = type(sys)("app.web.server")
        fake.run = lambda *a, **kw: calls.append(a)
        config = parse_config({"web": {"host": "127.0.0.1", "port": 1111}, "workspace": "ws"})
        env = {} if env_password is None else {PASSWORD_ENV: env_password}
        err = io.StringIO()
        with patch.object(cli, "_load_config", return_value=config), \
                patch.dict(sys.modules, {"app.web.server": fake}), \
                patch.dict(os.environ, env), redirect_stderr(err):
            if env_password is None:
                os.environ.pop(PASSWORD_ENV, None)
            code = cli.main(argv)
        return code, calls, err.getvalue()

    def test_flag_overrides_config(self) -> None:
        code, calls, _ = self._run_web(["web"], None)
        self.assertEqual((code, calls[0][:2], str(calls[0][2])), (0, ("127.0.0.1", 1111), "ws"))
        code, calls, _ = self._run_web(
            ["web", "--host", "10.0.0.5", "--port", "2222", "--workspace", "w2"], "pw")
        self.assertEqual((code, calls[0][:2], str(calls[0][2])), (0, ("10.0.0.5", 2222), "w2"))

    def test_max_jobs_flag_and_config(self) -> None:
        # Flag ghi đè; mặc định auto resolve theo phần cứng (inject qua patch).
        with patch("app.hardware.cpu_count", return_value=32), \
                patch("app.hardware.cuda_device_count", return_value=0):
            code, calls, err = self._run_web(["web"], None)
            self.assertEqual((code, calls[0][6]), (0, 2))
            self.assertIn("[web] Hàng đợi: tối đa 2 job song song (32 CPU)", err)
            code, calls, err = self._run_web(["web", "--max-jobs", "1"], None)
            self.assertEqual((code, calls[0][6]), (0, 1))
            self.assertIn("theo config", err)

    def test_max_jobs_invalid_exits_2(self) -> None:
        for bad in ("3", "0"):
            code, calls, err = self._run_web(["web", "--max-jobs", bad], None)
            with self.subTest(bad=bad):
                self.assertEqual(code, 2)
                self.assertEqual(calls, [])
                self.assertIn("web.max_jobs", err)

    def test_shared_glossary_passed_to_run(self) -> None:
        code, calls, _ = self._run_web(["web"], None)
        self.assertIsNone(calls[0][5])
        config = parse_config({"workspace": "ws", "translation": {"glossary": "series.yaml"}})
        fake = type(sys)("app.web.server")
        calls2 = []
        fake.run = lambda *a, **kw: calls2.append(a)
        with patch.object(cli, "_load_config", return_value=config), \
                patch.dict(sys.modules, {"app.web.server": fake}):
            os.environ.pop(PASSWORD_ENV, None)
            cli.main(["web"])
        self.assertEqual(str(calls2[0][5]), "series.yaml")

    def test_startup_rule_table(self) -> None:
        # (host, mật khẩu env) -> (exit, mật khẩu truyền cho run)
        cases = [
            ("127.0.0.1", None, 0, None),
            ("127.0.0.1", "", 0, None),
            ("127.0.0.1", "pw", 0, "pw"),
            ("10.0.0.5", None, 2, None),
            ("10.0.0.5", "", 2, None),
            ("10.0.0.5", "pw", 0, "pw"),
        ]
        for host, pw, want_code, want_pw in cases:
            code, calls, err = self._run_web(["web", "--host", host], pw)
            with self.subTest(host=host, pw=pw):
                self.assertEqual(code, want_code)
                if want_code == 2:
                    self.assertEqual(calls, [])  # không bind
                    self.assertIn("DUBBER_WEB_PASSWORD", err)
                else:
                    self.assertEqual(calls[0][4], want_pw)
                    self.assertNotIn("pw", err.replace("password", ""))
        _, _, err = self._run_web(["web", "--host", "10.0.0.5"], "pw")
        self.assertIn("HTTP (không mã hoá)", err)


if __name__ == "__main__":
    unittest.main()
