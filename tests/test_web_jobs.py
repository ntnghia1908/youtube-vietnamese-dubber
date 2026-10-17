"""Test ``app.web.jobs`` (thuần stdlib, ``popen`` giả) — AC3–AC8."""

from __future__ import annotations

import json
import signal
import subprocess
import threading
import time
import unittest
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory

from app.web.jobs import (
    JobManager,
    JobRequest,
    JobValidationError,
    build_command,
    parse_progress,
    read_log_lines,
    validate_request,
)

VIDEO = "https://www.youtube.com/watch?v=abc123"
PLAYLIST = "https://www.youtube.com/playlist?list=PLxyz"


class FakeProc:
    """Tiến trình giả: stdout là hàng đợi dòng, kết thúc khi ``finish``."""

    _counter = 5000

    def __init__(self, cmd: list[str]) -> None:
        FakeProc._counter += 1
        self.cmd = cmd
        self.pid = FakeProc._counter
        self.returncode: int | None = None
        self._q: Queue[str | None] = Queue()
        self._done = threading.Event()
        self.stdout = self._lines()

    def _lines(self):
        while True:
            item = self._q.get()
            if item is None:
                return
            yield item

    def feed(self, line: str) -> None:
        self._q.put(line)

    def finish(self, code: int) -> None:
        self.returncode = code
        self._q.put(None)
        self._done.set()

    def wait(self, timeout: float | None = None) -> int:
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired(self.cmd, timeout)
        return self.returncode  # type: ignore[return-value]

    def terminate(self) -> None:
        self.finish(-15)

    def kill(self) -> None:
        self.finish(-9)


def wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("hết thời gian chờ điều kiện")


class TestValidate(unittest.TestCase):
    def assertInvalid(self, **kw) -> str:
        with self.assertRaises(JobValidationError) as ctx:
            validate_request(JobRequest(**kw))
        return str(ctx.exception)

    def test_valid_requests(self) -> None:
        validate_request(JobRequest("dub", VIDEO))
        validate_request(JobRequest("dub", "https://youtu.be/abc123", source_lang="zh"))
        validate_request(JobRequest("dub", "https://www.youtube.com/shorts/abc123"))
        validate_request(JobRequest("playlist", PLAYLIST, items="1-3,5", download_only=True))
        # video trong playlist: `dub` vẫn hợp lệ vì có v=
        validate_request(JobRequest("dub", VIDEO + "&list=PLxyz"))

    def test_invalid_requests(self) -> None:
        self.assertInvalid(kind="x", url=VIDEO)
        self.assertIn("YouTube", self.assertInvalid(kind="dub", url="https://example.com/x"))
        self.assertInvalid(kind="dub", url="ftp://www.youtube.com/watch?v=a")
        self.assertInvalid(kind="dub", url="https://evil.com/?u=youtube.com")
        self.assertInvalid(kind="dub", url="https://www.youtube.com/")
        self.assertIn("list=", self.assertInvalid(kind="playlist", url=VIDEO))
        self.assertInvalid(kind="dub", url=PLAYLIST)
        self.assertInvalid(kind="dub", url=VIDEO, source_lang="Chinese")
        self.assertInvalid(kind="playlist", url=PLAYLIST, items="3-1")
        self.assertInvalid(kind="playlist", url=PLAYLIST, items="abc")
        self.assertInvalid(kind="dub", url=VIDEO, items="1")
        self.assertInvalid(kind="dub", url=VIDEO, download_only=True)


class TestBuildAndProgress(unittest.TestCase):
    def test_build_dub(self) -> None:
        cmd = build_command(JobRequest("dub", VIDEO), workspace=Path("output"), config_path=None, python="py")
        self.assertEqual(cmd, ["py", "-m", "app", "dub", VIDEO, "--workspace", "output"])

    def test_build_playlist_options_and_config(self) -> None:
        req = JobRequest("playlist", PLAYLIST, source_lang="zh", items="1-3", force=True, download_only=True)
        cmd = build_command(req, workspace=Path("output"), config_path=Path("my.yaml"), python="py")
        self.assertEqual(
            cmd,
            ["py", "-m", "app", "playlist", PLAYLIST, "--workspace", "output", "--config", "my.yaml",
             "--items", "1-3", "--source-lang", "zh", "--force", "--download-only"],
        )

    def test_parse_progress(self) -> None:
        self.assertEqual(
            parse_progress("[dub] (3/6) translate ..."),
            {"episode": None, "index": 3, "total": 6, "stage": "translate", "state": "running"},
        )
        self.assertEqual(
            parse_progress("[EP02] [dub] (3/6) translate xong (12.0s)\n"),
            {"episode": "EP02", "index": 3, "total": 6, "stage": "translate", "state": "done"},
        )
        self.assertEqual(parse_progress("[dub] (1/6) download SKIP (0.0s)")["state"], "skipped")
        for line in ("", "[playlist-dl] EP02 tải ...", "[EP02/22] Tiêu đề ...", "random"):
            self.assertIsNone(parse_progress(line))


class ManagerCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.procs: list[FakeProc] = []
        self.signals: list[tuple[int, int]] = []
        self.managers: list[JobManager] = []

    def _popen(self, cmd, **kwargs):
        self.kwargs = kwargs
        proc = FakeProc(cmd)
        self.procs.append(proc)
        return proc

    def _killpg(self, pid: int, sig: int) -> None:
        self.signals.append((pid, sig))
        for p in self.procs:
            if p.pid == pid:
                p.finish(-sig)

    def make(self, **kw) -> JobManager:
        m = JobManager(self.ws, None, python="py", popen=self._popen, killpg=self._killpg,
                       cancel_grace_seconds=kw.pop("grace", 10.0), **kw)
        self.managers.append(m)
        self.addCleanup(m.stop)
        return m

    def status(self, m: JobManager, job_id: str) -> str:
        return m.get(job_id)["status"]


class TestManager(ManagerCase):
    def test_success_log_progress_and_env(self) -> None:
        m = self.make()
        m.start()
        job = m.submit(JobRequest("dub", VIDEO, source_lang="zh"))
        self.assertEqual(job["status"], "queued")
        wait_until(lambda: self.procs)
        proc = self.procs[0]
        self.assertEqual(proc.cmd[:5], ["py", "-m", "app", "dub", VIDEO])
        self.assertEqual(self.kwargs["env"]["PYTHONUNBUFFERED"], "1")
        self.assertEqual(self.kwargs["env"]["PYTHONIOENCODING"], "utf-8")
        self.assertNotIn("shell", self.kwargs)
        proc.feed("[dub] (1/6) download ...\n")
        proc.feed("[dub] (3/6) translate ...\n")
        wait_until(lambda: (m.get(job["id"])["progress"] or {}).get("stage") == "translate")
        self.assertEqual(self.status(m, job["id"]), "running")
        proc.feed("dòng tiếng Việt: xin chào\n")
        proc.finish(0)
        wait_until(lambda: self.status(m, job["id"]) == "completed")
        final = m.get(job["id"])
        self.assertEqual(final["exit_code"], 0)
        self.assertIsNotNone(final["finished_at"])
        log = m.log_path(job["id"]).read_text(encoding="utf-8")
        self.assertIn("xin chào", log)
        self.assertIn("[dub] (3/6) translate ...", log)

    def test_nonzero_exit_is_failed(self) -> None:
        m = self.make()
        m.start()
        job = m.submit(JobRequest("dub", VIDEO))
        wait_until(lambda: self.procs)
        self.procs[0].finish(1)
        wait_until(lambda: self.status(m, job["id"]) == "failed")
        self.assertEqual(m.get(job["id"])["exit_code"], 1)

    def test_popen_oserror_is_failed(self) -> None:
        def boom(cmd, **kw):
            raise OSError("không có python")

        m = JobManager(self.ws, None, popen=boom)
        self.addCleanup(m.stop)
        m.start()
        job = m.submit(JobRequest("dub", VIDEO))
        wait_until(lambda: self.status(m, job["id"]) == "failed")
        self.assertIn("không có python", m.log_path(job["id"]).read_text(encoding="utf-8"))

    def test_fifo_single_worker(self) -> None:
        m = self.make()
        m.start()
        j1 = m.submit(JobRequest("dub", VIDEO))
        j2 = m.submit(JobRequest("dub", "https://youtu.be/zzz"))
        wait_until(lambda: self.procs)
        time.sleep(0.3)
        self.assertEqual(len(self.procs), 1)  # job 2 chưa được chạy
        self.assertEqual(self.status(m, j2["id"]), "queued")
        self.procs[0].finish(0)
        wait_until(lambda: len(self.procs) == 2)
        self.assertIn("zzz", self.procs[1].cmd[4])
        self.assertEqual(self.status(m, j1["id"]), "completed")
        self.procs[1].finish(0)
        wait_until(lambda: self.status(m, j2["id"]) == "completed")

    def test_cancel_queued(self) -> None:
        m = self.make()
        m.start()
        m.submit(JobRequest("dub", VIDEO))
        j2 = m.submit(JobRequest("dub", "https://youtu.be/zzz"))
        wait_until(lambda: self.procs)
        self.assertEqual(m.cancel(j2["id"])["status"], "cancelled")
        self.procs[0].finish(0)
        time.sleep(0.3)
        self.assertEqual(len(self.procs), 1)  # job đã hủy không bao giờ chạy
        self.assertEqual(self.status(m, j2["id"]), "cancelled")

    def test_cancel_running_sigterm_group(self) -> None:
        m = self.make()
        m.start()
        job = m.submit(JobRequest("dub", VIDEO))
        wait_until(lambda: self.procs)
        self.procs[0].feed("[dub] (1/6) download ...\n")
        wait_until(lambda: m.get(job["id"])["progress"])
        m.cancel(job["id"])
        wait_until(lambda: self.status(m, job["id"]) == "cancelled")
        self.assertEqual(self.signals, [(self.procs[0].pid, signal.SIGTERM)])

    def test_cancel_escalates_to_sigkill(self) -> None:
        sent: list[int] = []

        def stubborn(pid: int, sig: int) -> None:
            sent.append(sig)
            if sig == signal.SIGKILL:
                self.procs[0].finish(-9)  # SIGTERM bị lờ

        m = JobManager(self.ws, None, python="py", popen=self._popen, killpg=stubborn,
                       cancel_grace_seconds=0.2)
        self.addCleanup(m.stop)
        m.start()
        job = m.submit(JobRequest("dub", VIDEO))
        wait_until(lambda: self.procs)
        m.cancel(job["id"])
        wait_until(lambda: self.status(m, job["id"]) == "cancelled")
        self.assertEqual(sent, [signal.SIGTERM, signal.SIGKILL])

    def test_recovery(self) -> None:
        m1 = self.make()  # chưa start: chỉ ghi state, như một server đã chết
        running = m1.submit(JobRequest("dub", VIDEO))
        queued = m1.submit(JobRequest("dub", "https://youtu.be/zzz"))
        data = m1.get(running["id"])
        data["status"] = "running"
        m1._write(data)
        m2 = self.make()
        m2.start()
        self.assertEqual(self.status(m2, running["id"]), "interrupted")
        wait_until(lambda: self.procs)  # job queued được chạy tiếp
        self.assertIn("zzz", self.procs[0].cmd[4])
        self.assertEqual(self.status(m2, queued["id"]), "running")
        self.procs[0].finish(0)

    def _orphan_setup(self, *, alive: set[int], ours: bool = True):
        m1 = self.make()
        running = m1.submit(JobRequest("dub", VIDEO))
        queued = m1.submit(JobRequest("dub", "https://youtu.be/zzz"))
        data = m1.get(running["id"])
        data.update(status="running", pid=777)
        m1._write(data)
        events: list[str] = []

        def killpg(pid: int, sig: int) -> None:
            events.append(f"kill {pid} {sig}")
            alive.discard(pid)

        m2 = JobManager(self.ws, None, python="py", popen=lambda c, **k: (events.append("popen"), self._popen(c, **k))[1],
                        killpg=killpg, cancel_grace_seconds=0.2,
                        pid_alive=lambda pid: pid in alive, pid_is_pipeline=lambda pid: ours)
        self.addCleanup(m2.stop)
        return m2, running, queued, events

    def test_recovery_kills_live_orphan_before_worker(self) -> None:
        m, running, queued, events = self._orphan_setup(alive={777})
        m.start()
        wait_until(lambda: self.procs)
        self.assertEqual(events[:2], [f"kill 777 {signal.SIGTERM}", "popen"])  # kill rồi mới chạy job queued
        self.assertEqual(self.status(m, running["id"]), "interrupted")
        self.assertIsNone(m.get(running["id"])["pid"])
        self.assertIn("dừng tiến trình mồ côi pid=777", m.log_path(running["id"]).read_text(encoding="utf-8"))
        self.procs[0].finish(0)

    def test_recovery_ignores_dead_or_foreign_pid(self) -> None:
        for alive, ours in ((set(), True), ({777}, False)):
            self.procs.clear()
            m, running, _, events = self._orphan_setup(alive=alive, ours=ours)
            m.start()
            wait_until(lambda: self.procs)
            self.assertFalse([e for e in events if e.startswith("kill")])
            self.assertEqual(self.status(m, running["id"]), "interrupted")
            self.procs[-1].finish(0)
            m.stop()

    def test_recovery_sigkill_when_sigterm_ignored(self) -> None:
        m, running, _, events = self._orphan_setup(alive={777})
        m._killpg = lambda pid, sig: events.append(f"kill {pid} {sig}")  # lờ cả SIGTERM
        m.start()
        wait_until(lambda: self.procs)
        self.assertEqual([e for e in events if e.startswith("kill")],
                         [f"kill 777 {signal.SIGTERM}", f"kill 777 {signal.SIGKILL}"])
        self.procs[0].finish(0)

    def test_pid_recorded_after_popen(self) -> None:
        m = self.make()
        m.start()
        job = m.submit(JobRequest("dub", VIDEO))
        wait_until(lambda: self.procs)
        wait_until(lambda: m.get(job["id"])["pid"] == self.procs[0].pid)
        self.procs[0].finish(0)
        wait_until(lambda: self.status(m, job["id"]) == "completed")
        self.assertIsNone(m.get(job["id"])["pid"])

    def test_retry_creates_new_job_same_request(self) -> None:
        m = self.make()
        m.start()
        job = m.submit(JobRequest("playlist", PLAYLIST, items="1", source_lang="zh"))
        wait_until(lambda: self.procs)
        self.procs[0].finish(1)
        wait_until(lambda: self.status(m, job["id"]) == "failed")
        new = m.retry(job["id"])
        self.assertNotEqual(new["id"], job["id"])
        self.assertEqual(new["retry_of"], job["id"])
        self.assertEqual(new["request"], job["request"])
        self.assertEqual(new["command"], job["command"])
        self.assertNotIn("--force", new["command"])
        wait_until(lambda: len(self.procs) == 2)
        self.procs[1].finish(0)
        self.assertEqual([j["id"] for j in m.list()][0], new["id"])  # mới nhất trước

    def test_unknown_or_malformed_job_id(self) -> None:
        m = self.make()
        self.assertIsNone(m.get("nope"))
        self.assertIsNone(m.get("../../etc/passwd"))
        with self.assertRaises(KeyError):
            m.cancel("20260101-000000-abcdef")

    def test_json_written_atomically(self) -> None:
        m = self.make()
        job = m.submit(JobRequest("dub", VIDEO))
        jobs_dir = self.ws / ".web" / "jobs"
        self.assertEqual([p.name for p in jobs_dir.iterdir()], [f"{job['id']}.json"])  # không sót .tmp
        self.assertEqual(json.loads((jobs_dir / f"{job['id']}.json").read_text(encoding="utf-8"))["id"], job["id"])

    def test_submit_invalid_creates_nothing(self) -> None:
        m = self.make()
        with self.assertRaises(JobValidationError):
            m.submit(JobRequest("dub", "https://example.com/x"))
        self.assertEqual(m.list(), [])

    def test_config_path_passed_to_command(self) -> None:
        m = JobManager(self.ws, Path("c.yaml"), python="py", popen=self._popen)
        job = m.submit(JobRequest("dub", VIDEO))
        self.assertIn("--config", job["command"])
        self.assertIn("c.yaml", job["command"])


class TestReadLog(unittest.TestCase):
    def test_partial_line_only_when_final(self) -> None:
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.log"
            p.write_bytes("một\nhai\nba".encode("utf-8"))
            lines, off = read_log_lines(p, 0, final=False)
            self.assertEqual([t for _, t in lines], ["một", "hai"])
            self.assertEqual(off, len("một\nhai\n".encode("utf-8")))
            lines, off2 = read_log_lines(p, off, final=True)
            self.assertEqual([t for _, t in lines], ["ba"])
            self.assertEqual(read_log_lines(p, off2, final=True)[0], [])
            self.assertEqual(read_log_lines(Path(tmp) / "none", 0, final=True), ([], 0))


if __name__ == "__main__":
    unittest.main()
