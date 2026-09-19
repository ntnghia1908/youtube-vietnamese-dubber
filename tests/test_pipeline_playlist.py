"""Test cho ``app.pipeline.playlist`` (Checkpoint 8, gồm SỬA ĐỔI 1 — luồng
tải song song với luồng xử lý).

Patch ``fetch_playlist``, ``run_dub``, ``download_video``, ``load_episode_info``
ở ĐÚNG chỗ ``app.pipeline.playlist`` import chúng (module import ở cấp
module, patch module gốc không có tác dụng — cùng lý do nêu ở
``tests/test_pipeline_dub.py``). Từ SỬA ĐỔI 1, việc tải diễn ra trong một
luồng nền thật của module (không mock hoá ``threading``) nên mọi test ở
đây, kể cả khi không quan tâm tới tải, đều phải mock ``download_video``/
``load_episode_info`` — nếu không chúng sẽ thật sự gọi yt-dlp.

Đây chỉ là unit test (mock hoá toàn bộ I/O thật ngoài filesystem tạm) —
theo CLAUDE.md, checkpoint chỉ coi là xong sau khi chạy thật với playlist
thật và đọc ``playlist.json`` sinh ra.
"""

from __future__ import annotations

import json
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import AppConfig, TranslationConfig
from app.pipeline.dub import DubError, DubOptions, DubResult
from app.pipeline.playlist import (
    PLAYLIST_STATE_FILENAME,
    PlaylistError,
    PlaylistOptions,
    parse_item_spec,
    run_playlist,
)
from app.youtube.download import EpisodeInfo, VideoDownloadError, build_episode_dir_name
from app.youtube.playlist import PlaylistEntry, PlaylistInfo


def _entries(n: int, *, title_prefix: str = "Ep") -> list[PlaylistEntry]:
    return [
        PlaylistEntry(
            index=i, video_id=f"vid{i:03d}", title=f"{title_prefix} {i}", url=f"https://youtu.be/vid{i:03d}"
        )
        for i in range(1, n + 1)
    ]


def _playlist_info(
    entries: list[PlaylistEntry] | None = None,
    *,
    n: int = 3,
    playlist_id: str = "PLxxx",
    title: str = "Series Demo",
) -> PlaylistInfo:
    return PlaylistInfo(
        playlist_id=playlist_id,
        title=title,
        url="https://www.youtube.com/playlist?list=PLxxx",
        entries=entries if entries is not None else _entries(n),
    )


def _dub_result(episode_dir: Path, **overrides: object) -> DubResult:
    base: dict[str, object] = dict(
        episode_dir=episode_dir,
        output_path=episode_dir / "output_vi.mp4",
        source_language="en",
        segments=10,
        translate_failed_ids=[],
        missing_ids=[],
        too_long_ids=[],
        repair_rounds_used=0,
        glossary_paths=[],
        stage_seconds={
            "download": 0.0, "transcribe": 1.0, "translate": 1.0,
            "tts": 1.0, "normalize": 1.0, "render": 1.0,
        },
        skipped_stages=["download"],
    )
    base.update(overrides)
    return DubResult(**base)  # type: ignore[arg-type]


def _fake_download_video(*, on_call=None):
    """Side effect giả lập ``download_video``: tạo thật ``source.mp4`` +
    ``metadata.json`` trong ``<workspace>/<video_id>__Ep``."""

    def _download(url: str, workspace_dir: Path, *, force: bool = False) -> EpisodeInfo:
        video_id = url.rsplit("/", 1)[-1]
        episode_dir = Path(workspace_dir) / f"{video_id}__Ep"
        episode_dir.mkdir(parents=True, exist_ok=True)
        (episode_dir / "metadata.json").write_text(
            json.dumps({"id": video_id, "title": "Ep"}), encoding="utf-8"
        )
        (episode_dir / "source.mp4").write_bytes(b"fake-video")
        if on_call is not None:
            on_call(video_id)
        return EpisodeInfo(
            video_id=video_id, title="Ep", source_url=url, episode_dir=episode_dir,
            metadata_path=episode_dir / "metadata.json", source_path=episode_dir / "source.mp4",
        )

    return _download


