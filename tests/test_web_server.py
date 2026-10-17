"""Test server Web UI bằng ``TestClient`` (cần extra ``web``) — AC3–AC5, AC10, AC11."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from fastapi.testclient import TestClient

    from app.web.server import create_app

    HAVE_WEB = True
except ImportError:  # chưa cài extra `web`
    HAVE_WEB = False

from app.web.jobs import JobManager
from tests.test_web_jobs import FakeProc, wait_until

VIDEO = "https://www.youtube.com/watch?v=abc123"
EVIL = '<script>alert("x")</script>'


def _w(path: Path, content: bytes | str = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)


def _episode(d: Path, title: str, *, output: bool = True) -> None:
    _w(d / "metadata.json", json.dumps({"id": "v1", "title": title, "duration_seconds": 61}))
    _w(d / "source.mp4", bytes(range(256)) * 8)
    _w(d / "transcript.json", json.dumps({"segments": [{"id": 1, "start": 0, "end": 2, "text": "hi"}]}))
    _w(d / "translated.json", json.dumps({"segments": [
        {"id": 1, "start": 0, "end": 2, "source_text": "hi", "translated_text": "chào"}]}))
    _w(d / "tts" / "manifest.json", "{}")
    _w(d / "normalized.json", json.dumps({"segments": [
        {"id": 1, "start": 0.5, "end": 2, "source_text": "hi", "translated_text": "chào",
         "status": "too_long", "tempo": 1.4},
        {"id": 2, "start": 3, "end": 4, "source_text": "yo", "translated_text": "ừ",
         "status": "normal", "tempo": None}]}))
    if output:
        _w(d / "output_vi.mp4", bytes(range(256)) * 16)


@unittest.skipUnless(HAVE_WEB, "cần `pip install -e .[web]`")
class TestServer(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.procs: list[FakeProc] = []

        def popen(cmd, **kw):
            proc = FakeProc(cmd)
            self.procs.append(proc)
            return proc

        self.manager = JobManager(self.ws, None, python="py", popen=popen,
                                  killpg=lambda pid, sig: [p.finish(-sig) for p in self.procs if p.pid == pid])
        self.client = TestClient(create_app(self.ws, self.manager, allowed_hosts=("testserver",)))
        self.addCleanup(self.manager.stop)

    def test_host_header_checked(self) -> None:
        _episode(self.ws / "v1__t", "T")
        for bad in ("evil.example:8799", "evil.example", "127.0.0.1.evil.example", ""):
            self.assertEqual(self.client.get("/api/library", headers={"Host": bad}).status_code, 400, bad)
        self.assertEqual(self.client.get("/media/v1__t/source", headers={"Host": "evil.example"}).status_code, 400)
        for good in ("127.0.0.1:8765", "localhost:8765", "[::1]:8765", "localhost"):
            self.assertEqual(self.client.get("/api/library", headers={"Host": good}).status_code, 200, good)

    def test_empty_workspace_redirects_to_jobs(self) -> None:
        r = self.client.get("/", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (307, "/jobs"))
        r = self.client.get("/jobs")
        self.assertEqual(r.status_code, 200)
        self.assertIn('id="job-form"', r.text)

    def test_pages_ok_and_escape(self) -> None:
        _episode(self.ws / "v1__t", EVIL)
        pl = self.ws / "PL__x"
        _w(pl / "playlist.json", json.dumps({"title": EVIL, "entries": [
            {"index": 1, "title": "Tập 1", "status": "failed", "downloaded": False,
             "error_stage": "download", "error": "Private video\nsign in required", "seconds": 1.5,
             "episode_dir": "a__A"},
            {"index": 2, "title": "Tập 2", "status": "completed", "episode_dir": "b__B"}]}))
        _episode(pl / "b__B", "Tập 2")
        library = self.client.get("/")
        self.assertEqual(library.status_code, 200)
        self.assertNotIn("<script>alert", library.text)
        self.assertIn("&lt;script&gt;", library.text)
        self.assertEqual(self.client.get("/library").status_code, 200)

        r = self.client.get("/pl/PL__x")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Private video\nsign in required", r.text)  # lỗi đầy đủ, nhiều dòng
        self.assertIn('href="/ep/PL__x~b__B"', r.text)
        self.assertNotIn("<script>alert", r.text)

        r = self.client.get("/ep/v1__t")
        self.assertEqual(r.status_code, 200)
        self.assertIn("<video", r.text)
        self.assertIn('data-start="0.5"', r.text)
        self.assertIn('data-status="too_long"', r.text)
        self.assertNotIn("<script>alert", r.text)
        self.assertIn("&lt;script&gt;", r.text)

    def test_episode_without_output_still_opens(self) -> None:
        _episode(self.ws / "v1__t", "T", output=False)
        r = self.client.get("/ep/v1__t")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Chưa có", r.text)
        self.assertIn("/media/v1__t/source", r.text)
        self.assertEqual(self.client.get("/media/v1__t/output").status_code, 404)

    def test_submit_validation_and_origin(self) -> None:
        r = self.client.post("/api/jobs", json={"kind": "dub", "url": "https://example.com/x"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("YouTube", r.json()["error"])
        self.assertEqual(self.client.post("/api/jobs", content="không phải json").status_code, 400)
        self.assertEqual(self.client.post("/api/jobs", json={"kind": "dub"}).status_code, 400)
        self.assertEqual(self.client.post("/api/jobs", json={"kind": "dub", "url": VIDEO, "source_lang": 5}).status_code, 400)
        self.assertEqual(self.manager.list(), [])

        r = self.client.post("/api/jobs", json={"kind": "dub", "url": VIDEO},
                             headers={"Origin": "http://evil.example"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.manager.list(), [])

        r = self.client.post("/api/jobs", json={"kind": "dub", "url": VIDEO, "source_lang": "zh"},
                             headers={"Origin": "http://127.0.0.1:8765"})
        self.assertEqual(r.status_code, 201)
        job = r.json()
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["request"]["source_lang"], "zh")
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}").json()["id"], job["id"])
        self.assertEqual(len(self.client.get("/api/jobs").json()), 1)
        self.assertEqual(self.client.get(f"/jobs/{job['id']}").status_code, 200)
        self.assertEqual(self.client.get("/jobs").status_code, 200)

        r = self.client.post(f"/api/jobs/{job['id']}/cancel", headers={"Origin": "http://evil.example"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.post(f"/api/jobs/{job['id']}/cancel").json()["status"], "cancelled")
        retry = self.client.post(f"/api/jobs/{job['id']}/retry").json()
        self.assertEqual(retry["retry_of"], job["id"])
        self.assertEqual(self.client.get("/api/jobs/20260101-000000-abcdef").status_code, 404)
        self.assertEqual(self.client.post("/api/jobs/zzz/cancel").status_code, 404)

    def test_submit_form_encoded(self) -> None:
        r = self.client.post(
            "/api/jobs",
            content="kind=playlist&url=https%3A%2F%2Fwww.youtube.com%2Fplaylist%3Flist%3DPL1&items=1-2&download_only=on",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(r.status_code, 201, r.text)
        self.assertIn("--download-only", r.json()["command"])
        self.assertIn("1-2", r.json()["command"])

    def test_sse_log_and_status(self) -> None:
        self.manager.start()
        job = self.client.post("/api/jobs", json={"kind": "dub", "url": VIDEO}).json()
        wait_until(lambda: self.procs)
        self.procs[0].feed("[dub] (3/6) translate ...\n")
        self.procs[0].feed("xin chào\n")
        self.procs[0].finish(0)
        wait_until(lambda: self.manager.get(job["id"])["status"] == "completed")
        r = self.client.get(f"/api/jobs/{job['id']}/events")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/event-stream"))
        self.assertIn('event: log\nid: ', r.text)
        self.assertIn('data: "xin chào"', r.text)
        self.assertIn('"status": "completed"', r.text)
        self.assertIn('"stage": "translate"', r.text)

        # Last-Event-ID: nối lại sau dòng đầu -> không gửi lại dòng đầu.
        first_end = len("[dub] (3/6) translate ...\n")
        r2 = self.client.get(f"/api/jobs/{job['id']}/events", headers={"Last-Event-ID": str(first_end)})
        self.assertNotIn("translate ...", r2.text)
        self.assertIn("xin chào", r2.text)

    def test_media_range_and_traversal(self) -> None:
        _episode(self.ws / "v1__t", "T")
        r = self.client.get("/media/v1__t/source", headers={"Range": "bytes=0-9"})
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r.headers["content-range"], "bytes 0-9/2048")
        self.assertEqual(len(r.content), 10)
        self.assertEqual(self.client.get("/media/v1__t/output").status_code, 200)
        self.assertEqual(self.client.get("/media/v1__t/other").status_code, 404)
        # httpx gộp "/.." thành "/" trước khi gửi, nên ".." trần không tới được route.
        for bad in ("..%2F..%2Fetc", "..~..", "%2e%2e%2F%2e%2e", "nope"):
            self.assertEqual(self.client.get(f"/media/{bad}/source").status_code, 404, bad)
            self.assertEqual(self.client.get(f"/ep/{bad}").status_code, 404, bad)
            self.assertEqual(self.client.get(f"/pl/{bad}").status_code, 404, bad)
            self.assertEqual(self.client.get(f"/api/episodes/{bad}/segments").status_code, 404, bad)

    def test_library_and_segments_api(self) -> None:
        _episode(self.ws / "v1__t", "T")
        lib = self.client.get("/api/library").json()
        self.assertEqual(lib["episodes"][0]["too_long_count"], 1)
        self.assertEqual(lib["episodes"][0]["stages"]["render"], "done")
        segs = self.client.get("/api/episodes/v1__t/segments").json()
        self.assertEqual([s["status"] for s in segs], ["too_long", "normal"])

    def test_server_creates_nothing_in_workspace(self) -> None:
        _episode(self.ws / "v1__t", "T")
        before = sorted(p.relative_to(self.ws).as_posix() for p in self.ws.rglob("*"))
        for path in ("/", "/library", "/jobs", "/ep/v1__t", "/api/library", "/media/v1__t/source"):
            self.client.get(path)
        after = sorted(p.relative_to(self.ws).as_posix() for p in self.ws.rglob("*"))
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
