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

    def test_translation_glossary_defaults(self) -> None:
        config = parse_config(None)
        self.assertIsNone(config.translation.glossary)
        self.assertEqual(config.translation.glossary_max_chars, 8000)

    def test_translation_glossary_reads_values(self) -> None:
        config = parse_config(
            {"translation": {"glossary": "./series/glossary.yaml", "glossary_max_chars": 4000}}
        )
        self.assertEqual(config.translation.glossary, "./series/glossary.yaml")
        self.assertEqual(config.translation.glossary_max_chars, 4000)
        # null tường minh cũng hợp lệ (= không dùng glossary chung).
        self.assertIsNone(parse_config({"translation": {"glossary": None}}).translation.glossary)

    def test_translation_glossary_rejects_wrong_type(self) -> None:
        for value in (5, ["a.yaml"], True):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                parse_config({"translation": {"glossary": value}})

    def test_translation_glossary_does_not_check_file_exists(self) -> None:
        # Kiểm file tồn tại là việc lúc dùng (lệnh translate), không phải lúc parse config.
        config = parse_config({"translation": {"glossary": "khong/ton/tai.yaml"}})
        self.assertEqual(config.translation.glossary, "khong/ton/tai.yaml")

    def test_translation_glossary_max_chars_must_be_positive_int(self) -> None:
        for value in (0, -1):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                parse_config({"translation": {"glossary_max_chars": value}})
        for value in ("8000", 8.5, True):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                parse_config({"translation": {"glossary_max_chars": value}})

    def test_tts_section_defaults(self) -> None:
        config = parse_config(None)
        self.assertEqual(config.tts.provider, "edge")
        self.assertEqual(config.tts.voice, "vi-VN-HoaiMyNeural")
        self.assertEqual(config.tts.rate, "+0%")
        self.assertEqual(config.tts.volume, "+0%")
        self.assertEqual(config.tts.concurrency, 4)
        self.assertEqual(config.tts.max_attempts, 3)
        self.assertEqual(config.tts.timeout_seconds, 60)

    def test_tts_section_reads_values(self) -> None:
        config = parse_config(
            {"tts": {"voice": "vi-VN-NamMinhNeural", "rate": "+20%", "concurrency": 8}}
        )
        self.assertEqual(config.tts.voice, "vi-VN-NamMinhNeural")
        self.assertEqual(config.tts.rate, "+20%")
        self.assertEqual(config.tts.concurrency, 8)

    def test_tts_rejects_unknown_key(self) -> None:
        with self.assertRaisesRegex(ConfigError, "voise"):
            parse_config({"tts": {"voise": "x"}})

    def test_tts_rejects_bad_rate_format(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"tts": {"rate": "0%"}})

    def test_tts_rejects_bad_volume_format(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"tts": {"volume": "fast"}})

    def test_tts_accepts_negative_rate(self) -> None:
        self.assertEqual(parse_config({"tts": {"rate": "-10%"}}).tts.rate, "-10%")

    def test_tts_rejects_non_positive_concurrency(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"tts": {"concurrency": 0}})

    def test_tts_rejects_unsupported_provider(self) -> None:
        with self.assertRaisesRegex(ConfigError, "provider"):
            parse_config({"tts": {"provider": "azure"}})

    def test_timing_section_defaults(self) -> None:
        config = parse_config(None)
        self.assertEqual(config.timing.normal_max_ratio, 1.05)
        self.assertEqual(config.timing.max_tempo, 1.25)

    def test_timing_section_reads_values(self) -> None:
        config = parse_config({"timing": {"normal_max_ratio": 1.1, "max_tempo": 1.4}})
        self.assertEqual(config.timing.normal_max_ratio, 1.1)
        self.assertEqual(config.timing.max_tempo, 1.4)

    def test_timing_rejects_unknown_key(self) -> None:
        with self.assertRaisesRegex(ConfigError, "max_tempoo"):
            parse_config({"timing": {"max_tempoo": 1.4}})

    def test_timing_rejects_max_tempo_not_greater_than_normal_max_ratio(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"timing": {"normal_max_ratio": 1.2, "max_tempo": 1.1}})

    def test_timing_rejects_max_tempo_above_two(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"timing": {"max_tempo": 2.5}})

    def test_timing_rejects_normal_max_ratio_below_one(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"timing": {"normal_max_ratio": 0.9}})

    def test_timing_rejects_wrong_type(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"timing": {"max_tempo": "1.25"}})

    def test_mixing_section_defaults(self) -> None:
        config = parse_config(None)
        self.assertEqual(config.mixing.original_volume, 0.30)
        self.assertEqual(config.mixing.speech_volume, 1.0)
        self.assertEqual(config.mixing.max_shift_seconds, 1.0)

    def test_mixing_section_reads_values(self) -> None:
        config = parse_config(
            {"mixing": {"original_volume": 0.5, "speech_volume": 1.5, "max_shift_seconds": 0}}
        )
        self.assertEqual(config.mixing.original_volume, 0.5)
        self.assertEqual(config.mixing.speech_volume, 1.5)
        self.assertEqual(config.mixing.max_shift_seconds, 0)

    def test_mixing_accepts_boundary_values(self) -> None:
        config = parse_config({"mixing": {"original_volume": 0, "speech_volume": 2}})
        self.assertEqual(config.mixing.original_volume, 0)
        self.assertEqual(config.mixing.speech_volume, 2)
        self.assertEqual(parse_config({"mixing": {"original_volume": 1}}).mixing.original_volume, 1)

    def test_mixing_rejects_unknown_key(self) -> None:
        with self.assertRaisesRegex(ConfigError, "original_volum"):
            parse_config({"mixing": {"original_volum": 0.3}})

    def test_mixing_rejects_original_volume_out_of_range(self) -> None:
        for value in (-0.1, 1.1):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                parse_config({"mixing": {"original_volume": value}})

    def test_mixing_rejects_speech_volume_out_of_range(self) -> None:
        for value in (0, 2.5):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                parse_config({"mixing": {"speech_volume": value}})

    def test_mixing_rejects_negative_max_shift(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"mixing": {"max_shift_seconds": -0.5}})

    def test_mixing_rejects_wrong_type(self) -> None:
        for key in ("original_volume", "speech_volume", "max_shift_seconds"):
            for value in ("0.3", True):
                with self.subTest(key=key, value=value), self.assertRaises(ConfigError):
                    parse_config({"mixing": {key: value}})


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
        self.assertEqual(config.tts.provider, "edge")
        self.assertEqual(config.tts.voice, "vi-VN-HoaiMyNeural")
        self.assertEqual(config.timing.normal_max_ratio, 1.05)
        self.assertEqual(config.timing.max_tempo, 1.25)
        self.assertEqual(config.mixing.original_volume, 0.30)
        self.assertEqual(config.mixing.speech_volume, 1.0)
        self.assertEqual(config.mixing.max_shift_seconds, 1.0)
        # CP6.5: glossary dùng chung tắt mặc định (dòng đó nằm trong comment).
        self.assertIsNone(config.translation.glossary)
        self.assertEqual(config.translation.glossary_max_chars, 8000)


if __name__ == "__main__":
    unittest.main()
