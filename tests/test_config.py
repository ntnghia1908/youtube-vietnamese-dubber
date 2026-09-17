"""Unit test cho ``app.config``."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import AppConfig, ConfigError, load_config, parse_config


class TestParseConfig(unittest.TestCase):
    def test_empty_config_uses_defaults(self) -> None:
        config = parse_config(None)
        self.assertEqual(config, AppConfig())
        # Không có model dịch mặc định trong code (plan §10).
        self.assertIsNone(config.translation.model)

    def test_reads_sections(self) -> None:
        config = parse_config(
            {
                "workspace": "./ws",
                "target_language": "vi",
                "whisper": {"model": "small", "device": "cuda"},
                "translation": {"model": "qwen3:8b", "batch_size": 20, "think": None},
            }
        )
        self.assertEqual(config.workspace, Path("./ws"))
        self.assertEqual(config.whisper.model, "small")
        self.assertEqual(config.whisper.compute_type, "auto")
        self.assertEqual(config.translation.model, "qwen3:8b")
        self.assertEqual(config.translation.batch_size, 20)
        self.assertIsNone(config.translation.think)

    def test_rejects_unknown_key(self) -> None:
        with self.assertRaisesRegex(ConfigError, "batchsize"):
            parse_config({"translation": {"batchsize": 20}})

    def test_rejects_unknown_section(self) -> None:
        with self.assertRaisesRegex(ConfigError, "translate"):
            parse_config({"translate": {}})

    def test_rejects_wrong_type(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"translation": {"batch_size": "25"}})

    def test_rejects_bool_for_int(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"translation": {"batch_size": True}})

    def test_rejects_non_positive_batch_size(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"translation": {"batch_size": 0}})

    def test_rejects_unsupported_provider(self) -> None:
        with self.assertRaisesRegex(ConfigError, "provider"):
            parse_config({"translation": {"provider": "openai"}})

    def test_temperature_accepts_int(self) -> None:
        self.assertEqual(parse_config({"translation": {"temperature": 0}}).translation.temperature, 0)


class TestLoadConfig(unittest.TestCase):
    def test_explicit_missing_path_errors(self) -> None:
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                load_config(Path(tmp) / "nope.yaml")

    def test_loads_yaml_file(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("translation:\n  model: qwen3:8b\n", encoding="utf-8")
            self.assertEqual(load_config(path).translation.model, "qwen3:8b")

    def test_invalid_yaml_errors_with_path(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("translation: [unclosed\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "config.yaml"):
                load_config(path)

    def test_example_config_is_valid(self) -> None:
        example = Path(__file__).resolve().parent.parent / "config.example.yaml"
        config = load_config(example)
        self.assertEqual(config.translation.provider, "ollama")
        self.assertTrue(config.translation.model)


if __name__ == "__main__":
    unittest.main()