def _fake_load_episode_info(episode_dir: Path, url: str) -> EpisodeInfo:
    video_id = episode_dir.name.split("__", 1)[0]
    return EpisodeInfo(
        video_id=video_id, title="Ep", source_url=url, episode_dir=episode_dir,
        metadata_path=episode_dir / "metadata.json", source_path=episode_dir / "source.mp4",
    )


def _success_run_dub(overrides_by_id: dict[str, dict] | None = None):
    """Side effect giả lập ``run_dub`` thành công: BẮT BUỘC nhận ``episode=``
    (SỬA ĐỔI 1 — playlist không bao giờ để ``run_dub`` tự tải), tạo thật
    ``output_vi.mp4`` trong ``episode.episode_dir``."""
    overrides_by_id = overrides_by_id or {}

    def _run_dub(url: str, config: AppConfig, options: DubOptions, *, log, episode: EpisodeInfo | None = None):
        assert episode is not None, "playlist phải luôn truyền episode= cho run_dub"
        (episode.episode_dir / "output_vi.mp4").write_bytes(b"fake")
        return _dub_result(episode.episode_dir, **overrides_by_id.get(episode.video_id, {}))

    return _run_dub


class PlaylistTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()
        self.config = AppConfig(translation=TranslationConfig(model="m"))
        self.dub_options = DubOptions(workspace=self.workspace)
        self.log_lines: list[str] = []

    def _log(self, message: str) -> None:
        self.log_lines.append(message)

    def _patch(
        self,
        *,
        playlist_info: PlaylistInfo | None = None,
        run_dub_mock: MagicMock | None = None,
        download_video_mock: MagicMock | None = None,
        load_episode_info_mock: MagicMock | None = None,
    ) -> SimpleNamespace:
        mocks = SimpleNamespace(
            fetch=MagicMock(return_value=playlist_info or _playlist_info()),
            run_dub=run_dub_mock or MagicMock(side_effect=_success_run_dub()),
            download_video=download_video_mock or MagicMock(side_effect=_fake_download_video()),
            load_episode_info=load_episode_info_mock or MagicMock(side_effect=_fake_load_episode_info),
        )
        targets = {
            "fetch_playlist": mocks.fetch,
            "run_dub": mocks.run_dub,
            "download_video": mocks.download_video,
            "load_episode_info": mocks.load_episode_info,
        }
        for name, mock in targets.items():
            patcher = patch(f"app.pipeline.playlist.{name}", mock)
            patcher.start()
            self.addCleanup(patcher.stop)
        return mocks

    def _run(self, options: PlaylistOptions | None = None):
        return run_playlist(
            "https://www.youtube.com/playlist?list=PLxxx",
            self.config,
            options or PlaylistOptions(dub=self.dub_options),
            log=self._log,
        )

    def _state_path(self, result) -> Path:
        return result.playlist_dir / PLAYLIST_STATE_FILENAME

    def _read_state(self, result) -> dict:
        return json.loads(self._state_path(result).read_text(encoding="utf-8"))


class TestFirstRun(PlaylistTestCase):
    def test_calls_run_dub_in_order_with_playlist_dir_workspace_and_warnings(self) -> None:
        overrides = {"vid002": {"translate_failed_ids": [4, 9]}}
        mocks = self._patch(run_dub_mock=MagicMock(side_effect=_success_run_dub(overrides)))

        result = self._run()

        urls = [c.args[0] for c in mocks.run_dub.call_args_list]
        self.assertEqual(urls, [
            "https://youtu.be/vid001", "https://youtu.be/vid002", "https://youtu.be/vid003",
        ])
        for call in mocks.run_dub.call_args_list:
            self.assertEqual(call.args[2].workspace, result.playlist_dir)
            # SỬA ĐỔI 1: run_dub luôn nhận episode= (đã tải sẵn), không bao
            # giờ để run_dub tự tải.
            self.assertIsInstance(call.kwargs["episode"], EpisodeInfo)

        self.assertEqual(result.total, 3)
        self.assertEqual(result.selected, 3)
        self.assertEqual([e.outcome for e in result.episodes], ["completed"] * 3)

        state = self._read_state(result)
        self.assertEqual(len(state["entries"]), 3)
        self.assertTrue(all(e["status"] == "completed" for e in state["entries"]))
        self.assertTrue(all(e["downloaded"] is True for e in state["entries"]))
        ep2 = next(e for e in state["entries"] if e["video_id"] == "vid002")
        self.assertEqual(ep2["warnings"], {"translate_failed_ids": [4, 9], "missing_ids": [], "too_long_ids": []})
        self.assertEqual(ep2["episode_dir"], "vid002__Ep")
        self.assertEqual(ep2["output_path"], "vid002__Ep/output_vi.mp4")


