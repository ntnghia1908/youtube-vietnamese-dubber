# Task: CP9-B — Giữ nhạc gốc to ở đoạn không lồng tiếng

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: claude-code — subagent implementer (adapter duy nhất trong project-profile §7)
- Authorization mode: boundary
- Authorization source: APPROVE TASK 2026-10-17 (HUMAN LEAD: "APPROVE TASK CP9-B WEB-POLISH") — CP9 nằm ngoài boundary ADR-001
- Parallel group: P1 (cùng CP9-A)
- Owned paths: `app/audio/render.py`, `app/config.py`, `app/pipeline/dub.py`, `app/cli.py` (chỉ chỗ truyền tham số vào render), `config.example.yaml`, `tests/test_render.py`, `tests/test_config.py`, `docs/decisions/checkpoint-9-B.md` (file tạm khi chạy song song; ORCHESTRATOR gộp vào checkpoint-9.md lúc merge)
- Dependencies: CP9-A (chạy sau, cùng file `docs/decisions/checkpoint-9.md`; không phụ thuộc code)
- Base commit / branch: a878855 / worktree (song song với CP9-A)
- Human Lead approval: accepted 2026-10-17
- Implementation authorized: YES

Lifecycle: `boundary` mode = `DRAFT → IN_PROGRESS → READY`.

## Goal

Ở các đoạn không lồng tiếng (segment `status: "silent"` trong `normalized.json`, gồm câu `skip` của glossary như bài hát mở đầu), audio gốc phát ở volume **to** (`mixing.skip_original_volume`, mặc định 1.0) thay vì bị hạ xuống `original_volume` 0.30. Chuyển mức có fade ngắn để không giật.

Hạng mục 5 của CP9 (HUMAN LEAD 2026-10-17: "Giữ nhạc gốc to ở các đoạn skip … hãy làm luôn"). Thứ tự: CP9-A → **CP9-B** → các hạng mục còn lại.

## Scope

- In scope: volume audio gốc thay đổi theo thời gian khi mix (`mix_video`); config mới; fingerprint output đổi theo; render.json ghi các khoảng đã giữ to.
- Out of scope: tách nhạc/giọng (source separation); tự phát hiện nhạc không cần glossary; đổi cách dựng `voice_track.wav`; khoảng lặng giữa hai câu thường (vẫn hạ như cũ).

## Authority / key decisions

- Plan §Checkpoint 9; `docs/decisions/checkpoint-6.md` (mix một lệnh ffmpeg, `amix normalize=0`, `alimiter`).
- `normalized.json` (CP5): segment rỗng có `status: "silent"`, `audio: null`, `start`/`end` là khoảng gốc của Whisper (xem Episode 02 Ocean Girl: id 1–6, 0–63s).

## Implementation approach

### File cần sửa/tạo

| Path | Việc cần làm |
|---|---|
| `app/audio/render.py` | Hàm thuần `skip_intervals(...)`, `original_volume_expr(...)`; `mix_video` nhận thêm tham số; `render_episode` tính khoảng + đưa vào fingerprint + render.json |
| `app/config.py` | `MixingConfig.skip_original_volume: float = 1.0`, `skip_fade_seconds: float = 0.5`; kiểu + validate (cùng chỗ `validate_mixing`) |
| `app/pipeline/dub.py`, `app/cli.py` | Truyền hai giá trị config vào `render_episode` (lệnh `render` và `dub`/`playlist`) — không thêm flag CLI |
| `config.example.yaml` | Hai key mới dưới `mixing:` kèm comment |
| `tests/test_render.py`, `tests/test_config.py` | Case mới |

### Interface

