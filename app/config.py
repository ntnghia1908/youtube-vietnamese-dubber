"""Đọc cấu hình từ ``config.yaml`` — Checkpoint 3.

Thứ tự ưu tiên của một giá trị: flag CLI > file config > mặc định trong
code. Riêng tên model dịch KHÔNG có mặc định (plan §10: tên model local
chỉ là config, không hard-code trong source) — thiếu thì báo lỗi rõ ràng
lúc tạo translator.

Chỉ khai báo các section đã có code đọc (``whisper``, ``translation``,
``tts``, ``timing``, ``mixing``).
Key lạ bị từ chối thay vì bỏ qua: gõ nhầm ``batchsize`` mà lặng lẽ dùng
mặc định thì rất khó phát hiện khi playlist đã chạy vài giờ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_FILENAME = "config.yaml"


class ConfigError(ValueError):
    """File config không đọc được hoặc có giá trị không hợp lệ."""


@dataclass(frozen=True)
class WhisperConfig:
    model: str = "medium"
    device: str = "auto"
    compute_type: str = "auto"


@dataclass(frozen=True)
class TranslationConfig:
    provider: str = "ollama"
    model: str | None = None
    # None -> đọc biến môi trường OLLAMA_HOST, rồi mới tới localhost.
    host: str | None = None
    batch_size: int = 25
    # Số dòng đã dịch ngay trước batch, gửi kèm làm ngữ cảnh (không dịch lại).
    context_size: int = 5
    max_attempts: int = 3
    temperature: float = 0.3
    num_ctx: int = 8192
    timeout_seconds: float = 300.0
    # None -> không gửi field ``think`` (cho model không hỗ trợ thinking).
    think: bool | None = False
    # Glossary dùng chung (vd cả series), gộp với <episode>/glossary.yaml.
    # Không kiểm file tồn tại lúc parse config — kiểm lúc dùng (lệnh translate).
    glossary: str | None = None
    # Số ký tự transcript tối đa gửi model khi tạo nháp glossary.
    glossary_max_chars: int = 8000


@dataclass(frozen=True)
class TTSConfig:
    provider: str = "edge"
    voice: str = "vi-VN-HoaiMyNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    concurrency: int = 4
    max_attempts: int = 3
    timeout_seconds: float = 60.0


@dataclass(frozen=True)
class TimingConfig:
    normal_max_ratio: float = 1.05
    max_tempo: float = 1.25


@dataclass(frozen=True)
class PipelineConfig:
    # `dub` (CP7): số vòng tối đa chạy lại translate (câu dịch lỗi) và
    # tts+normalize (thiếu audio) trước khi render; 0 = không thử lại.
    repair_rounds: int = 2
    # `playlist` (CP8): dừng sớm sau N tập lỗi LIÊN TIẾP (lỗi hệ thống —
    # Ollama tắt, mất mạng — nhiều khả năng lặp lại y hệt ở các tập sau,
    # chạy tiếp chỉ tốn thời gian); 0 = không bao giờ dừng sớm.
    max_consecutive_failures: int = 3


@dataclass(frozen=True)
class MixingConfig:
    # Volume audio gốc khi mix (plan §15: 25–35%). 0 = tắt hẳn audio gốc.
    original_volume: float = 0.30
    # Volume giọng tiếng Việt. Riêng khỏi ``tts.volume`` (đó là volume do
    # edge-tts áp lúc tổng hợp, dạng +N%; đây là hệ số lúc mix).
    speech_volume: float = 1.0
    # Số giây dời tối đa một câu khi câu trước tràn slot. 0 = không dời (đè).
    max_shift_seconds: float = 1.0


@dataclass(frozen=True)
class AppConfig:
    workspace: Path = Path("output")
    target_language: str = "vi"
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    mixing: MixingConfig = field(default_factory=MixingConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)


# Kiểu hợp lệ cho từng key. ``None`` trong tuple = cho phép giá trị null.
_WHISPER_TYPES: dict[str, tuple[type | None, ...]] = {
    "model": (str,),
    "device": (str,),
    "compute_type": (str,),
}
_TRANSLATION_TYPES: dict[str, tuple[type | None, ...]] = {
    "provider": (str,),
    "model": (str, None),
    "host": (str, None),
    "batch_size": (int,),
    "context_size": (int,),
    "max_attempts": (int,),
    "temperature": (int, float),
    "num_ctx": (int,),
    "timeout_seconds": (int, float),
    "think": (bool, None),
    "glossary": (str, None),
    "glossary_max_chars": (int,),
}
_SUPPORTED_PROVIDERS = ("ollama",)
_TTS_TYPES: dict[str, tuple[type | None, ...]] = {
    "provider": (str,),
    "voice": (str,),
    "rate": (str,),
    "volume": (str,),
    "concurrency": (int,),
    "max_attempts": (int,),
    "timeout_seconds": (int, float),
}
_SUPPORTED_TTS_PROVIDERS = ("edge",)
_TIMING_TYPES: dict[str, tuple[type | None, ...]] = {
    "normal_max_ratio": (int, float),
    "max_tempo": (int, float),
}
_MIXING_TYPES: dict[str, tuple[type | None, ...]] = {
    "original_volume": (int, float),
    "speech_volume": (int, float),
    "max_shift_seconds": (int, float),
}
_PIPELINE_TYPES: dict[str, tuple[type | None, ...]] = {
    "repair_rounds": (int,),
    "max_consecutive_failures": (int,),
}
# vd "+0%", "-10%", "+100%". YAML `rate: +0%` không quote vẫn parse ra str,
# nhưng thiếu dấu % (`rate: 0%` thành số 0 hoặc thiếu dấu +/-) là lỗi hay gặp.
_RATE_VOLUME_RE = re.compile(r"^[+-]\d{1,3}%$")


def validate_rate_or_volume(section: str, key: str, value: str) -> None:
    """Kiểm tra ``rate``/``volume`` đúng định dạng edge-tts (``+N%``/``-N%``).

    Dùng chung cho cả ``config.yaml`` (``parse_config``) và flag CLI
    (``--rate``/``--volume``) để cùng một thông báo lỗi.
    """
    if not _RATE_VOLUME_RE.match(value):
        raise ConfigError(
            f"`{section}.{key}` phải có dạng \"+N%\" hoặc \"-N%\" (vd \"+0%\", \"-10%\"), "
            f"đang là {value!r}."
        )


def validate_timing_ratios(normal_max_ratio: float, max_tempo: float) -> None:
    """Kiểm tra ``1.0 <= normal_max_ratio < max_tempo <= 2.0``.

    Dùng chung cho ``config.yaml`` (``parse_config``) và flag CLI
    (``--max-tempo``) để cùng một thông báo lỗi. ``max_tempo <=
    normal_max_ratio`` không có ý nghĩa: mọi câu hơi dài hơn ngưỡng
    "normal" sẽ ngay lập tức bị coi là "too_long" vì không còn khoảng để
    co giãn.
    """
    if not (1.0 <= normal_max_ratio < max_tempo <= 2.0):
        raise ConfigError(
            "`timing.normal_max_ratio`/`timing.max_tempo` không hợp lệ: cần "
            f"1.0 <= normal_max_ratio ({normal_max_ratio}) < max_tempo ({max_tempo}) <= 2.0."
        )


def validate_mixing(
    original_volume: float, speech_volume: float, max_shift_seconds: float
) -> None:
    """Kiểm tra tham số mix: ``0 <= original_volume <= 1``, ``0 < speech_volume <= 2``,
    ``max_shift_seconds >= 0``.

    Dùng chung cho ``config.yaml`` (``parse_config``) và flag CLI
    (``--original-volume``/``--max-shift``) để cùng một thông báo lỗi.
    ``speech_volume`` không cho bằng 0: tắt hẳn giọng thuyết minh thì không
    còn là bản lồng tiếng, gần như chắc chắn là gõ nhầm.
    """
    if not 0.0 <= original_volume <= 1.0:
        raise ConfigError(
            f"`mixing.original_volume` phải trong khoảng 0.0–1.0 (đang là {original_volume})."
        )
    if not 0.0 < speech_volume <= 2.0:
        raise ConfigError(
            f"`mixing.speech_volume` phải lớn hơn 0 và không quá 2.0 (đang là {speech_volume})."
        )
    if max_shift_seconds < 0.0:
        raise ConfigError(
            f"`mixing.max_shift_seconds` không được âm (đang là {max_shift_seconds})."
        )


def _check_section(
    data: Any, section: str, types: dict[str, tuple[type | None, ...]]
) -> dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"`{section}` phải là một mapping (key: value).")

    unknown = sorted(set(data) - set(types))
    if unknown:
        raise ConfigError(
            f"Key không hợp lệ trong `{section}`: {', '.join(map(str, unknown))}. "
            f"Key hợp lệ: {', '.join(types)}."
        )

    for key, value in data.items():
        allowed = types[key]
        if value is None:
            if None not in allowed:
                raise ConfigError(f"`{section}.{key}` không được để trống.")
            continue
        # bool là subclass của int trong Python: `batch_size: true` không được lọt qua.
        if isinstance(value, bool) and bool not in allowed:
            raise ConfigError(f"`{section}.{key}` có kiểu không hợp lệ: {value!r}.")
        if not isinstance(value, tuple(t for t in allowed if t is not None)):
            raise ConfigError(f"`{section}.{key}` có kiểu không hợp lệ: {value!r}.")
    return dict(data)


def _positive(section: str, key: str, value: float) -> None:
    if value <= 0:
        raise ConfigError(f"`{section}.{key}` phải lớn hơn 0 (đang là {value}).")


def parse_config(data: Any) -> AppConfig:
    """Dựng ``AppConfig`` từ dữ liệu YAML đã parse. Raise ConfigError nếu sai."""
    if data is None:
        return AppConfig()
    if not isinstance(data, dict):
        raise ConfigError("File config phải là một mapping ở cấp cao nhất.")

    top_level = {
        "workspace",
        "target_language",
        "whisper",
        "translation",
        "tts",
        "timing",
        "mixing",
        "pipeline",
    }
    unknown = sorted(set(data) - top_level)
    if unknown:
        raise ConfigError(
            f"Section không hợp lệ: {', '.join(map(str, unknown))}. "
            f"Hợp lệ: {', '.join(sorted(top_level))}."
        )

    kwargs: dict[str, Any] = {}
    if data.get("workspace") is not None:
        if not isinstance(data["workspace"], str):
            raise ConfigError("`workspace` phải là đường dẫn dạng chuỗi.")
        kwargs["workspace"] = Path(data["workspace"])
    if data.get("target_language") is not None:
        if not isinstance(data["target_language"], str):
            raise ConfigError("`target_language` phải là mã ngôn ngữ dạng chuỗi (vd vi).")
        kwargs["target_language"] = data["target_language"]

    kwargs["whisper"] = WhisperConfig(
        **_check_section(data.get("whisper"), "whisper", _WHISPER_TYPES)
    )

    translation = TranslationConfig(
        **_check_section(data.get("translation"), "translation", _TRANSLATION_TYPES)
    )
    if translation.provider not in _SUPPORTED_PROVIDERS:
        raise ConfigError(
            f"`translation.provider` không hỗ trợ: {translation.provider!r}. "
            f"Hiện có: {', '.join(_SUPPORTED_PROVIDERS)}."
        )
    for key in ("batch_size", "max_attempts", "num_ctx", "timeout_seconds", "glossary_max_chars"):
        _positive("translation", key, getattr(translation, key))
    if translation.context_size < 0:
        raise ConfigError("`translation.context_size` không được âm.")
    kwargs["translation"] = translation

    tts = TTSConfig(**_check_section(data.get("tts"), "tts", _TTS_TYPES))
    if tts.provider not in _SUPPORTED_TTS_PROVIDERS:
        raise ConfigError(
            f"`tts.provider` không hỗ trợ: {tts.provider!r}. "
            f"Hiện có: {', '.join(_SUPPORTED_TTS_PROVIDERS)}."
        )
    validate_rate_or_volume("tts", "rate", tts.rate)
    validate_rate_or_volume("tts", "volume", tts.volume)
    for key in ("concurrency", "max_attempts", "timeout_seconds"):
        _positive("tts", key, getattr(tts, key))
    kwargs["tts"] = tts

    timing = TimingConfig(**_check_section(data.get("timing"), "timing", _TIMING_TYPES))
    validate_timing_ratios(timing.normal_max_ratio, timing.max_tempo)
    kwargs["timing"] = timing

    mixing = MixingConfig(**_check_section(data.get("mixing"), "mixing", _MIXING_TYPES))
    validate_mixing(mixing.original_volume, mixing.speech_volume, mixing.max_shift_seconds)
    kwargs["mixing"] = mixing

    pipeline = PipelineConfig(**_check_section(data.get("pipeline"), "pipeline", _PIPELINE_TYPES))
    if pipeline.repair_rounds < 0:
        raise ConfigError(
            f"`pipeline.repair_rounds` không được âm (đang là {pipeline.repair_rounds})."
        )
    if pipeline.max_consecutive_failures < 0:
        raise ConfigError(
            "`pipeline.max_consecutive_failures` không được âm (đang là "
            f"{pipeline.max_consecutive_failures})."
        )
    kwargs["pipeline"] = pipeline

    return AppConfig(**kwargs)


def load_config(path: Path | None = None) -> AppConfig:
    """Đọc config từ ``path``.

    ``path=None``: dùng ``./config.yaml`` nếu có, không có thì dùng mặc
    định (để các lệnh không cần config vẫn chạy được trên máy mới).
    ``path`` được chỉ định rõ mà không tồn tại thì báo lỗi.
    """
    if path is None:
        path = Path(DEFAULT_CONFIG_FILENAME)
        if not path.exists():
            return AppConfig()
    elif not path.exists():
        raise ConfigError(f"Không tìm thấy file config: {path}")

    try:
        import yaml
    except ImportError as exc:
        raise ConfigError("Chưa cài `pyyaml`. Chạy `pip install -e .` rồi thử lại.") from exc

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Không đọc được file config {path}: {exc}") from exc

    try:
        return parse_config(data)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
