"""Stage: điều phối end-to-end ``dub`` (download -> ... -> render) — Checkpoint 7.

``run_dub`` gọi thẳng các hàm stage đã có ở CP1-6.5 (không đi qua ``_cmd_*``
của CLI con). Mỗi stage tự resume theo artifact của chính nó (không có
``dub.json``/state file riêng — xem docs/decisions/checkpoint-7.md mục A).

Hai việc dub tự điều phối mà các stage không tự làm:
- **translate**: gọi lại (không ``force``) khi còn ``failed_ids``, tối đa
  ``config.pipeline.repair_rounds`` lần (CP3 A1: gọi lại không force chỉ
  dịch lại đúng các segment lỗi).
- **tts + normalize**: sau khi ``normalize_timing`` còn ``missing_ids``,
  gọi lại ``tts`` rồi ``normalize`` (không ``force``) tới khi hết hoặc hết
  số vòng (CP5 A3 / CP6 A2: ``render_episode`` không tự chạy lại stage
  trước).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.audio.ffmpeg import AUDIO_FILENAME, AudioExtractionError, extract_audio
from app.audio.render import RenderError, render_episode
from app.config import (
    AppConfig,
    ConfigError,
    validate_mixing,
    validate_rate_or_volume,
    validate_timing_ratios,
)
from app.synchronization.timing import TimingError, normalize_timing
from app.transcription.whisper import TRANSCRIPT_FILENAME, TranscriptionError, transcribe_audio
from app.translation import create_translator
from app.translation.base import TranslationError  # GlossaryError là subclass
from app.translation.glossary import GLOSSARY_FILENAME, load_effective_glossary
from app.translation.translate import TRANSLATED_FILENAME, translate_transcript
from app.tts import create_tts_engine
from app.tts.base import TTSError
from app.tts.synthesize import TTS_DIRNAME, synthesize_translation
from app.youtube.download import VideoDownloadError, download_video

STAGES = ("download", "transcribe", "translate", "tts", "normalize", "render")


class DubError(RuntimeError):
    """Lỗi ở một stage cụ thể; ``stage`` là một phần tử của ``STAGES``."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"[{stage}] {message}")
        self.stage = stage


@dataclass(frozen=True)
class DubOptions:
    workspace: Path
    source_lang: str | None = None  # None = auto-detect (Whisper)
    shared_glossary: Path | None = None  # đã resolve flag > config
    original_volume: float = 0.30  # đã resolve flag > config
    allow_missing: bool = False
    force: bool = False


@dataclass
class DubResult:
    episode_dir: Path
    output_path: Path
    source_language: str  # ngôn ngữ ghi trong transcript.json
    segments: int
    translate_failed_ids: list[int]  # còn lỗi sau mọi vòng -> câu im lặng trong output
    missing_ids: list[int]  # chỉ khác rỗng khi allow_missing=True
    too_long_ids: list[int]
    repair_rounds_used: int  # tổng vòng lặp lại (translate + tts/normalize)
    glossary_paths: list[Path]  # rỗng = dịch không glossary
    stage_seconds: dict[str, float]  # thời gian thực mỗi stage (cả khi skip)
    skipped_stages: list[str]  # stage không làm gì (artifact đã khớp)


def _log_start(log: Callable[[str], None], index: int, total: int, name: str) -> None:
    log(f"[dub] ({index}/{total}) {name} ...")


def _log_done(
    log: Callable[[str], None], index: int, total: int, name: str, seconds: float, skipped: bool
) -> None:
    status = "SKIP" if skipped else "xong"
    log(f"[dub] ({index}/{total}) {name} {status} ({seconds:.1f}s)")


