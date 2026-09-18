"""Command-line interface cho YouTube Vietnamese Dubber.

Checkpoint 1: subcommand ``download`` (tải một video YouTube).
Checkpoint 2: subcommand ``transcribe`` (trích audio + speech-to-text).
Checkpoint 3: subcommand ``translate`` (dịch transcript) + ``--config``.
Các subcommand khác (tts, render, dub, playlist, ...) sẽ được thêm dần ở
các checkpoint tiếp theo, xem docs/IMPLEMENTATION_PLAN.md.

Flag CLI để mặc định ``None`` để phân biệt "không truyền" với "truyền
đúng giá trị mặc định": không truyền thì lấy từ config.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from app import __version__
from app.config import AppConfig, ConfigError, load_config


def build_parser() -> argparse.ArgumentParser:
    """Tạo argument parser cấp cao nhất + các subcommand đã implement."""
    parser = argparse.ArgumentParser(
        prog="app",
        description=(
            "YouTube Vietnamese Dubber — tạo bản thuyết minh tiếng Việt "
            "cho video/playlist YouTube, ưu tiên chạy local, chi phí thấp."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    # Parent parser: `--config` đặt được sau tên subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config",
        default=None,
        help="File config YAML (mặc định: ./config.yaml nếu có). Xem config.example.yaml.",
    )

    subparsers = parser.add_subparsers(dest="command")

    download_parser = subparsers.add_parser(
        "download",
        parents=[common],
        help="Tải một video YouTube, tạo metadata.json + source.mp4.",
    )
    download_parser.add_argument("url", help="URL video YouTube cần tải.")
    download_parser.add_argument(
        "--workspace",
        default=None,
        help="Thư mục gốc chứa các episode (mặc định: `workspace` trong config, hoặc output).",
    )
    download_parser.add_argument(
        "--force",
        action="store_true",
        help="Tải lại source.mp4 dù đã tồn tại (bỏ qua resume).",
    )

    transcribe_parser = subparsers.add_parser(
        "transcribe",
        parents=[common],
        help="Trích audio + speech-to-text (faster-whisper), tạo audio.wav + transcript.json.",
    )
    transcribe_parser.add_argument(
        "episode_dir",
        help="Thư mục episode đã có source.mp4 (tạo bởi subcommand `download`).",
    )
    transcribe_parser.add_argument(
        "--whisper-model",
        default=None,
        help="Model faster-whisper (tiny/base/small/medium/large-v3, ...). Mặc định: `whisper.model` trong config, hoặc medium.",
    )
    transcribe_parser.add_argument(
        "--device",
        default=None,
        help="Device chạy faster-whisper (auto/cpu/cuda). Mặc định: `whisper.device` trong config, hoặc auto.",
    )
    transcribe_parser.add_argument(
        "--source-lang",
        default="auto",
        help=(
            "Mã ngôn ngữ gốc của video (vd zh, en, ja). Mặc định: auto "
            "(để Whisper tự nhận dạng). Nên ép cứng nếu auto-detect đoán sai."
        ),
    )
    transcribe_parser.add_argument(
        "--force",
        action="store_true",
        help="Trích audio + transcribe lại dù audio.wav/transcript.json đã tồn tại.",
    )

    translate_parser = subparsers.add_parser(
        "translate",
        parents=[common],
        help="Dịch transcript.json sang tiếng Việt, tạo translated.json.",
    )
    translate_parser.add_argument(
        "episode_dir",
        help="Thư mục episode đã có transcript.json (tạo bởi subcommand `transcribe`).",
    )
    translate_parser.add_argument(
        "--translator",
        choices=["ollama"],
        default=None,
        help="Backend dịch. Mặc định: `translation.provider` trong config, hoặc ollama.",
    )
    translate_parser.add_argument(
        "--model",
        default=None,
        help="Tên model dịch (vd qwen3:8b). Mặc định: `translation.model` trong config.",
    )
    translate_parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Số segment mỗi lần gọi model. Mặc định: `translation.batch_size` trong config, hoặc 25.",
    )
    translate_parser.add_argument(
        "--target-lang",
        default=None,
        help="Mã ngôn ngữ đích. Mặc định: `target_language` trong config, hoặc vi.",
    )
    translate_parser.add_argument(
        "--force",
        action="store_true",
        help="Dịch lại từ đầu dù translated.json (hoặc tiến trình dịch dở) đã tồn tại.",
    )

    return parser


def _load_config(args: argparse.Namespace) -> AppConfig:
    return load_config(Path(args.config) if args.config else None)


def _cmd_download(args: argparse.Namespace, config: AppConfig) -> int:
    # Import cục bộ: các subcommand chưa dùng tới không cần yt-dlp có sẵn.
    from app.youtube.download import VideoDownloadError, download_video

    workspace = Path(args.workspace) if args.workspace else config.workspace
    try:
        episode = download_video(args.url, workspace, force=args.force)
    except VideoDownloadError as exc:
        print(f"[download] LỖI: {exc}", file=sys.stderr)
        return 1

    print(f"[download] video_id : {episode.video_id}")
    print(f"[download] title    : {episode.title}")
    print(f"[download] episode  : {episode.episode_dir}")
    print(f"[download] metadata : {episode.metadata_path}")
    print(f"[download] source   : {episode.source_path}")
    return 0


def _cmd_transcribe(args: argparse.Namespace, config: AppConfig) -> int:
    # Import cục bộ: subcommand chưa dùng tới không cần ffmpeg/faster-whisper có sẵn.
    from app.audio.ffmpeg import AUDIO_FILENAME, AudioExtractionError, extract_audio
    from app.transcription.whisper import (
        TRANSCRIPT_FILENAME,
        TranscriptionError,
        transcribe_audio,
    )
    from app.youtube.download import SOURCE_FILENAME

    episode_dir = Path(args.episode_dir)
    source_path = episode_dir / SOURCE_FILENAME
    audio_path = episode_dir / AUDIO_FILENAME
    transcript_path = episode_dir / TRANSCRIPT_FILENAME

    try:
        extract_audio(source_path, audio_path, force=args.force)
        result = transcribe_audio(
            audio_path,
            transcript_path,
            model_size=args.whisper_model or config.whisper.model,
            device=args.device or config.whisper.device,
            compute_type=config.whisper.compute_type,
            language=None if args.source_lang == "auto" else args.source_lang,
            force=args.force,
        )
    except (AudioExtractionError, TranscriptionError) as exc:
        print(f"[transcribe] LỖI: {exc}", file=sys.stderr)
        return 1

    print(f"[transcribe] audio      : {audio_path}")
    print(f"[transcribe] transcript : {result.transcript_path}")
    print(f"[transcribe] language   : {result.language}")
    print(f"[transcribe] segments   : {len(result.segments)}")
    return 0


def _cmd_translate(args: argparse.Namespace, config: AppConfig) -> int:
    from app.transcription.whisper import TRANSCRIPT_FILENAME
    from app.translation import create_translator
    from app.translation.base import TranslationError
    from app.translation.translate import TRANSLATED_FILENAME, translate_transcript

    overrides = {
        key: value
        for key, value in {
            "provider": args.translator,
            "model": args.model,
            "batch_size": args.batch_size,
        }.items()
        if value is not None
    }
    tconfig = replace(config.translation, **overrides)
    if tconfig.batch_size <= 0:
        print("[translate] LỖI: --batch-size phải lớn hơn 0.", file=sys.stderr)
        return 1
    target_language = args.target_lang or config.target_language

    episode_dir = Path(args.episode_dir)
    try:
        translator = create_translator(tconfig)
        result = translate_transcript(
            episode_dir / TRANSCRIPT_FILENAME,
            episode_dir / TRANSLATED_FILENAME,
            translator,
            target_language=target_language,
            batch_size=tconfig.batch_size,
            context_size=tconfig.context_size,
            max_attempts=tconfig.max_attempts,
            force=args.force,
            # flush: khi stdout bị pipe/ghi ra file log, Python buffer output
            # nên không thấy tiến trình cho tới khi lệnh kết thúc.
            log=lambda message: print(message, flush=True),
        )
    except TranslationError as exc:
        print(f"[translate] LỖI: {exc}", file=sys.stderr)
        return 1

    if result.skipped:
        print("[translate] SKIP: translated.json đã tồn tại (dùng --force để dịch lại).")
    print(f"[translate] translated : {result.translated_path}")
    print(f"[translate] language   : {result.source_language} -> {result.target_language}")
    print(f"[translate] segments   : {len(result.segments)}")
    if result.failed_ids:
        # C3: một câu khó không được chặn cả tập, nhưng vẫn phải cảnh báo rõ
        # để người dùng biết chạy lại lệnh (exit 0 để playlist chạy tiếp).
        ids = ", ".join(str(i) for i in result.failed_ids)
        print(
            f"[translate] CẢNH BÁO: {len(result.failed_ids)} segment chưa dịch được "
            f"(id {ids}) — chạy lại lệnh để thử lại."
        )
    return 0


_COMMANDS = {
    "download": _cmd_download,
    "transcribe": _cmd_transcribe,
    "translate": _cmd_translate,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point dùng bởi ``python -m app``."""
    parser = build_parser()
    args = parser.parse_args(argv)

    handler = _COMMANDS.get(args.command)
    if handler is None:
        # Chưa có subcommand nào được chọn — hiển thị help.
        parser.print_help()
        return 0

    try:
        config = _load_config(args)
    except ConfigError as exc:
        print(f"[config] LỖI: {exc}", file=sys.stderr)
        return 1
    return handler(args, config)


if __name__ == "__main__":
    raise SystemExit(main())
