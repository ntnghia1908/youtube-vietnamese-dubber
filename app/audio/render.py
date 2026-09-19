"""Stage: dựng voice track + render video cuối — Checkpoint 6.

``normalized.json`` (CP5) + ``source.mp4`` (CP1) -> ``voice_track.wav`` ->
``output_vi.mp4``: đặt audio từng segment vào đúng timestamp, mix với audio
gốc (hạ volume), giữ nguyên video stream (``-c:v copy``).

Quyết định đã chốt (xem ``docs/decisions/checkpoint-6.md``):
- Voice track dựng bằng stdlib (``wave`` + ``array``): mỗi segment giải mã
  qua ``ffmpeg ... pipe:1`` ra PCM s16le mono. Không dùng một lệnh
  ``adelay+amix`` 58–400 input (giới hạn độ dài dòng lệnh Windows, khó
  debug), không dùng ``audioop`` (đã bị gỡ từ Python 3.13) và không thêm numpy.
- Câu ``too_long`` còn tràn slot thì DỜI câu sau, có chặn trần
  (``max_shift``), không đè ngay: hai giọng đè nhau khó nghe hơn nhiều so
  với lệch vài trăm ms, và drift tự hồi phục vì câu ``normal`` ngắn hơn
  slot của nó. Chạm trần thì mới đè.
- ``missing`` mặc định báo lỗi (đây là sản phẩm cuối, không được lọt một
  bản thuyết minh thiếu câu ra ngoài); ``allow_missing`` mới chèn im lặng.
- Mix bằng một lần ffmpeg, không ghi ``mixed_audio.wav`` trung gian.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import wave
from array import array
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.synchronization.timing import NORMALIZED_FILENAME, TimingError, probe_duration
from app.youtube.download import SOURCE_FILENAME

VOICE_TRACK_FILENAME = "voice_track.wav"
OUTPUT_FILENAME = "output_vi.mp4"
# Sidecar: fingerprint + report, để resume và để debug vị trí từng câu.
RENDER_FILENAME = "render.json"
# Đúng sample rate gốc của edge-tts (24 kHz) nên không phải resample.
VOICE_SAMPLE_RATE_HZ = 24000
_AUDIO_BITRATE = "192k"

# Ngưỡng coi là "có dời/đè" khi báo cáo — bỏ qua sai số dấu phẩy động.
_EPSILON_SECONDS = 0.001
# Audio cuối vượt hết video quá ngưỡng này mới cảnh báo bị cắt.
_TRUNCATE_WARN_SECONDS = 0.05


class RenderError(RuntimeError):
    """Lỗi rõ ràng khi thiếu input, ffmpeg không có, hoặc mix thất bại."""


@dataclass(frozen=True)
class Placement:
    id: int
    audio: str  # đường dẫn tương đối episode dir (dấu /), lấy từ normalized["audio"]
    start: float  # start gốc của segment
    placed_at: float  # thời điểm thực sự đặt vào track
    audio_duration: float
    shift: float  # placed_at - start, luôn >= 0
    overlap: float  # giây đè lên audio câu trước (> 0 chỉ khi chạm max_shift)


@dataclass(frozen=True)
class RenderResult:
    voice_track_path: Path
    output_path: Path
    render_path: Path
    placed_ids: list[int]
    silent_ids: list[int]
    missing_ids: list[int]  # khác rỗng chỉ khi allow_missing=True
    shifted_ids: list[int]  # shift > 0.001
    overlap_ids: list[int]  # overlap > 0.001
    max_shift_seen: float
    duration: float  # giây, độ dài source.mp4
    voice_track_skipped: bool
    output_skipped: bool


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    # Copy pattern từ app/synchronization/timing.py:_write_json_atomic (hàm
    # private, không import chéo) — cùng lý do: bị kill giữa lúc ghi thì file
    # cụt không được coi là "đã xong" và skip mãi.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _round3(value: float) -> float:
    return round(value, 3)


def plan_placements(segments: list[dict[str, Any]], *, max_shift: float) -> list[Placement]:
    """Tính thời điểm đặt từng segment vào track. Hàm thuần, không I/O.

    Chỉ lấy segment có ``audio != None``, sắp theo ``(start, id)``. ``cursor``
    là thời điểm audio đã đặt kết thúc; câu tiếp theo bị dời tới ``cursor``
    nếu cần, nhưng không quá ``start + max_shift`` (chạm trần thì đè lên câu
    trước, ``overlap > 0``). Dùng ``audio_duration`` (ffprobe thật, từ
    ``normalized.json``), KHÔNG dùng ``tts_duration``/``tempo``/``overflow``:
    atempo không chính xác tuyệt đối nên suy từ tempo sẽ lệch dần.
    """
    rows = [seg for seg in segments if seg.get("audio") is not None]
    rows.sort(key=lambda seg: (seg["start"], seg["id"]))

    placements: list[Placement] = []
    cursor = 0.0
    for seg in rows:
        start = float(seg["start"])
        duration = float(seg["audio_duration"])
        placed_at = min(max(start, cursor), start + max_shift)
        overlap = max(0.0, cursor - placed_at)
        cursor = max(cursor, placed_at + duration)
        placements.append(
            Placement(
                id=int(seg["id"]),
                audio=str(seg["audio"]),
                start=start,
                placed_at=placed_at,
                audio_duration=duration,
                shift=placed_at - start,
                overlap=overlap,
            )
        )
    return placements


def decode_pcm(path: Path, sample_rate: int) -> bytes:
    """Giải mã ``path`` ra PCM s16le mono ``sample_rate`` Hz (bytes thô, không header).

    Đọc stdout dạng bytes (KHÔNG ``text=True``: decode UTF-8 sẽ phá PCM).
    ``RenderError`` nếu không có ffmpeg, ffmpeg lỗi, hoặc không ra byte nào
    (file rỗng/hỏng) — một câu im lặng lặng lẽ tệ hơn một lỗi rõ ràng.
    """
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin is None:
        raise RenderError(
            "Không tìm thấy `ffmpeg` trên PATH. Cài ffmpeg rồi thử lại "
            "(xem README.md, mục Yêu cầu)."
        )
    cmd = [
        ffmpeg_bin,
        "-nostdin",
        "-v", "error",
        "-i", str(path),
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ac", "1",
        "-ar", str(sample_rate),
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()[-500:]
        raise RenderError(f"ffmpeg lỗi khi giải mã {path}: {stderr}")
    data = result.stdout
    if not data:
        raise RenderError(f"ffmpeg giải mã {path} nhưng không ra sample nào (file rỗng/hỏng?).")
    if len(data) % 2:
        # s16 = 2 byte/sample; byte lẻ cuối là rác, giữ lại sẽ lệch cả track.
        data = data[:-1]
    return data


def _bytes_to_samples(data: bytes | bytearray) -> array:
    samples = array("h")
    samples.frombytes(data)
    if sys.byteorder == "big":
        # PCM s16le luôn little-endian; array('h') dùng thứ tự native.
        samples.byteswap()
    return samples


def _samples_to_bytes(samples: array) -> bytes:
    if sys.byteorder == "big":
        samples = array("h", samples)
        samples.byteswap()
    return samples.tobytes()


def build_voice_track(
    episode_dir: Path,
    placements: list[Placement],
    dst: Path,
    *,
    total_seconds: float,
    sample_rate: int,
    log: Callable[[str], None] = print,
) -> None:
    """Ghi ``dst`` (WAV mono s16) dài đúng ``ceil(total_seconds * sample_rate)`` frame.

    Dựng cả track trong RAM (``bytearray`` toàn số 0 = im lặng, ~2.9 MB/phút)
    rồi ghi một lần: ``decode_pcm`` lỗi giữa chừng thì chưa có file nào trên
    đĩa, không cần dọn. Vòng lặp từng sample CHỈ chạy trên vùng đè lên audio
    đã đặt (ngắn, và ``max_shift`` mặc định gần như không bao giờ tạo ra
    nó); phần còn lại là slice-assign — lặp từng sample cả track sẽ mất hàng
    chục giây cho video vài phút.
    """
    total_samples = math.ceil(total_seconds * sample_rate)
    track = bytearray(total_samples * 2)
    written_end = 0  # sample cuối (exclusive) đã có audio, để biết chỗ nào là vùng đè

    for index, placement in enumerate(placements, start=1):
        pcm = decode_pcm(episode_dir / placement.audio, sample_rate)
        off = max(0, round(placement.placed_at * sample_rate))
        # Dùng số sample THẬT của pcm, không dùng audio_duration: ffprobe đo
        # theo container, có thể lệch vài sample so với số frame giải mã ra.
        n = min(len(pcm) // 2, total_samples - off)  # vượt track thì cắt, không raise
        if n <= 0:
            continue
        ov = max(0, min(off + n, written_end) - off)  # số sample đè lên vùng đã có audio
        if ov:
            existing = _bytes_to_samples(track[off * 2 : (off + ov) * 2])
            incoming = _bytes_to_samples(pcm[: ov * 2])
            for i in range(ov):
                # Cộng rồi kẹp int16: tràn thì wrap-around thành tiếng rè, kẹp
                # thì chỉ méo nhẹ.
                existing[i] = max(-32768, min(32767, existing[i] + incoming[i]))
            track[off * 2 : (off + ov) * 2] = _samples_to_bytes(existing)
        if n > ov:
            track[(off + ov) * 2 : (off + n) * 2] = pcm[ov * 2 : n * 2]
        written_end = max(written_end, off + n)
        if index % 10 == 0 or index == len(placements):
            log(f"[render] đã ghép {index}/{len(placements)} segment")

    # Ghi ra .tmp.wav (phải có đuôi .wav) rồi os.replace — atomic.
    tmp_path = dst.with_name(dst.stem + ".tmp.wav")
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with wave.open(str(tmp_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(track)
        os.replace(tmp_path, dst)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def mix_video(
    source: Path,
    voice_track: Path,
    dst: Path,
    *,
    original_volume: float,
    speech_volume: float,
) -> None:
    """Mux ``source`` (video + audio gốc) với ``voice_track`` thành ``dst`` bằng một lệnh ffmpeg.

    - ``aformat`` ép audio gốc về stereo để ``amix`` không phải đoán layout.
    - ``pan=stereo|c0=c0|c1=c0`` nhân đôi voice mono ra hai kênh mà KHÔNG bị
      giảm 3 dB như upmix mặc định.
    - ``normalize=0``: ``amix`` mặc định tự chia mức mỗi input cho số input,
      sẽ làm nhỏ giọng thuyết minh đi một nửa ngoài ý muốn.
    - ``alimiter`` chống clip khi cộng hai track.
    - ``duration=first``: kết thúc theo audio gốc (voice track dài hơn video thì bị cắt).
    - ``-c:v copy``: không encode lại video (nhanh, không mất chất lượng).

    Ghi ra ``dst`` kèm hậu tố ``.tmp.mp4`` (đuôi ``.mp4`` để ffmpeg chọn đúng
    muxer) rồi ``os.replace``; lỗi thì xoá tmp.
    """
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin is None:
        raise RenderError(
            "Không tìm thấy `ffmpeg` trên PATH. Cài ffmpeg rồi thử lại "
            "(xem README.md, mục Yêu cầu)."
        )
    tmp_path = dst.with_name(dst.stem + ".tmp.mp4")
    dst.parent.mkdir(parents=True, exist_ok=True)
    filter_complex = (
        f"[0:a]aformat=channel_layouts=stereo,volume={original_volume:.4f}[bg];"
        f"[1:a]pan=stereo|c0=c0|c1=c0,volume={speech_volume:.4f}[fg];"
        "[bg][fg]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[aout]"
    )
    cmd = [
        ffmpeg_bin,
        "-y",
        "-nostdin",
        "-v", "error",
        "-i", str(source),
        "-i", str(voice_track),
        "-filter_complex", filter_complex,
        "-map", "0:v:0",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", _AUDIO_BITRATE,
        "-movflags", "+faststart",
        str(tmp_path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        tmp_path.unlink(missing_ok=True)
        raise RenderError(f"ffmpeg mix thất bại cho {source}: {result.stderr.strip()[-2000:]}")
    if not tmp_path.exists():
        raise RenderError(f"ffmpeg chạy xong nhưng không thấy file output tại: {tmp_path}")
    os.replace(tmp_path, dst)


def _sha256_of(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _voice_fingerprint(
    rows: list[list[Any]], *, sample_rate: int, max_shift: float, source_duration: float
) -> str:
    return _sha256_of(
        {
            "v": 1,
            "sample_rate": sample_rate,
            "max_shift": max_shift,
            "source_duration": round(source_duration, 3),
            "rows": rows,
        }
    )


def _output_fingerprint(
    voice_fingerprint: str,
    *,
    original_volume: float,
    speech_volume: float,
    source_stat: os.stat_result,
) -> str:
    return _sha256_of(
        {
            "v": 1,
            "voice": voice_fingerprint,
            "original_volume": original_volume,
            "speech_volume": speech_volume,
            "source_size": source_stat.st_size,
            "source_mtime_ns": source_stat.st_mtime_ns,
        }
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _load_normalized_segments(episode_dir: Path) -> list[dict[str, Any]]:
    path = episode_dir / NORMALIZED_FILENAME
    if not path.exists():
        raise RenderError(
            f"Không tìm thấy {path}. Chạy `normalize` trước "
            f"(python -m app normalize \"{episode_dir}\")."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RenderError(
            f"{path} hỏng ({exc}). Chạy lại `normalize --force` để tạo lại."
        ) from exc
    segments = data.get("segments") if isinstance(data, dict) else None
    if not isinstance(segments, list):
        raise RenderError(f"{path} thiếu danh sách `segments`. Chạy lại `normalize --force`.")
    for seg in segments:
        if not isinstance(seg, dict) or not isinstance(seg.get("id"), int) or not _is_number(
            seg.get("start")
        ):
            raise RenderError(
                f"{path} có segment thiếu `id`/`start` hợp lệ: {seg!r}. "
                "Chạy lại `normalize --force`."
            )
    return segments


def _load_render_json(path: Path, log: Callable[[str], None]) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log(f"[render] {path} hỏng ({exc}) — dựng lại từ đầu.")
        return {}
    return data if isinstance(data, dict) else {}


def _section(doc: dict[str, Any], key: str) -> dict[str, Any]:
    value = doc.get(key)
    return value if isinstance(value, dict) else {}


def render_episode(
    episode_dir: Path,
    *,
    original_volume: float = 0.30,
    speech_volume: float = 1.0,
    max_shift: float = 1.0,
    allow_missing: bool = False,
    force: bool = False,
    log: Callable[[str], None] = print,
) -> RenderResult:
    """Dựng ``voice_track.wav`` + ``output_vi.mp4`` cho một episode (resume được)."""
    episode_dir = Path(episode_dir)
    source_path = episode_dir / SOURCE_FILENAME
    voice_track_path = episode_dir / VOICE_TRACK_FILENAME
    output_path = episode_dir / OUTPUT_FILENAME
    render_path = episode_dir / RENDER_FILENAME
    # int từ YAML (`max_shift_seconds: 1`) và float từ CLI phải cho cùng
    # fingerprint, nếu không đổi kiểu số sẽ dựng lại track oan.
    original_volume = float(original_volume)
    speech_volume = float(speech_volume)
    max_shift = float(max_shift)
    # Đọc lúc gọi (không phải lúc import) để test patch được hằng số này.
    sample_rate = VOICE_SAMPLE_RATE_HZ

    # --- Kiểm tra đầu vào (không tự chạy lại stage trước) ---
    segments = _load_normalized_segments(episode_dir)
    if not source_path.exists():
        raise RenderError(
            f"Không tìm thấy {source_path}. Chạy `download` trước "
            "(hoặc kiểm tra lại thư mục episode)."
        )

    with_audio = [seg for seg in segments if seg.get("audio") is not None]
    # Đây là normalized.json cũ/hỏng (file bị xoá sau `normalize`), KHÁC câu
    # "missing" hợp lệ do CP5 đánh dấu -> lỗi kể cả khi allow_missing=True.
    broken_ids = [
        seg["id"]
        for seg in with_audio
        if not _is_number(seg.get("audio_duration"))
        or not (episode_dir / str(seg["audio"])).is_file()
    ]
    if broken_ids:
        ids = ", ".join(str(i) for i in broken_ids)
        raise RenderError(
            f"{len(broken_ids)} segment có `audio` nhưng file không tồn tại hoặc thiếu "
            f"`audio_duration` (id {ids}): normalized.json đã cũ, chạy lại `normalize`."
        )

    # `silent` (CP4 dịch ra rỗng) không phải lỗi; mọi segment không có audio
    # còn lại (status "missing" hoặc bất thường) coi là thiếu audio thật.
    silent_ids = [
        seg["id"] for seg in segments if seg.get("audio") is None and seg.get("status") == "silent"
    ]
    missing_ids = [
        seg["id"] for seg in segments if seg.get("audio") is None and seg.get("status") != "silent"
    ]
    if missing_ids and not allow_missing:
        ids = ", ".join(str(i) for i in missing_ids)
        raise RenderError(
            f"{len(missing_ids)} segment thiếu audio (id {ids}): chạy lại `tts` rồi "
            "`normalize`, hoặc dùng `--allow-missing` để chèn im lặng."
        )

    try:
        source_duration = probe_duration(source_path)
    except TimingError as exc:
        raise RenderError(str(exc)) from exc

    placements = plan_placements(with_audio, max_shift=max_shift)
    last_end = max((p.placed_at + p.audio_duration for p in placements), default=0.0)
    total_seconds = max(source_duration, last_end)
    if last_end > source_duration + _TRUNCATE_WARN_SECONDS:
        log(
            f"[render] CẢNH BÁO: audio kết thúc ở {last_end:.2f}s, muộn hơn video "
            f"({source_duration:.2f}s) — phần thừa bị cắt ở {OUTPUT_FILENAME}."
        )

    # Dọn file tạm sót lại do lần chạy trước bị kill giữa chừng.
    voice_track_path.with_name(voice_track_path.stem + ".tmp.wav").unlink(missing_ok=True)
    output_path.with_name(output_path.stem + ".tmp.mp4").unlink(missing_ok=True)

    rows = [
        [seg["id"], seg["start"], seg["audio"], seg["audio_duration"],
         seg.get("tts_cache_key"), seg.get("tempo")]
        for seg in with_audio
    ]
    voice_fp = _voice_fingerprint(
        rows, sample_rate=sample_rate, max_shift=max_shift, source_duration=source_duration
    )
    output_fp = _output_fingerprint(
        voice_fp,
        original_volume=original_volume,
        speech_volume=speech_volume,
        source_stat=source_path.stat(),
    )

    old_doc = _load_render_json(render_path, log)
    old_voice = _section(old_doc, "voice_track")
    old_output = _section(old_doc, "output")

    # --- voice_track.wav ---
    voice_skipped = (
        not force and voice_track_path.exists() and old_voice.get("fingerprint") == voice_fp
    )
    if voice_skipped:
        log(f"[render] SKIP: {VOICE_TRACK_FILENAME} đã khớp (dùng --force để dựng lại).")
        doc: dict[str, Any] = {"voice_track": old_voice}
        if old_output:
            doc["output"] = old_output
    else:
        log(f"[render] dựng {VOICE_TRACK_FILENAME} ({len(placements)} segment)...")
        build_voice_track(
            episode_dir,
            placements,
            voice_track_path,
            total_seconds=total_seconds,
            sample_rate=sample_rate,
            log=log,
        )
        voice_section: dict[str, Any] = {
            "fingerprint": voice_fp,
            "sample_rate": sample_rate,
            "duration": _round3(total_seconds),
            "params": {"max_shift_seconds": max_shift},
            "summary": {
                "placed": len(placements),
                "silent": len(silent_ids),
                "missing": len(missing_ids),
                "shifted": sum(1 for p in placements if p.shift > _EPSILON_SECONDS),
                "overlap": sum(1 for p in placements if p.overlap > _EPSILON_SECONDS),
                "max_shift_seen": _round3(max((p.shift for p in placements), default=0.0)),
            },
            "placements": [
                {
                    "id": p.id,
                    "start": _round3(p.start),
                    "placed_at": _round3(p.placed_at),
                    "audio_duration": _round3(p.audio_duration),
                    "shift": _round3(p.shift),
                    "overlap": _round3(p.overlap),
                }
                for p in placements
            ],
        }
        # Bỏ section `output` cũ: nội dung voice_track đã đổi, output cũ không
        # còn khớp. Mux lỗi giữa chừng thì lần sau vẫn SKIP voice, chỉ mux lại.
        doc = {"voice_track": voice_section}
        _write_json_atomic(render_path, doc)

    # --- output_vi.mp4 ---
    # So với `output` của render.json CŨ (đọc đầu hàm): voice track dựng lại
    # với cùng fingerprint (vd xoá tay voice_track.wav) cho ra nội dung y hệt,
    # nên output cũ vẫn dùng được.
    output_skipped = (
        not force and output_path.exists() and old_output.get("fingerprint") == output_fp
    )
    if output_skipped:
        log(f"[render] SKIP: {OUTPUT_FILENAME} đã khớp (dùng --force để mux lại).")
        if "output" not in doc:
            doc["output"] = old_output
            _write_json_atomic(render_path, doc)
    else:
        log(f"[render] mux {OUTPUT_FILENAME} (original {original_volume:g}, speech {speech_volume:g})...")
        mix_video(
            source_path,
            voice_track_path,
            output_path,
            original_volume=original_volume,
            speech_volume=speech_volume,
        )
        doc["output"] = {
            "fingerprint": output_fp,
            "params": {"original_volume": original_volume, "speech_volume": speech_volume},
            "duration": _round3(source_duration),
        }
        _write_json_atomic(render_path, doc)

    return RenderResult(
        voice_track_path=voice_track_path,
        output_path=output_path,
        render_path=render_path,
        placed_ids=[p.id for p in placements],
        silent_ids=silent_ids,
        missing_ids=missing_ids,
        shifted_ids=[p.id for p in placements if p.shift > _EPSILON_SECONDS],
        overlap_ids=[p.id for p in placements if p.overlap > _EPSILON_SECONDS],
        max_shift_seen=_round3(max((p.shift for p in placements), default=0.0)),
        duration=source_duration,
        voice_track_skipped=voice_skipped,
        output_skipped=output_skipped,
    )