class TestSecondRunSkips(PlaylistTestCase):
    def test_second_run_all_skipped_run_dub_and_download_not_called_again(self) -> None:
        self._patch()
        self._run()

        mocks2 = self._patch()
        result2 = self._run()

        mocks2.run_dub.assert_not_called()
        mocks2.download_video.assert_not_called()
        mocks2.load_episode_info.assert_not_called()
        self.assertEqual([e.outcome for e in result2.episodes], ["skipped"] * 3)

    def test_completed_but_missing_output_file_reruns_using_cached_download(self) -> None:
        self._patch()
        result1 = self._run()
        ep1_output = result1.playlist_dir / "vid001__Ep" / "output_vi.mp4"
        ep1_output.unlink()

        mocks2 = self._patch()
        result2 = self._run(PlaylistOptions(dub=self.dub_options))

        # Đã downloaded=True + source.mp4/metadata.json còn -> dùng
        # load_episode_info, KHÔNG gọi lại download_video (SỬA ĐỔI 1).
        mocks2.download_video.assert_not_called()
        called_urls = [c.args[0] for c in mocks2.run_dub.call_args_list]
        self.assertEqual(called_urls, ["https://youtu.be/vid001"])
        outcomes = {e.video_id: e.outcome for e in result2.episodes}
        self.assertEqual(outcomes["vid001"], "completed")


class TestEpisodeFailureContinues(PlaylistTestCase):
    def test_failing_episode_does_not_block_next_one(self) -> None:
        def _run_dub(url, config, options, *, log, episode=None):
            if url.endswith("vid002"):
                raise DubError("translate", "Không kết nối được Ollama")
            return _success_run_dub()(url, config, options, log=log, episode=episode)

        mocks = self._patch(run_dub_mock=MagicMock(side_effect=_run_dub))
        result = self._run()

        outcomes = {e.video_id: e.outcome for e in result.episodes}
        self.assertEqual(outcomes, {"vid001": "completed", "vid002": "failed", "vid003": "completed"})
        ep2 = next(e for e in result.episodes if e.video_id == "vid002")
        self.assertEqual(ep2.error_stage, "translate")

        state = self._read_state(result)
        ep2_state = next(e for e in state["entries"] if e["video_id"] == "vid002")
        self.assertEqual(ep2_state["status"], "failed")
        self.assertEqual(ep2_state["error_stage"], "translate")
        # Tải thành công dù xử lý lỗi -> "downloaded" vẫn true (khác lỗi tải).
        self.assertTrue(ep2_state["downloaded"])

        # Lần sau: tập 2 (failed) được thử lại tự động, không cần --recheck/--force.
        mocks2 = self._patch(run_dub_mock=MagicMock(side_effect=_success_run_dub()))
        result2 = self._run()
        urls2 = [c.args[0] for c in mocks2.run_dub.call_args_list]
        self.assertEqual(urls2, ["https://youtu.be/vid002"])
        self.assertEqual(
            next(e.outcome for e in result2.episodes if e.video_id == "vid002"), "completed"
        )