```python
def skip_intervals(
    segments: list[dict[str, Any]], *, min_gap: float = 0.5, duration: float
) -> list[tuple[float, float]]:
    """Khoảng [start, end] (giây) của segment status == "silent", sắp theo start,
    gộp khoảng liền/cách nhau < min_gap; cắt vào [0, duration]. Hàm thuần."""

def original_volume_expr(
    intervals: list[tuple[float, float]], *, base: float, skip: float, fade: float
) -> str:
    """Biểu thức cho filter ffmpeg `volume=...:eval=frame`.
    w(t) = max_i clip(min((t-(a_i-fade))/fade, ((b_i+fade)-t)/fade), 0, 1)  (fade=0 -> bước nhảy: between(t,a,b))
    volume = base + (skip-base)*w(t). Không có khoảng -> trả f"{base:.4f}" (y hệt hiện tại).
    Số làm tròn 3 chữ số; dấu phẩy trong biểu thức phải escape `\\,` cho filtergraph."""

def mix_video(source, voice_track, dst, *, original_volume: float, speech_volume: float,
              skip_intervals: list[tuple[float, float]] = (), skip_original_volume: float = 1.0,
              skip_fade: float = 0.5) -> None
    # [0:a]aformat=...,volume='<expr>':eval=frame[bg]  — chỉ thêm :eval=frame khi có khoảng
```

- Fade nằm **ngoài** khoảng (bắt đầu tăng từ `a - fade`, về mức thấp ở `b + fade`) để câu lồng tiếng sát trước/sau không bị nhạc to đè: nếu khoảng fade chạm câu có audio (placement từ `plan_placements`), thu hẹp fade phía đó cho không chồng lên `placed_at`/`placed_at+audio_duration` của câu kề. Implementer chọn cách đơn giản nhất đúng điều này, ghi vào decisions.
- Nếu số khoảng lớn làm biểu thức dài (> ~200 khoảng), escalate — không tự đổi sang cách khác.

### Artifact

- Vào: `normalized.json` (không đổi schema).
- Ra: `render.json` mục `output.params` thêm:

```json
{"original_volume": 0.3, "speech_volume": 1.0, "skip_original_volume": 1.0, "skip_fade_seconds": 0.5,
 "skip_intervals": [[0.0, 63.0]]}
```

- `_output_fingerprint`: thêm `skip_original_volume`, `skip_fade_seconds`, `skip_intervals`; tăng `"v": 2`. Hệ quả chấp nhận: mọi tập đã render sẽ mux lại một lần ở lần chạy kế tiếp (chỉ bước mux ~1 phút, không TTS/dịch lại). `voice_track.wav` KHÔNG dựng lại (fingerprint voice giữ nguyên).

### Config

```yaml
mixing:
  skip_original_volume: 1.00  # volume audio gốc ở đoạn không lồng tiếng (status silent, vd câu glossary skip); = original_volume để tắt
  skip_fade_seconds: 0.5      # thời gian chuyển mức volume (giây, 0–3); 0 = chuyển ngay
```

Validate: `0 <= skip_original_volume <= 1`, `0 <= skip_fade_seconds <= 3`, lỗi cùng kiểu thông báo như `validate_mixing`.

### Hành vi bắt buộc

- Tập không có segment `silent` → lệnh ffmpeg và output y hệt trước task (filter `volume=0.3000`), chỉ fingerprint đổi.
- `skip_original_volume == original_volume` → không thêm biểu thức (hành vi cũ).
- `--force` / resume như cũ; đổi một trong hai key mới → chỉ mux lại.

### Điểm phải escalate

- Expression ffmpeg không chạy được trên bản ffmpeg của máy (ghi version) hoặc cần filter khác (`asendcmd`, `sidechaincompress`...).
- Muốn coi cả khoảng trống giữa hai câu thường là "đoạn không lồng tiếng".

## Acceptance Criteria

1. Đoạn `silent` có audio gốc ở mức `skip_original_volume`; ngoài đoạn đó vẫn `original_volume`; chuyển mức có fade.
2. Tập không có `silent` → filter ffmpeg không đổi.
3. `render.json` ghi `skip_intervals` + hai param mới; đổi param → mux lại, không dựng lại voice track.
4. Config mới có mặc định, validate, có trong `config.example.yaml`.

## Required verification

- `$PY -m unittest discover -s tests` PASS. Case mới:
  - `skip_intervals`: gộp liền nhau/khoảng cách < min_gap, cắt theo duration, bỏ segment không silent, rỗng.
  - `original_volume_expr`: không khoảng → hằng; fade=0 → `between`; có fade → chứa `clip`; escape dấu phẩy.
  - `mix_video` (mock subprocess): `filter_complex` có `eval=frame` khi có khoảng, y hệt cũ khi không.
  - fingerprint: đổi `skip_original_volume` → output fingerprint đổi, voice fingerprint không đổi.
  - config: mặc định, sai kiểu, ngoài khoảng.
