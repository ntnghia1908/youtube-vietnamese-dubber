"""Đọc cấu hình từ ``config.yaml`` — Checkpoint 3.

Thứ tự ưu tiên của một giá trị: flag CLI > file config > mặc định trong
code. Riêng tên model dịch KHÔNG có mặc định (plan §10: tên model local
chỉ là config, không hard-code trong source) — thiếu thì báo lỗi rõ ràng
lúc tạo translator.

Chỉ khai báo các section đã có code đọc (``whisper``, ``translation``).
Key lạ bị từ chối thay vì bỏ qua: gõ nhầm ``batchsize`` mà lặng lẽ dùng
mặc định thì rất khó phát hiện khi playlist đã chạy vài giờ.
"""

from __future__ import annotations

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


@dataclass(frozen=True)
class AppConfig:
    workspace: Path = Path("output")
    target_language: str = "vi"
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)


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
}
_SUPPORTED_PROVIDERS = ("ollama",)


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

    top_level = {"workspace", "target_language", "whisper", "translation"}
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
    for key in ("batch_size", "max_attempts", "num_ctx", "timeout_seconds"):
        _positive("translation", key, getattr(translation, key))
    if translation.context_size < 0:
        raise ConfigError("`translation.context_size` không được âm.")
    kwargs["translation"] = translation

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