class TestDownloadFailureContinues(PlaylistTestCase):
    """SỬA ĐỔI 1: tải lỗi -> failed ở stage 'download', tập sau vẫn xử lý."""

    def test_download_error_marks_failed_download_stage_and_continues(self) -> None:
        def _download(url, workspace_dir, *, force=False):
            if url.endswith("vid001"):
                raise VideoDownloadError("mất mạng")
            return _fake_download_video()(url, workspace_dir, force=force)

        mocks = self._patch(download_video_mock=MagicMock(side_effect=_download))
        result = self._run()

        outcomes = {e.video_id: (e.outcome, e.error_stage) for e in result.episodes}
        self.assertEqual(outcomes["vid001"], ("failed", "download"))
        self.assertEqual(outcomes["vid002"], ("completed", None))
        self.assertEqual(outcomes["vid003"], ("completed", None))

        state = self._read_state(result)
        ep1 = next(e for e in state["entries"] if e["video_id"] == "vid001")
        self.assertEqual(ep1["status"], "failed")
        self.assertEqual(ep1["error_stage"], "download")
        self.assertIn("mất mạng", ep1["error"])
        self.assertFalse(ep1["downloaded"])

        # run_dub không bao giờ được gọi cho tập tải lỗi (không có EpisodeInfo).
        called_urls = {c.args[0] for c in mocks.run_dub.call_args_list}
        self.assertNotIn("https://youtu.be/vid001", called_urls)

    def test_download_failures_do_not_count_toward_abort(self) -> None:
        # Playlist thật có 9 video Private liền nhau: lỗi tải không được làm
        # dừng sớm, tập sau chúng vẫn phải được xử lý.
        def _download(url, workspace_dir, *, force=False):
            if not url.endswith("vid006"):
                raise VideoDownloadError("Private video")
            return _fake_download_video()(url, workspace_dir, force=force)

        mocks = self._patch(
            playlist_info=_playlist_info(n=6),
            download_video_mock=MagicMock(side_effect=_download),
        )
        result = self._run(PlaylistOptions(dub=self.dub_options, max_consecutive_failures=2))

        self.assertFalse(result.aborted)
        outcomes = [e.outcome for e in result.episodes]
        self.assertEqual(outcomes, ["failed"] * 5 + ["completed"])
        self.assertEqual(mocks.run_dub.call_count, 1)

    def test_unexpected_download_thread_error_raises_instead_of_hanging(self) -> None:
        # Lỗi lạ ở luồng tải (không phải VideoDownloadError) phải nổi lên ở
        # luồng chính; trước đây event không được set -> treo vĩnh viễn.
        self._patch(download_video_mock=MagicMock(side_effect=RuntimeError("bug")))
        outcome: dict[str, BaseException] = {}

        def _target() -> None:
            try:
                self._run()
            except BaseException as exc:  # noqa: BLE001
                outcome["exc"] = exc

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive(), "run_playlist bị treo khi luồng tải gặp lỗi lạ")
        self.assertIsInstance(outcome.get("exc"), RuntimeError)


class TestRecheckAndForce(PlaylistTestCase):
    def test_recheck_reruns_completed_episodes(self) -> None:
        self._patch()
        self._run()

        mocks2 = self._patch()
        result2 = self._run(PlaylistOptions(dub=self.dub_options, recheck=True))

        self.assertEqual(mocks2.run_dub.call_count, 3)
        self.assertEqual([e.outcome for e in result2.episodes], ["completed"] * 3)

    def test_force_reruns_and_passes_force_down_and_bypasses_download_cache(self) -> None:
        self._patch()
        self._run()

        forced_dub = replace(self.dub_options, force=True)
        mocks2 = self._patch()
        self._run(PlaylistOptions(dub=forced_dub))

        self.assertEqual(mocks2.run_dub.call_count, 3)
        for call in mocks2.run_dub.call_args_list:
            self.assertTrue(call.args[2].force)
        # force=True bỏ qua cache tải (dù đã downloaded=True từ lần trước).
        self.assertEqual(mocks2.download_video.call_count, 3)
        mocks2.load_episode_info.assert_not_called()


class TestItemsSelection(PlaylistTestCase):
    def test_items_limits_to_selected_indexes(self) -> None:
        mocks = self._patch()
        result = self._run(PlaylistOptions(dub=self.dub_options, items=frozenset({2})))

        self.assertEqual([c.args[0] for c in mocks.run_dub.call_args_list], ["https://youtu.be/vid002"])
        self.assertEqual([e.video_id for e in result.episodes], ["vid002"])
        self.assertEqual(result.selected, 1)
        self.assertEqual(result.total, 3)

        state = self._read_state(result)
        others = [e for e in state["entries"] if e["video_id"] != "vid002"]
        self.assertTrue(all(e["status"] == "pending" for e in others))

    def test_items_with_out_of_range_index_logs_warning(self) -> None:
        self._patch()
        self._run(PlaylistOptions(dub=self.dub_options, items=frozenset({2, 99})))

        self.assertTrue(any("99" in line for line in self.log_lines))


