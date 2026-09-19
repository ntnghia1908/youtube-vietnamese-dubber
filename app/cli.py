"""Command-line interface cho YouTube Vietnamese Dubber.

Checkpoint 1: subcommand ``download`` (tải một video YouTube).
Checkpoint 2: subcommand ``transcribe`` (trích audio + speech-to-text).
Checkpoint 3: subcommand ``translate`` (dịch transcript) + ``--config``.
Checkpoint 4: subcommand ``tts`` (tổng hợp giọng nói bằng edge-tts).
Checkpoint 5: subcommand ``normalize`` (chuẩn hoá timing tts vs slot gốc).
Checkpoint 6: subcommand ``render`` (dựng voice_track.wav + mix ra output_vi.mp4).
Checkpoint 6.5: subcommand ``glossary`` (tạo nháp glossary.yaml bằng model) +
``translate --glossary`` (glossary dùng chung, gộp với <episode>/glossary.yaml).
Checkpoint 7: subcommand ``dub`` (end-to-end: download -> transcribe ->
translate -> tts -> normalize -> render từ một URL, gọi thẳng các hàm stage).
Checkpoint 8: subcommand ``playlist`` (gọi ``dub`` tuần tự cho mọi tập của
một playlist, ghi tiến trình vào playlist.json để resume). ``dub`` và
``playlist`` dùng chung bộ flag qua ``_add_dub_arguments``/``_resolve_dub_options``.

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
from app.config import (
    AppConfig,
    ConfigError,
    load_config,
    validate_mixing,
    validate_rate_or_volume,
    validate_timing_ratios,
)


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
    translate_parser.add_argument(
        "--glossary",
        default=None,
        help=(
            "Glossary dùng chung (vd cả series), gộp với <episode>/glossary.yaml (file của "
            "tập luôn tự nhận nếu có). Mặc định: `translation.glossary` trong config."
        ),
    )

    glossary_parser = subparsers.add_parser(
        "glossary",
        parents=[common],
        help="Tạo NHÁP glossary.yaml (nhân vật, xưng hô, thuật ngữ) từ transcript.json bằng model.",
    )
    glossary_parser.add_argument(
        "episode_dir",
        help="Thư mục episode đã có transcript.json (tạo bởi subcommand `transcribe`).",
    )
    glossary_parser.add_argument(
        "--model",
        default=None,
        help="Tên model tạo nháp (vd qwen3:8b). Mặc định: `translation.model` trong config.",
    )
    glossary_parser.add_argument(
        "--max-chars",
        type=int,
        default=None,
        help=(
            "Số ký tự transcript tối đa gửi model. Mặc định: `translation.glossary_max_chars` "
            "trong config, hoặc 8000."
        ),
    )
    glossary_parser.add_argument(
        "--force",
        action="store_true",
        help="Tạo lại dù glossary.yaml đã tồn tại (bản cũ được lưu ở glossary.yaml.bak).",
    )

    tts_parser = subparsers.add_parser(
        "tts",
        parents=[common],
        help="Tổng hợp giọng nói tiếng Việt (edge-tts) từ translated.json, tạo tts/*.mp3.",
    )
    tts_parser.add_argument(
        "episode_dir",
        help="Thư mục episode đã có translated.json (tạo bởi subcommand `translate`).",
    )
    tts_parser.add_argument(
        "--voice",
        default=None,
        help="Tên voice edge-tts (vd vi-VN-HoaiMyNeural). Mặc định: `tts.voice` trong config.",
    )
    tts_parser.add_argument(
        "--rate",
        default=None,
        help=(
            "Tốc độ đọc, dạng +N%%/-N%% (vd +20%%). Mặc định: `tts.rate` trong config. "
            "Giá trị âm phải dùng dạng --rate=-10%% (không phải --rate -10%%), "
            "nếu không argparse hiểu nhầm thành một flag khác."
        ),
    )
    tts_parser.add_argument(
        "--volume",
        default=None,
        help="Âm lượng, dạng +N%%/-N%%. Mặc định: `tts.volume` trong config. Dùng --volume=-10%% cho giá trị âm.",
    )
    tts_parser.add_argument(
        "--force",
        action="store_true",
        help="Tổng hợp lại toàn bộ segment dù tts/manifest.json đã đủ.",
    )

    normalize_parser = subparsers.add_parser(
        "normalize",
        parents=[common],
        help="Chuẩn hoá timing giữa tts/*.mp3 và slot gốc, tạo normalized.json.",
    )
    normalize_parser.add_argument(
        "episode_dir",
        help="Thư mục episode đã có translated.json + tts/ (tạo bởi subcommand `tts`).",
    )
    normalize_parser.add_argument(
        "--max-tempo",
        type=float,
        default=None,
        help="Co giãn (ffmpeg atempo) tối đa. Mặc định: `timing.max_tempo` trong config, hoặc 1.25.",
    )
    normalize_parser.add_argument(
        "--force",
        action="store_true",
        help="Tính lại toàn bộ (probe + co giãn) dù normalized.json đã khớp.",
    )

    render_parser = subparsers.add_parser(
        "render",
        parents=[common],
        help="Ghép voice_track.wav, mix với audio gốc, xuất output_vi.mp4.",
    )
    render_parser.add_argument(
        "episode_dir",
        help="Thư mục episode đã có normalized.json + source.mp4 (tạo bởi `normalize`, `download`).",
    )
    render_parser.add_argument(
        "--original-volume",
        type=float,
        default=None,
        help="Volume audio gốc, 0.0–1.0. Mặc định: `mixing.original_volume` trong config, hoặc 0.30.",
    )
    render_parser.add_argument(
        "--max-shift",
        type=float,
        default=None,
        help=(
            "Số giây dời tối đa một câu khi câu trước tràn slot (0 = không dời, đè). "
            "Mặc định: `mixing.max_shift_seconds` trong config, hoặc 1.0."
        ),
    )
    render_parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Cho phép segment thiếu audio (status missing): chèn im lặng thay vì báo lỗi.",
    )
    render_parser.add_argument(
        "--force",
        action="store_true",
        help="Dựng lại voice_track.wav và mux lại output_vi.mp4 dù đã khớp.",
    )

    dub_parser = subparsers.add_parser(
        "dub",
        parents=[common],
        help=(
            "Chạy toàn bộ pipeline cho một video (download -> transcribe -> translate -> "
            "tts -> normalize -> render), tự resume và tự sửa lỗi tạm thời."
        ),
    )
    dub_parser.add_argument("url", help="URL video YouTube cần lồng tiếng.")
    _add_dub_arguments(dub_parser)

    playlist_parser = subparsers.add_parser(
        "playlist",
        parents=[common],
        help=(
            "Chạy `dub` tuần tự cho mọi tập trong một playlist YouTube, ghi tiến trình vào "
            "playlist.json để resume, một tập lỗi không chặn cả playlist."
        ),
    )
    playlist_parser.add_argument("url", help="URL playlist YouTube cần lồng tiếng.")
    _add_dub_arguments(
        playlist_parser,
        force_help=(
            "Làm lại MỌI tập dù đã completed (tải lại video, chạy lại Whisper, dịch lại, tổng "
            "hợp giọng lại toàn bộ playlist) — tốn thời gian/mạng rất nhiều, nên dùng kèm --items "
            "để giới hạn phạm vi."
        ),
    )
    playlist_parser.add_argument(
        "--items",
        default=None,
        help='Chỉ xử lý các tập này, vd "1-3,5" (mặc định: mọi tập trong playlist).',
    )
    playlist_parser.add_argument(
        "--recheck",
        action="store_true",
        help=(
            "Gọi lại `dub` cả với tập đã completed (mỗi stage tự resume, chỉ làm lại phần thật "
            "sự đổi) — dùng sau khi sửa glossary dùng chung cho cả series."
        ),
    )
    playlist_parser.add_argument(
        "--download-only",
        action="store_true",
        help=(
            "Chỉ chạy luồng tải cho các tập được chọn (một tập mỗi lần), KHÔNG "
            "transcribe/translate/tts/render — dùng để tải trước cả playlist rồi xử lý offline sau."
        ),
    )

    return parser


def _add_dub_arguments(
    parser: argparse.ArgumentParser,
    *,
    force_help: str = (
        "Làm lại MỌI stage dù artifact đã có (tải lại video, chạy lại Whisper, dịch lại, "
        "tổng hợp giọng lại) — tốn thời gian và gọi lại AI/mạng, chỉ dùng khi thật sự cần."
    ),
) -> None:
    """Flag dùng chung giữa ``dub`` và ``playlist`` (CP8) — không gồm ``url``
    (positional, help text khác nhau giữa hai lệnh) hay ``--config`` (đã có
    ở parent parser ``common``)."""
    parser.add_argument(
        "--workspace",
        default=None,
        help="Thư mục gốc chứa các episode (mặc định: `workspace` trong config, hoặc output).",
    )
    parser.add_argument(
        "--source-lang",
        default="auto",
        help=(
            "Mã ngôn ngữ gốc của video (vd zh, en, ja). Mặc định: auto (để Whisper tự nhận "
            "dạng). Nên ép cứng nếu auto-detect đoán sai (vd zh bị nhận nhầm thành en)."
        ),
    )
    parser.add_argument(
        "--glossary",
        default=None,
        help=(
            "Glossary dùng chung (vd cả series), gộp với <episode>/glossary.yaml (file của tập "
            "luôn tự nhận nếu có). Mặc định: `translation.glossary` trong config."
        ),
    )
    parser.add_argument(
        "--original-volume",
        type=float,
        default=None,
        help="Volume audio gốc khi mix, 0.0–1.0. Mặc định: `mixing.original_volume` trong config, hoặc 0.30.",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Cho phép segment thiếu audio sau khi đã tự thử sửa: chèn im lặng thay vì báo lỗi.",
    )
    parser.add_argument("--force", action="store_true", help=force_help)


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
    from app.translation.glossary import load_effective_glossary
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
    # Flag --glossary ghi đè config; chỉ là tầng dùng chung, còn
    # <ep>/glossary.yaml luôn tự nhận nếu có.
    shared_glossary = args.glossary if args.glossary is not None else tconfig.glossary
    try:
        # Trong khối try: GlossaryError là một TranslationError (file sai đường
        # dẫn/YAML hỏng phải báo lỗi rõ, không được dịch lặng lẽ không glossary).
        glossary, glossary_paths = load_effective_glossary(
            episode_dir, Path(shared_glossary) if shared_glossary else None
        )
        if glossary is not None:
            print(
                "[translate] glossary : " + ", ".join(str(p) for p in glossary_paths),
                flush=True,
            )
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
            glossary=glossary,
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


def _cmd_glossary(args: argparse.Namespace, config: AppConfig) -> int:
    from app.translation import create_translator
    from app.translation.base import TranslationError
    from app.translation.glossary_draft import draft_glossary_file

    tconfig = replace(config.translation, **({"model": args.model} if args.model else {}))
    max_chars = args.max_chars if args.max_chars is not None else tconfig.glossary_max_chars
    if max_chars <= 0:
        print("[glossary] LỖI: --max-chars phải lớn hơn 0.", file=sys.stderr)
        return 1

    episode_dir = Path(args.episode_dir)
    try:
        translator = create_translator(tconfig)
        result = draft_glossary_file(
            episode_dir,
            translator,
            target_language=config.target_language,
            max_chars=max_chars,
            max_attempts=tconfig.max_attempts,
            force=args.force,
            # flush: giống _cmd_translate — thấy log ngay cả khi stdout bị pipe.
            log=lambda message: print(message, flush=True),
        )
    except TranslationError as exc:
        # GlossaryError là một TranslationError.
        print(f"[glossary] LỖI: {exc}", file=sys.stderr)
        return 1

    if result.skipped:
        print(
            "[glossary] SKIP: glossary.yaml đã tồn tại (dùng --force để tạo lại; "
            "bản cũ được lưu ở glossary.yaml.bak)."
        )
    print(f"[glossary] glossary   : {result.glossary_path}")
    print(f"[glossary] characters : {len(result.glossary.characters)}")
    print(f"[glossary] address    : {len(result.glossary.address)}")
    print(f"[glossary] terms      : {len(result.glossary.terms)}")
    if result.backup_path is not None:
        print(f"[glossary] backup     : {result.backup_path}")
    if not result.skipped:
        print(
            "[glossary] LƯU Ý: đây là bản nháp do model tạo — mở file, sửa tên nhân vật/xưng hô "
            f'cho đúng rồi chạy `python -m app translate "{episode_dir}"`.'
        )
    return 0


def _cmd_tts(args: argparse.Namespace, config: AppConfig) -> int:
    from app.translation.translate import TRANSLATED_FILENAME
    from app.tts import create_tts_engine
    from app.tts.base import TTSError
    from app.tts.synthesize import TTS_DIRNAME, synthesize_translation

    overrides = {
        key: value
        for key, value in {
            "voice": args.voice,
            "rate": args.rate,
            "volume": args.volume,
        }.items()
        if value is not None
    }
    tconfig = replace(config.tts, **overrides)
    for key in ("rate", "volume"):
        try:
            validate_rate_or_volume("tts", key, getattr(tconfig, key))
        except ConfigError as exc:
            print(f"[tts] LỖI: {exc}", file=sys.stderr)
            return 1

    episode_dir = Path(args.episode_dir)
    try:
        engine = create_tts_engine(tconfig)
        result = synthesize_translation(
            episode_dir / TRANSLATED_FILENAME,
            episode_dir / TTS_DIRNAME,
            engine,
            max_attempts=tconfig.max_attempts,
            concurrency=tconfig.concurrency,
            force=args.force,
            # flush: giống _cmd_translate — playlist chạy hàng giờ, log phải
            # thấy ngay cả khi stdout bị pipe/ghi ra file.
            log=lambda message: print(message, flush=True),
        )
    except TTSError as exc:
        print(f"[tts] LỖI: {exc}", file=sys.stderr)
        return 1

    if result.skipped:
        print("[tts] SKIP: tts/ đã đủ (dùng --force để tạo lại).")
    print(f"[tts] manifest    : {result.manifest_path}")
    print(f"[tts] tổng hợp    : {len(result.synthesized_ids)}")
    print(f"[tts] cache       : {len(result.cached_ids)}")
    print(f"[tts] rỗng        : {len(result.empty_ids)}")
    if result.failed_ids:
        # Giống C3 của CP3: một segment lỗi không được chặn cả episode,
        # nhưng vẫn phải cảnh báo rõ để người dùng biết chạy lại lệnh.
        ids = ", ".join(str(i) for i in result.failed_ids)
        print(
            f"[tts] CẢNH BÁO: {len(result.failed_ids)} segment lỗi (id {ids}) — "
            "chạy lại lệnh để thử lại."
        )
    return 0


def _cmd_normalize(args: argparse.Namespace, config: AppConfig) -> int:
    from app.synchronization.timing import TimingError, normalize_timing

    max_tempo = args.max_tempo if args.max_tempo is not None else config.timing.max_tempo
    normal_max_ratio = config.timing.normal_max_ratio
    try:
        validate_timing_ratios(normal_max_ratio, max_tempo)
    except ConfigError as exc:
        print(f"[normalize] LỖI: {exc}", file=sys.stderr)
        return 1

    episode_dir = Path(args.episode_dir)
    try:
        result = normalize_timing(
            episode_dir,
            normal_max_ratio=normal_max_ratio,
            max_tempo=max_tempo,
            force=args.force,
            log=lambda message: print(message, flush=True),
        )
    except TimingError as exc:
        print(f"[normalize] LỖI: {exc}", file=sys.stderr)
        return 1

    if result.skipped:
        print("[normalize] SKIP: normalized.json đã khớp (dùng --force để tính lại).")
    total = (
        len(result.normal_ids)
        + len(result.stretched_ids)
        + len(result.too_long_ids)
        + len(result.silent_ids)
        + len(result.missing_ids)
    )
    print(f"[normalize] segments  : {total}")
    print(f"[normalize] normal    : {len(result.normal_ids)}")
    print(f"[normalize] stretched : {len(result.stretched_ids)}")
    too_long_suffix = f" (id {', '.join(str(i) for i in result.too_long_ids)})" if result.too_long_ids else ""
    print(f"[normalize] too_long  : {len(result.too_long_ids)}{too_long_suffix}")
    print(f"[normalize] silent    : {len(result.silent_ids)}")
    print(f"[normalize] missing   : {len(result.missing_ids)}")
    print(f"[normalize] output    : {result.normalized_path}")
    if result.missing_ids:
        # Giống C3/A3 của các stage trước: thiếu audio không được chặn cả
        # episode, nhưng phải cảnh báo rõ để người dùng biết chạy lại `tts`.
        ids = ", ".join(str(i) for i in result.missing_ids)
        print(
            f"[normalize] CẢNH BÁO: {len(result.missing_ids)} segment thiếu audio "
            f"(id {ids}) — chạy lại `tts` rồi `normalize`."
        )
    return 0


def _cmd_render(args: argparse.Namespace, config: AppConfig) -> int:
    # Import cục bộ: subcommand chưa dùng tới không cần ffmpeg có sẵn.
    from app.audio.render import RenderError, render_episode

    original_volume = (
        args.original_volume if args.original_volume is not None else config.mixing.original_volume
    )
    max_shift = args.max_shift if args.max_shift is not None else config.mixing.max_shift_seconds
    # Không có flag cho speech_volume: chỉnh ở `mixing.speech_volume` (config).
    speech_volume = config.mixing.speech_volume
    try:
        validate_mixing(original_volume, speech_volume, max_shift)
    except ConfigError as exc:
        print(f"[render] LỖI: {exc}", file=sys.stderr)
        return 1

    episode_dir = Path(args.episode_dir)
    try:
        result = render_episode(
            episode_dir,
            original_volume=original_volume,
            speech_volume=speech_volume,
            max_shift=max_shift,
            allow_missing=args.allow_missing,
            force=args.force,
            log=lambda message: print(message, flush=True),
        )
    except RenderError as exc:
        print(f"[render] LỖI: {exc}", file=sys.stderr)
        return 1

    def _ids_suffix(ids: list[int]) -> str:
        return f" (id {', '.join(str(i) for i in ids)})" if ids else ""

    total = len(result.placed_ids) + len(result.silent_ids) + len(result.missing_ids)
    print(f"[render] segments     : {total}")
    print(f"[render] placed       : {len(result.placed_ids)}")
    print(f"[render] silent       : {len(result.silent_ids)}")
    print(f"[render] missing      : {len(result.missing_ids)}")
    shifted_suffix = f" (tối đa {result.max_shift_seen:.2f}s)" if result.shifted_ids else ""
    print(f"[render] shifted      : {len(result.shifted_ids)}{shifted_suffix}")
    print(f"[render] overlap      : {len(result.overlap_ids)}{_ids_suffix(result.overlap_ids)}")
    print(f"[render] voice_track  : {result.voice_track_path}")
    print(f"[render] output       : {result.output_path}")
    if result.missing_ids:
        # Chỉ tới được đây khi --allow-missing: vẫn phải nói rõ bản thuyết
        # minh đang thiếu câu, không được lặng lẽ lọt ra sản phẩm cuối.
        ids = ", ".join(str(i) for i in result.missing_ids)
        print(
            f"[render] CẢNH BÁO: {len(result.missing_ids)} segment thiếu audio "
            f"(id {ids}) được thay bằng im lặng."
        )
    return 0


def _resolve_dub_options(
    args: argparse.Namespace, config: AppConfig, *, prefix: str
) -> DubOptions | None:
    """Gộp flag CLI > config thành ``DubOptions``, dùng chung cho ``dub`` và
    ``playlist`` (CP8) — hai lệnh có cùng bộ flag, xem ``_add_dub_arguments``.

    ``prefix`` chỉ dùng để tiền tố thông báo lỗi (``[dub]``/``[playlist]``).
    Trả về ``None`` khi validate lỗi — lỗi đã được in ra stderr, người gọi
    chỉ cần ``return 1`` (không gọi mạng/pipeline khi config sai).
    """
    workspace = Path(args.workspace) if args.workspace else config.workspace
    source_lang = None if args.source_lang == "auto" else args.source_lang
    shared_glossary = args.glossary if args.glossary is not None else config.translation.glossary
    original_volume = (
        args.original_volume if args.original_volume is not None else config.mixing.original_volume
    )
    try:
        validate_mixing(original_volume, config.mixing.speech_volume, config.mixing.max_shift_seconds)
    except ConfigError as exc:
        print(f"[{prefix}] LỖI: {exc}", file=sys.stderr)
        return None

    # Import cục bộ: kéo theo yt-dlp/faster-whisper/Ollama/edge-tts, các
    # subcommand khác (vd download đơn lẻ) không cần tới.
    from app.pipeline.dub import DubOptions

    return DubOptions(
        workspace=workspace,
        source_lang=source_lang,
        shared_glossary=Path(shared_glossary) if shared_glossary else None,
        original_volume=original_volume,
        allow_missing=args.allow_missing,
        force=args.force,
    )


def _cmd_dub(args: argparse.Namespace, config: AppConfig) -> int:
    from app.pipeline.dub import DubError, run_dub

    options = _resolve_dub_options(args, config, prefix="dub")
    if options is None:
        return 1
    try:
        result = run_dub(
            args.url,
            config,
            options,
            # flush: giống _cmd_translate/_cmd_tts — playlist/video dài chạy
            # hàng giờ, log phải thấy ngay cả khi stdout bị pipe/ghi ra file.
            log=lambda message: print(message, flush=True),
        )
    except DubError as exc:
        print(f"[dub] LỖI {exc}", file=sys.stderr)
        return 1

    print(f"[dub] episode    : {result.episode_dir}")
    print(f"[dub] ngôn ngữ   : {result.source_language} -> {config.target_language}")
    print(f"[dub] segments   : {result.segments}")
    too_long_suffix = (
        f" (id {', '.join(str(i) for i in result.too_long_ids)})" if result.too_long_ids else ""
    )
    print(f"[dub] too_long   : {len(result.too_long_ids)}{too_long_suffix}")
    print(f"[dub] sửa lại    : {result.repair_rounds_used} vòng")
    total_seconds = sum(result.stage_seconds.values())
    times = ", ".join(f"{name} {seconds:.1f}s" for name, seconds in result.stage_seconds.items())
    print(f"[dub] thời gian  : {times} (tổng {total_seconds:.1f}s)")
    print(f"[dub] output     : {result.output_path}")
    if result.translate_failed_ids:
        ids = ", ".join(str(i) for i in result.translate_failed_ids)
        print(
            f"[dub] CẢNH BÁO: {len(result.translate_failed_ids)} segment dịch lỗi (id {ids}) — "
            "các câu này im lặng trong output."
        )
    if result.missing_ids:
        ids = ", ".join(str(i) for i in result.missing_ids)
        print(
            f"[dub] CẢNH BÁO: {len(result.missing_ids)} segment thiếu audio (id {ids}) "
            "được thay bằng im lặng."
        )
    return 0


def _cmd_playlist(args: argparse.Namespace, config: AppConfig) -> int:
    from app.pipeline.playlist import PlaylistError, PlaylistOptions, parse_item_spec, run_playlist

    dub_options = _resolve_dub_options(args, config, prefix="playlist")
    if dub_options is None:
        return 1

    items = None
    if args.items is not None:
        try:
            items = parse_item_spec(args.items)
        except PlaylistError as exc:
            # --items sai không được chạm mạng: fetch playlist chỉ xảy ra
            # sau bước này (đúng "Hành vi bắt buộc" của cp-8.md).
            print(f"[playlist] LỖI: {exc}", file=sys.stderr)
            return 1

    playlist_options = PlaylistOptions(
        dub=dub_options,
        items=items,
        recheck=args.recheck,
        max_consecutive_failures=config.pipeline.max_consecutive_failures,
        download_only=args.download_only,
    )
    try:
        result = run_playlist(
            args.url,
            config,
            playlist_options,
            # flush: playlist chạy hàng giờ, log phải thấy ngay cả khi stdout bị pipe/ghi ra file.
            log=lambda message: print(message, flush=True),
        )
    except PlaylistError as exc:
        print(f"[playlist] LỖI: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # Không để traceback mặc định của Python lộ ra: người dùng Ctrl+C
        # giữa một playlist dài là chuyện bình thường, không phải lỗi.
        print(
            "[playlist] Đã dừng (Ctrl+C). Chạy lại đúng lệnh này để tiếp tục.",
            file=sys.stderr,
        )
        return 130

    width = max(2, len(str(result.total)))
    print(f"[playlist] thư mục   : {result.playlist_dir}")
    print(f"[playlist] {result.total} tập (chọn {result.selected})")

    if args.download_only:
        # SỬA ĐỔI 1: --download-only chỉ tải, không xử lý -> outcome chỉ có
        # "downloaded"/"failed"/"not_run" (không "completed"/"skipped").
        counts = {"downloaded": 0, "failed": 0, "not_run": 0}
        for episode in result.episodes:
            counts[episode.outcome] = counts.get(episode.outcome, 0) + 1
        print(f"[playlist] downloaded {counts['downloaded']} | failed {counts['failed']}")
    else:
        counts = {"completed": 0, "skipped": 0, "failed": 0, "not_run": 0}
        for episode in result.episodes:
            counts[episode.outcome] = counts.get(episode.outcome, 0) + 1
        print(
            f"[playlist] completed {counts['completed']} | skipped {counts['skipped']} | "
            f"failed {counts['failed']} | not_run {counts['not_run']}"
        )

    for episode in result.episodes:
        if episode.outcome != "failed":
            continue
        first_line = episode.error.splitlines()[0] if episode.error else ""
        print(f"[playlist] LỖI  EP{episode.index:0{width}d} {episode.video_id} {first_line}")
    for episode in result.episodes:
        # Cảnh báo chỉ cho tập completed TRONG LẦN CHẠY NÀY (episode.result
        # chỉ có giá trị khi run_dub vừa thật sự chạy — skipped/downloaded không có).
        if episode.outcome != "completed" or episode.result is None:
            continue
        ep_tag = f"EP{episode.index:0{width}d}"
        if episode.result.translate_failed_ids:
            ids = ", ".join(str(i) for i in episode.result.translate_failed_ids)
            print(
                f"[playlist] CẢNH BÁO {ep_tag}: {len(episode.result.translate_failed_ids)} câu "
                f"dịch lỗi (id {ids}) — im lặng trong output"
            )
        if episode.result.missing_ids:
            ids = ", ".join(str(i) for i in episode.result.missing_ids)
            print(
                f"[playlist] CẢNH BÁO {ep_tag}: {len(episode.result.missing_ids)} segment thiếu "
                f"audio (id {ids}) — chèn im lặng"
            )

    if counts["failed"] > 0 or result.aborted:
        return 1
    return 0


_COMMANDS = {
    "download": _cmd_download,
    "transcribe": _cmd_transcribe,
    "translate": _cmd_translate,
    "glossary": _cmd_glossary,
    "tts": _cmd_tts,
    "normalize": _cmd_normalize,
    "render": _cmd_render,
    "dub": _cmd_dub,
    "playlist": _cmd_playlist,
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