- **Chạy thật**: Ocean Girl Episode 02 (`output/PLllZo-…/5A98HbdhMrU__…`, đã có `normalized.json`, id 1–6 silent 0–63s).
  0. Trước khi sửa: copy `output_vi.mp4` hiện tại ra scratchpad (bản đối chứng, không để trong repo).
  1. `$PY -m app render "<episode_dir>"` → log mux; `render.json` có `skip_intervals` ≈ `[[0.0, 63.0]]`; log `voice_track` SKIP.
  2. Đo `mean_volume` bằng `ffmpeg -ss <t> -t 10 -i <file> -af volumedetect -f null -`:
     - đoạn 20–30s: output mới so với `source.mp4` chênh ≤ 1.5 dB (nhạc giữ to), và to hơn bản đối chứng rõ rệt (~+10 dB với 0.30);
     - đoạn có thuyết minh (vd 120–130s): output mới so với bản đối chứng chênh ≤ 0.5 dB (không đổi).
     Ghi số đo vào Result.
  3. Chạy lại lệnh bước 1 → SKIP cả voice track lẫn output.

## Manual test checklist (Tech Lead)

- Không chạm database / security model / public API.
- [ ] HUMAN LEAD nghe 0:00–1:10 Episode 02: bài hát chủ đề to rõ như bản gốc, chuyển sang thuyết minh mượt.

## Result

- Main changes: `app/audio/render.py` — `skip_intervals()` (gộp segment `silent` cách nhau < 0.5s), `original_volume_expr()` (biểu thức `volume=…:eval=frame`, fade nằm ngoài khoảng, thu hẹp theo câu lồng tiếng kề bên qua `fades`), `mix_video`/`render_episode` nhận tham số mới, fingerprint output `v:2`, `render.json` `output.params` ghi `skip_*`. `app/config.py` — `mixing.skip_original_volume` (1.0), `mixing.skip_fade_seconds` (0.5), `validate_skip_mixing`. Truyền vào render ở `app/pipeline/dub.py` và `app/cli.py` (`_cmd_render`). `config.example.yaml` thêm 2 key.
- Tests: toàn suite 589 OK (implementer + ORCHESTRATOR chạy lại trong worktree). Case mới ở `tests/test_render.py` (intervals, expr, mix filter, fade thu hẹp, tắt khi bằng volume, đổi param chỉ mux lại) và `tests/test_config.py`.
- Chạy thật: Ocean Girl Episode 02, `python -m app render <ep>` → `skip_intervals [[0.0, 83.0]]` (7 segment silent, id 1–7; contract ghi 0–63s là ước lượng sai), voice_track SKIP. mean_volume 20–30s: source −25.7 / mới −25.3 / đối chứng −35.7 dB; 120–130s: mới = đối chứng −18.7 dB. ORCHESTRATOR đo lại (3s): 25s −26.2, 80s −36.7 (source −37.1), 125s −18.3 dB. Chạy lần 2 SKIP cả voice track lẫn output.
- Review: ORCHESTRATOR đọc diff `app/`, không có blocking finding. Fade phía phải ở 83s = 0 vì câu lồng tiếng bắt đầu ngay 83.0s (chuyển mức tức thì, đúng thiết kế không cho nhạc to đè thuyết minh).
- Important findings / decisions: `docs/decisions/checkpoint-9.md` mục CP9-B. Chạy song song CP9-A trong worktree (policy `maxParallelImplementers = 2`); worktree khởi tạo ở commit cũ 99131ae, implementer `merge --ff-only a878855` trước khi làm.
- Known limitations: mọi tập đã render sẽ mux lại một lần ở lần chạy kế (fingerprint v2). Segment `silent` do model dịch ra rỗng ngoài ý muốn cũng được giữ nhạc to. Chưa đo riêng vùng chuyển mức.
- PR: — (commit thẳng `main`).