class TestMaxConsecutiveFailures(PlaylistTestCase):
    def _failing_run_dub(self):
        return MagicMock(side_effect=DubError("translate", "boom"))

    def test_aborts_after_n_consecutive_failures(self) -> None:
        mocks = self._patch(run_dub_mock=self._failing_run_dub())
        result = self._run(PlaylistOptions(dub=self.dub_options, max_consecutive_failures=2))

        self.assertTrue(result.aborted)
        self.assertEqual(mocks.run_dub.call_count, 2)
        outcomes = [e.outcome for e in result.episodes]
        self.assertEqual(outcomes, ["failed", "failed", "not_run"])

    def test_success_between_failures_resets_counter_no_abort(self) -> None:
        def _run_dub(url, config, options, *, log, episode=None):
            if url.endswith("vid002"):
                return _success_run_dub()(url, config, options, log=log, episode=episode)
            raise DubError("translate", "boom")

        mocks = self._patch(run_dub_mock=MagicMock(side_effect=_run_dub))
        result = self._run(PlaylistOptions(dub=self.dub_options, max_consecutive_failures=2))

        self.assertFalse(result.aborted)
        self.assertEqual(mocks.run_dub.call_count, 3)
        self.assertEqual([e.outcome for e in result.episodes], ["failed", "completed", "failed"])

    def test_zero_never_aborts(self) -> None:
        mocks = self._patch(run_dub_mock=self._failing_run_dub())
        result = self._run(PlaylistOptions(dub=self.dub_options, max_consecutive_failures=0))

        self.assertFalse(result.aborted)
        self.assertEqual(mocks.run_dub.call_count, 3)
        self.assertEqual([e.outcome for e in result.episodes], ["failed"] * 3)


class TestMerge(PlaylistTestCase):
    def test_merge_drops_removed_ids_and_adds_new_ones_keeping_status(self) -> None:
        entries_v1 = [
            PlaylistEntry(index=1, video_id="v1", title="Ep 1", url="https://youtu.be/v1"),
            PlaylistEntry(index=2, video_id="v2", title="Ep 2", url="https://youtu.be/v2"),
        ]
        self._patch(playlist_info=_playlist_info(entries_v1))
        self._run()

        entries_v2 = [
            PlaylistEntry(index=1, video_id="v1", title="Ep 1 Moi", url="https://youtu.be/v1"),
            PlaylistEntry(index=2, video_id="v3", title="Ep 3", url="https://youtu.be/v3"),
        ]
        self._patch(playlist_info=_playlist_info(entries_v2))
        result2 = self._run()

        state = self._read_state(result2)
        video_ids = {e["video_id"] for e in state["entries"]}
        self.assertEqual(video_ids, {"v1", "v3"})
        v1_entry = next(e for e in state["entries"] if e["video_id"] == "v1")
        self.assertEqual(v1_entry["status"], "completed")  # giữ nguyên, không chạy lại
        self.assertEqual(v1_entry["title"], "Ep 1 Moi")  # title cập nhật theo bản mới
        v3_entry = next(e for e in state["entries"] if e["video_id"] == "v3")
        self.assertEqual(v3_entry["status"], "completed")  # tập mới -> pending -> được chạy -> completed
        self.assertTrue(any("không còn trong playlist" in line for line in self.log_lines))


class TestKeyboardInterrupt(PlaylistTestCase):
    def test_keyboard_interrupt_propagates_and_keeps_prior_state(self) -> None:
        def _run_dub(url, config, options, *, log, episode=None):
            if url.endswith("vid002"):
                raise KeyboardInterrupt()
            return _success_run_dub()(url, config, options, log=log, episode=episode)

        self._patch(playlist_info=_playlist_info(n=2), run_dub_mock=MagicMock(side_effect=_run_dub))

        playlist_dir = self.workspace / build_episode_dir_name("PLxxx", "Series Demo")
        with self.assertRaises(KeyboardInterrupt):
            self._run()

        state = json.loads((playlist_dir / PLAYLIST_STATE_FILENAME).read_text(encoding="utf-8"))
        by_id = {e["video_id"]: e for e in state["entries"]}
        self.assertEqual(by_id["vid001"]["status"], "completed")
        self.assertNotEqual(by_id["vid002"]["status"], "completed")


