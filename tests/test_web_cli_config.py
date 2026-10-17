"""Test section config ``web`` và subcommand ``web`` — AC1, AC2."""

from __future__ import annotations

import io
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from app import cli
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

    def test_flag_overrides_config_and_warns_on_non_loopback(self) -> None:
        calls = []
        fake = type(sys)("app.web.server")
        fake.run = lambda *a: calls.append(a)
        config = parse_config({"web": {"host": "127.0.0.1", "port": 1111}, "workspace": "ws"})
        err = io.StringIO()
        with patch.object(cli, "_load_config", return_value=config), \
                patch.dict(sys.modules, {"app.web.server": fake}), redirect_stderr(err):
            self.assertEqual(cli.main(["web"]), 0)
            self.assertEqual(cli.main(["web", "--host", "0.0.0.0", "--port", "2222", "--workspace", "w2"]), 0)
        self.assertEqual(str(calls[0][2]), "ws")
        self.assertEqual(calls[0][:2], ("127.0.0.1", 1111))
        self.assertEqual(calls[1][:2], ("0.0.0.0", 2222))
        self.assertEqual(str(calls[1][2]), "w2")
        self.assertEqual(err.getvalue().count("CẢNH BÁO"), 1)  # chỉ lần bind 0.0.0.0


if __name__ == "__main__":
    unittest.main()