def run_dub(
    url: str,
    config: AppConfig,
    options: DubOptions,
    *,
    log: Callable[[str], None] = print,
) -> DubResult:
    """Chạy toàn bộ pipeline cho một video, trả về tóm tắt kết quả.

    Mỗi stage bọc lỗi riêng của nó thành ``DubError(stage, message)`` để
    người gọi (CLI) biết chính xác đứt ở đâu và lệnh nào chạy lại.
    """
    total = len(STAGES)

    # --- 0. Validate trước khi chạm mạng: đừng để tải + whisper 10 phút rồi
    # mới báo config sai (vd --original-volume ngoài khoảng, thiếu model). ---
    try:
        validate_mixing(
            options.original_volume, config.mixing.speech_volume, config.mixing.max_shift_seconds
        )
    except ConfigError as exc:
        raise DubError("render", str(exc)) from exc
    try:
        validate_timing_ratios(config.timing.normal_max_ratio, config.timing.max_tempo)
    except ConfigError as exc:
        raise DubError("normalize", str(exc)) from exc
    try:
        validate_rate_or_volume("tts", "rate", config.tts.rate)
        validate_rate_or_volume("tts", "volume", config.tts.volume)
    except ConfigError as exc:
        raise DubError("tts", str(exc)) from exc
    if config.translation.model is None:
        raise DubError(
            "translate",
            "Chưa cấu hình `translation.model` trong config.yaml — đặt tên model dịch "
            "(vd gemma3:12b) rồi chạy lại `dub` (không có flag --model riêng cho dub).",
        )

    stage_seconds: dict[str, float] = {}
    skipped_stages: list[str] = []

    # --- 1. download ---
    _log_start(log, 1, total, "download")
    started = time.monotonic()
    # Mốc thời gian *trước* khi gọi download_video: episode_dir chỉ được biết
    # sau lệnh gọi (yt-dlp trả metadata), nên không thể exists() trước như các
    # stage sau — suy ra "đã có từ trước" bằng cách so mtime của source.mp4
    # với mốc này (file cũ hơn mốc = không bị tải lại).
    download_started_at = time.time()
    try:
        episode = download_video(url, options.workspace, force=options.force)
    except VideoDownloadError as exc:
        raise DubError("download", str(exc)) from exc
    download_skipped = (
        not options.force
        and episode.source_path.exists()
        and episode.source_path.stat().st_mtime < download_started_at
    )
    stage_seconds["download"] = time.monotonic() - started
    if download_skipped:
        skipped_stages.append("download")
    _log_done(log, 1, total, "download", stage_seconds["download"], download_skipped)

    episode_dir = episode.episode_dir
    audio_path = episode_dir / AUDIO_FILENAME
    transcript_path = episode_dir / TRANSCRIPT_FILENAME
    translated_path = episode_dir / TRANSLATED_FILENAME
    tts_dir = episode_dir / TTS_DIRNAME

    # --- 2. transcribe ---
    _log_start(log, 2, total, "transcribe")
    started = time.monotonic()
    transcript_existed = transcript_path.exists()
    try:
        extract_audio(episode.source_path, audio_path, force=options.force)
        transcribe_result = transcribe_audio(
            audio_path,
            transcript_path,
            model_size=config.whisper.model,
            device=config.whisper.device,
            compute_type=config.whisper.compute_type,
            language=options.source_lang,
            force=options.force,
        )
    except (AudioExtractionError, TranscriptionError) as exc:
        raise DubError("transcribe", str(exc)) from exc

    if options.source_lang is not None and transcribe_result.language != options.source_lang:
        # Transcript cache cũ nhận sai ngôn ngữ (hoặc lệnh transcribe riêng lẻ
        # đã chạy trước với ngôn ngữ khác) — KHÔNG tự xoá/ghi đè: làm vậy kéo
        # theo dịch lại cả tập mà người dùng chưa đồng ý (xem CLAUDE.md, bẫy
        # auto-detect zh->en).
        raise DubError(
            "transcribe",
            f"transcript.json đang là ngôn ngữ '{transcribe_result.language}', khác "
            f"--source-lang '{options.source_lang}' vừa truyền. Chạy: "
            f'python -m app transcribe "{episode_dir}" --source-lang {options.source_lang} --force'
            " rồi chạy lại dub.",
        )
    if options.source_lang is None and transcribe_result.language != "en":
        log(
            f"[dub] LƯU Ý: Whisper tự nhận ngôn ngữ '{transcribe_result.language}' — "
            "nếu sai, chạy lại với --source-lang."
        )

    stage_seconds["transcribe"] = time.monotonic() - started
    transcribe_skipped = not options.force and transcript_existed
    if transcribe_skipped:
        skipped_stages.append("transcribe")
    _log_done(log, 2, total, "transcribe", stage_seconds["transcribe"], transcribe_skipped)

    # --- 3. glossary (không phải stage riêng — không tự tạo nháp, xem CP6.5 A2) ---
    try:
        glossary, glossary_paths = load_effective_glossary(episode_dir, options.shared_glossary)
    except TranslationError as exc:  # GlossaryError là TranslationError
        raise DubError("translate", str(exc)) from exc

    if not (episode_dir / GLOSSARY_FILENAME).exists():
        log(
            f'[dub] Chưa có glossary.yaml — nên chạy: python -m app glossary "{episode_dir}", '
            "sửa file, rồi chạy lại dub."
        )
    if glossary is not None:
        log("[dub] glossary : " + ", ".join(str(p) for p in glossary_paths))

    # --- 4. translate (tự thử lại failed_ids tối đa repair_rounds lần) ---
    _log_start(log, 3, total, "translate")
    started = time.monotonic()
    try:
        translator = create_translator(config.translation)
    except TranslationError as exc:
        raise DubError("translate", str(exc)) from exc

    def _translate(force: bool):
        try:
            return translate_transcript(
                transcript_path,
                translated_path,
                translator,
                target_language=config.target_language,
                batch_size=config.translation.batch_size,
                context_size=config.translation.context_size,
                max_attempts=config.translation.max_attempts,
                force=force,
                glossary=glossary,
                log=log,
            )
        except TranslationError as exc:
            raise DubError("translate", str(exc)) from exc

    translate_result = _translate(options.force)
    translate_skipped_initial = translate_result.skipped
    translate_rounds = 0
    while translate_result.failed_ids and translate_rounds < config.pipeline.repair_rounds:
        translate_rounds += 1
        log(
            f"[dub] translate: {len(translate_result.failed_ids)} segment lỗi — "
            f"thử lại vòng {translate_rounds}/{config.pipeline.repair_rounds}"
        )
        # Không force: chỉ thử lại đúng các segment lỗi (CP3 A1), giữ nguyên
        # các câu đã dịch tốt.
        translate_result = _translate(False)
    translate_failed_ids = list(translate_result.failed_ids)
    if translate_failed_ids:
        ids = ", ".join(str(i) for i in translate_failed_ids)
        log(
            f"[dub] CẢNH BÁO: {len(translate_failed_ids)} segment dịch lỗi sau "
            f"{translate_rounds} vòng thử lại (id {ids}) — các câu này sẽ im lặng trong output."
        )

    stage_seconds["translate"] = time.monotonic() - started
    translate_skipped = translate_skipped_initial and translate_rounds == 0
    if translate_skipped:
        skipped_stages.append("translate")
    _log_done(log, 3, total, "translate", stage_seconds["translate"], translate_skipped)

    # --- 5+6. tts + normalize (mỗi hàm tự log (i/6) .../xong quanh MỖI lần gọi
    # — kể cả các vòng sửa ở bước 7 — để log đọc tuần tự thay vì xen kẽ hai
    # stage nửa chừng; stage_seconds/skipped vẫn cộng dồn đúng qua biến ngoài. ---
    try:
        tts_engine = create_tts_engine(config.tts)
    except TTSError as exc:
        raise DubError("tts", str(exc)) from exc

    tts_seconds = 0.0
    tts_did_work = False

    def _run_tts(force: bool):
        nonlocal tts_seconds, tts_did_work
        _log_start(log, 4, total, "tts")
        t0 = time.monotonic()
        try:
            result = synthesize_translation(
                translated_path,
                tts_dir,
                tts_engine,
                max_attempts=config.tts.max_attempts,
                concurrency=config.tts.concurrency,
                force=force,
                log=log,
            )
        except TTSError as exc:
            raise DubError("tts", str(exc)) from exc
        elapsed = time.monotonic() - t0
        tts_seconds += elapsed
        if not result.skipped:
            tts_did_work = True
        _log_done(log, 4, total, "tts", elapsed, result.skipped)
        return result

    normalize_seconds = 0.0
    normalize_did_work = False

    def _run_normalize(force: bool):
        nonlocal normalize_seconds, normalize_did_work
        _log_start(log, 5, total, "normalize")
        t0 = time.monotonic()
        try:
            result = normalize_timing(
                episode_dir,
                normal_max_ratio=config.timing.normal_max_ratio,
                max_tempo=config.timing.max_tempo,
                force=force,
                log=log,
            )
        except TimingError as exc:
            raise DubError("normalize", str(exc)) from exc
        elapsed = time.monotonic() - t0
        normalize_seconds += elapsed
        if not result.skipped:
            normalize_did_work = True
        _log_done(log, 5, total, "normalize", elapsed, result.skipped)
        return result

    tts_result = _run_tts(options.force)
    timing_result = _run_normalize(options.force)
    missing_ids = list(timing_result.missing_ids)
    too_long_ids = list(timing_result.too_long_ids)

    # --- 7. vòng sửa thiếu audio (CP5 A3 / CP6 A2): render KHÔNG tự chạy lại
    # stage trước, dub phải điều phối tts -> normalize tới khi hết missing
    # hoặc hết số vòng. Không truyền force vào đây dù options.force: nếu
    # không sẽ tổng hợp lại toàn bộ mỗi vòng. ---
    missing_rounds = 0
    while missing_ids and missing_rounds < config.pipeline.repair_rounds:
        missing_rounds += 1
        ids = ", ".join(str(i) for i in missing_ids)
        log(
            f"[dub] normalize: {len(missing_ids)} segment thiếu audio (id {ids}) — "
            f"thử lại vòng {missing_rounds}/{config.pipeline.repair_rounds}"
        )
        tts_result = _run_tts(False)
        timing_result = _run_normalize(False)
        missing_ids = list(timing_result.missing_ids)
        too_long_ids = list(timing_result.too_long_ids)

    stage_seconds["tts"] = tts_seconds
    tts_skipped = not tts_did_work
    if tts_skipped:
        skipped_stages.append("tts")

    stage_seconds["normalize"] = normalize_seconds
    normalize_skipped = not normalize_did_work
    if normalize_skipped:
        skipped_stages.append("normalize")

    repair_rounds_used = translate_rounds + missing_rounds

    # --- 8. render ---
    if missing_ids and not options.allow_missing:
        ids = ", ".join(str(i) for i in missing_ids)
        raise DubError(
            "render",
            f"{len(missing_ids)} segment thiếu audio (id {ids}) sau {missing_rounds} vòng thử "
            "lại — chạy lại dub, hoặc thêm --allow-missing để chèn im lặng",
        )

    _log_start(log, 6, total, "render")
    started = time.monotonic()
    try:
        render_result = render_episode(
            episode_dir,
            original_volume=options.original_volume,
            speech_volume=config.mixing.speech_volume,
            max_shift=config.mixing.max_shift_seconds,
            allow_missing=options.allow_missing,
            force=options.force,
            log=log,
        )
    except RenderError as exc:
        raise DubError("render", str(exc)) from exc
    stage_seconds["render"] = time.monotonic() - started
    render_skipped = render_result.voice_track_skipped and render_result.output_skipped
    if render_skipped:
        skipped_stages.append("render")
    _log_done(log, 6, total, "render", stage_seconds["render"], render_skipped)

    return DubResult(
        episode_dir=episode_dir,
        output_path=render_result.output_path,
        source_language=transcribe_result.language,
        segments=len(transcribe_result.segments),
        translate_failed_ids=translate_failed_ids,
        missing_ids=list(render_result.missing_ids),
        too_long_ids=too_long_ids,
        repair_rounds_used=repair_rounds_used,
        glossary_paths=list(glossary_paths),
        stage_seconds=stage_seconds,
        skipped_stages=skipped_stages,
    )