class TestBrokenState(PlaylistTestCase):
    def test_broken_json_raises_and_does_not_overwrite(self) -> None:
        self._patch()
        playlist_dir = self.workspace / build_episode_dir_name("PLxxx", "Series Demo")
        playlist_dir.mkdir(parents=True)
        state_path = playlist_dir / PLAYLIST_STATE_FILENAME
        state_path.write_text("{ khong phai json hop le", encoding="utf-8")

        with self.assertRaises(PlaylistError):
            self._run()

        self.assertEqual(state_path.read_text(encoding="utf-8"), "{ khong phai json hop le")


class TestConcurrentDownload(PlaylistTestCase):
    """SỬA ĐỔI 1: luồng tải chạy TRƯỚC/SONG SONG với luồng xử lý."""

    def test_next_episode_downloads_while_current_is_processed(self) -> None:
        vid2_downloaded = threading.Event()

        def _download(url, workspace_dir, *, force=False):
            result = _fake_download_video()(url, workspace_dir, force=force)
            if url.endswith("vid002"):
                vid2_downloaded.set()
            return result

        def _run_dub(url, config, options, *, log, episode=None):
            if url.endswith("vid001"):
                # Nếu tải chạy tuần tự SAU xử lý (không song song), tập 2
                # chưa thể tải xong lúc này -> wait() sẽ timeout -> fail test.
                self.assertTrue(
                    vid2_downloaded.wait(timeout=2.0),
                    "tập 2 phải được tải xong trong lúc tập 1 còn đang run_dub",
                )
            return _success_run_dub()(url, config, options, log=log, episode=episode)

        self._patch(
            playlist_info=_playlist_info(n=2),
            run_dub_mock=MagicMock(side_effect=_run_dub),
            download_video_mock=MagicMock(side_effect=_download),
        )

        result = self._run()
        self.assertEqual([e.outcome for e in result.episodes], ["completed", "completed"])


class TestDownloadOnly(PlaylistTestCase):
    def test_download_only_does_not_call_run_dub(self) -> None:
        mocks = self._patch()
        result = self._run(PlaylistOptions(dub=self.dub_options, download_only=True))

        mocks.run_dub.assert_not_called()
        self.assertEqual(mocks.download_video.call_count, 3)
        self.assertEqual([e.outcome for e in result.episodes], ["downloaded"] * 3)

        state = self._read_state(result)
        self.assertTrue(all(e["downloaded"] for e in state["entries"]))
        self.assertTrue(all(e["status"] == "pending" for e in state["entries"]))
        for e in state["entries"]:
            self.assertTrue((result.playlist_dir / e["episode_dir"] / "source.mp4").exists())

    def test_download_only_failure_counts_as_failed(self) -> None:
        def _download(url, workspace_dir, *, force=False):
            if url.endswith("vid002"):
                raise VideoDownloadError("boom")
            return _fake_download_video()(url, workspace_dir, force=force)

        self._patch(download_video_mock=MagicMock(side_effect=_download))
        result = self._run(PlaylistOptions(dub=self.dub_options, download_only=True))

        outcomes = {e.video_id: e.outcome for e in result.episodes}
        self.assertEqual(outcomes, {"vid001": "downloaded", "vid002": "failed", "vid003": "downloaded"})


class TestDownloadCacheReuse(PlaylistTestCase):
    """SỬA ĐỔI 1: tập đã ``downloaded`` + file còn -> load_episode_info, không gọi mạng."""

    def test_already_downloaded_uses_load_episode_info_not_download_video(self) -> None:
        self._patch()
        self._run(PlaylistOptions(dub=self.dub_options, download_only=True))

        mocks2 = self._patch()
        result2 = self._run()

        mocks2.download_video.assert_not_called()
        self.assertEqual(mocks2.load_episode_info.call_count, 3)
        self.assertEqual([e.outcome for e in result2.episodes], ["completed"] * 3)


class TestParseItemSpec(unittest.TestCase):
    def test_valid_specs(self) -> None:
        self.assertEqual(parse_item_spec("1-3,5"), frozenset({1, 2, 3, 5}))
        self.assertEqual(parse_item_spec(" 2 , 4-4 "), frozenset({2, 4}))

    def test_invalid_specs_raise(self) -> None:
        for bad in ("", "0", "3-1", "a", "1-"):
            with self.subTest(bad=bad):
                with self.assertRaises(PlaylistError):
                    parse_item_spec(bad)


if __name__ == "__main__":
    unittest.main()
