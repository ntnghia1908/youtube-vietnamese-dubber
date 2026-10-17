"""Test server Web UI bằng ``TestClient`` (cần extra ``web``) — AC3–AC5, AC10, AC11."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

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


@unittest.skipUnless(HAVE_WEB, "cần `pip install -e .[web]`")
class TestServerGlossary(unittest.TestCase):
    """WEB-2: editor glossary + draft + redub — AC1–AC9."""

    GOOD = "terms:\n  quantum mechanics: cơ học lượng tử\n"

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.manager = JobManager(self.ws, None, python="py", popen=lambda cmd, **kw: FakeProc(cmd))
        self.client = TestClient(create_app(self.ws, self.manager, allowed_hosts=("testserver",)))
        self.addCleanup(self.manager.stop)
        self.ep = self.ws / "v1__t"
        _episode(self.ep, "T")
        _w(self.ep / "metadata.json", json.dumps({"id": "v1", "title": "T", "duration_seconds": 61,
                                                  "original_url": VIDEO}))

    def put(self, content, base, **kw):
        return self.client.put("/api/episodes/v1__t/glossary",
                               content=json.dumps({"content": content, "base_sha256": base}), **kw)

    def test_get_state_and_page(self) -> None:
        st = self.client.get("/api/episodes/v1__t/glossary").json()
        self.assertEqual((st["exists"], st["stale"], st["has_transcript"], st["has_translation"]),
                         (False, False, True, True))
        page = self.client.get("/ep/v1__t/glossary")
        self.assertEqual(page.status_code, 200)
        self.assertIn("<textarea", page.text)
        self.assertIn("Tạo nháp bằng model", page.text)
        self.assertIn("/static/glossary.js", page.text)
        self.assertEqual(self.client.get("/static/glossary.js").status_code, 200)
        self.assertIn("glossary", self.client.get("/ep/v1__t").text)
        self.assertIn("<th>glossary</th>", self.client.get("/library").text)

    def test_put_ok_bad_conflict(self) -> None:
        r = self.put(self.GOOD, None)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["stale"])  # translated.json không có hash, glossary hiệu lực có
        self.assertEqual((self.ep / "glossary.yaml").read_text(encoding="utf-8"), self.GOOD)
        sha = r.json()["file_sha256"]
        before = (self.ep / "glossary.yaml").read_bytes()
        for bad in ("terms: [\n", "alias: x\n", "context: " + "a" * 300_000):
            r = self.put(bad, sha)
            self.assertEqual(r.status_code, 400, bad[:20])
            self.assertIn("error", r.json())
        self.assertEqual((self.ep / "glossary.yaml").read_bytes(), before)
        self.assertFalse((self.ep / "glossary.yaml.bak").exists())
        r = self.put("terms: {}\n", "sai")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["state"]["file_sha256"], sha)
        self.assertEqual((self.ep / "glossary.yaml").read_bytes(), before)
        self.assertEqual(self.client.put("/api/episodes/v1__t/glossary", content="không json").status_code, 400)
        self.assertEqual(self.client.put("/api/episodes/v1__t/glossary", content="{}").status_code, 400)

    def test_unknown_key_origin(self) -> None:
        for path in ("/ep/nope/glossary", "/api/episodes/nope/glossary", "/api/episodes/..%2F..%2Fx/glossary"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        for path in ("/api/episodes/nope/glossary/draft", "/api/episodes/nope/redub"):
            self.assertEqual(self.client.post(path).status_code, 404, path)
        self.assertEqual(self.put(self.GOOD, None, headers={"Origin": "http://evil.example"}).status_code, 403)
        for path in ("/api/episodes/v1__t/glossary/draft", "/api/episodes/v1__t/redub"):
            r = self.client.post(path, headers={"Origin": "http://evil.example"})
            self.assertEqual(r.status_code, 403, path)
        self.assertFalse((self.ep / "glossary.yaml").exists())
        self.assertEqual(self.manager.list(), [])

    def test_draft_job(self) -> None:
        r = self.client.post("/api/episodes/v1__t/glossary/draft")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["kind"], "glossary")
        self.assertEqual(r.json()["command"][3:5], ["glossary", str(self.ep)])
        jobs = self.client.get("/jobs")
        self.assertIn("glossary: v1__t", jobs.text)
        self.assertEqual(self.client.get(f"/jobs/{r.json()['id']}").status_code, 200)
        (self.ep / "glossary.yaml").write_text(self.GOOD, encoding="utf-8")
        self.assertEqual(self.client.post("/api/episodes/v1__t/glossary/draft").status_code, 400)
        (self.ep / "glossary.yaml").unlink()
        (self.ep / "transcript.json").unlink()
        self.assertEqual(self.client.post("/api/episodes/v1__t/glossary/draft").status_code, 400)
        self.assertNotIn("Tạo nháp", self.client.get("/ep/v1__t/glossary").text)

    def test_redub_single_and_playlist(self) -> None:
        r = self.client.post("/api/episodes/v1__t/redub")
        self.assertEqual(r.status_code, 201)
        cmd = r.json()["command"]
        self.assertEqual(cmd[3:5], ["dub", VIDEO])
        self.assertNotIn("--force", cmd)
        self.assertNotIn("--source-lang", cmd)
        pl = self.ws / "PL__x"
        _w(pl / "playlist.json", json.dumps({"url": "https://www.youtube.com/playlist?list=PLx", "entries": [
            {"index": 4, "title": "x", "episode_dir": "b__B"}]}))
        _episode(pl / "b__B", "B")
        r = self.client.post("/api/episodes/PL__x~b__B/redub")
        self.assertEqual(r.status_code, 201)
        cmd = r.json()["command"]
        self.assertEqual(cmd[3:5], ["playlist", "https://www.youtube.com/playlist?list=PLx"])
        self.assertEqual(cmd[-3:], ["--items", "4", "--recheck"])
        _w(self.ep / "metadata.json", "{}")
        self.assertEqual(self.client.post("/api/episodes/v1__t/redub").status_code, 400)

    def test_api_jobs_glossary_kind(self) -> None:
        post = lambda body: self.client.post("/api/jobs", content=json.dumps(body))  # noqa: E731
        self.assertEqual(post({"kind": "glossary", "episode_key": "v1__t"}).status_code, 201)
        self.assertEqual(post({"kind": "glossary"}).status_code, 400)
        self.assertEqual(post({"kind": "glossary", "episode_key": "zzz"}).status_code, 400)
        self.assertEqual(post({"kind": "glossary", "episode_key": "v1__t", "force": True}).status_code, 400)
        self.assertEqual(post({"kind": "glossary", "episode_key": "v1__t", "url": VIDEO}).status_code, 400)
        self.assertEqual(post({"kind": "dub", "url": VIDEO, "recheck": True}).status_code, 400)
        self.assertEqual(post({"kind": "playlist", "url": "https://www.youtube.com/playlist?list=P",
                               "recheck": True}).status_code, 201)

    def test_content_escaped_and_broken_file_opens(self) -> None:
        (self.ep / "glossary.yaml").write_text("context: </textarea><script>alert(1)</script>\n[", encoding="utf-8")
        page = self.client.get("/ep/v1__t/glossary")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("<script>alert", page.text)
        self.assertIn("&lt;/textarea&gt;&lt;script&gt;", page.text)
        st = self.client.get("/api/episodes/v1__t/glossary").json()
        self.assertTrue(st["error"])
        self.assertEqual(self.put(self.GOOD, st["file_sha256"]).status_code, 200)

    def test_shared_glossary_shown(self) -> None:
        shared = self.ws / "shared.yaml"
        shared.write_text("terms:\n  a: b\n", encoding="utf-8")
        client = TestClient(create_app(self.ws, self.manager, allowed_hosts=("testserver",),
                                       shared_glossary=shared))
        st = client.get("/api/episodes/v1__t/glossary").json()
        self.assertEqual(st["shared_path"], str(shared))
        self.assertTrue(st["stale"])
        self.assertIn(str(shared), client.get("/ep/v1__t/glossary").text)

    def test_only_expected_files_written(self) -> None:
        before = {p.relative_to(self.ws).as_posix() for p in self.ws.rglob("*")}
        self.put(self.GOOD, None)
        sha = self.client.get("/api/episodes/v1__t/glossary").json()["file_sha256"]
        self.put(self.GOOD + "# c\n", sha)
        after = {p.relative_to(self.ws).as_posix() for p in self.ws.rglob("*")}
        self.assertEqual(after - before, {"v1__t/glossary.yaml", "v1__t/glossary.yaml.bak"})


@unittest.skipUnless(HAVE_WEB, "cần `pip install -e .[web]`")
class TestServerAuth(unittest.TestCase):
    """WEB-AUTH: create_app(..., password=...) — AC3–AC9."""

    PW = "mật-khẩu-thử"
    HTML = {"Accept": "text/html"}

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.manager = JobManager(self.ws, None, python="py", popen=lambda cmd, **kw: FakeProc(cmd))
        self.addCleanup(self.manager.stop)
        _episode(self.ws / "v1__t", "T")
        self.client = self.make_client()

    def make_client(self, password: str | None = None) -> "TestClient":
        app = create_app(self.ws, self.manager, allowed_hosts=("testserver",), password=password or self.PW)
        return TestClient(app)

    def login(self, client: "TestClient", pw: str | None = None, nxt: str = "/library"):
        return client.post("/login", content=f"password={quote(pw or self.PW)}&next={quote(nxt, safe='')}",
                           headers={"Content-Type": "application/x-www-form-urlencoded"},
                           follow_redirects=False)

    def test_no_password_has_no_login_routes(self) -> None:
        plain = TestClient(create_app(self.ws, self.manager, allowed_hosts=("testserver",)))
        self.assertEqual(plain.get("/login").status_code, 404)
        self.assertEqual(plain.post("/logout").status_code, 404)
        self.assertEqual(plain.get("/library").status_code, 200)
        self.assertNotIn("Đăng xuất", plain.get("/library").text)
        empty = TestClient(create_app(self.ws, self.manager, allowed_hosts=("testserver",), password=""))
        self.assertEqual(empty.get("/library").status_code, 200)

    def test_unauthenticated(self) -> None:
        r = self.client.get("/library?x=1", headers=self.HTML, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/login?next=%2Flibrary%3Fx%3D1"))
        for method, path in (("put", "/api/episodes/v1__t/glossary"), ("get", "/api/episodes/v1__t/glossary"),
                             ("post", "/api/episodes/v1__t/redub"), ("post", "/api/episodes/v1__t/glossary/draft"),
                             ("get", "/ep/v1__t/glossary"), ("get", "/api/jobs"), ("get", "/media/v1__t/output"),
                             ("get", "/api/jobs/x/events"), ("post", "/api/jobs"), ("get", "/library")):
            r = getattr(self.client, method)(path, follow_redirects=False)
            self.assertEqual(r.status_code, 401, path)
            self.assertEqual(r.json(), {"detail": "Cần đăng nhập."})
        self.assertEqual(self.client.get("/static/app.css").status_code, 200)
        self.assertEqual(self.client.get("/login").status_code, 200)

    def test_host_checked_before_auth(self) -> None:
        r = self.client.get("/api/jobs", headers={"Host": "evil.example"})
        self.assertEqual(r.status_code, 400)

    def test_login_page_content(self) -> None:
        r = self.client.get("/login?next=/ep/v1__t")
        self.assertIn('type="password"', r.text)
        self.assertIn('name="next" value="/ep/v1__t"', r.text)
        self.assertNotIn(self.PW, r.text)

    def test_login_ok_cookie_and_access(self) -> None:
        r = self.login(self.client)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/library"))
        cookie = r.headers["set-cookie"].lower()
        for part in ("dubber_session=", "max-age=2592000", "path=/", "httponly", "samesite=strict"):
            self.assertIn(part, cookie)
        self.assertNotIn("secure", cookie)
        self.assertNotIn(self.PW.lower(), cookie)
        self.assertEqual(self.client.get("/library").status_code, 200)
        self.assertIn("Đăng xuất", self.client.get("/library").text)
        self.assertEqual(self.client.get("/api/jobs").status_code, 200)
        r = self.client.get("/media/v1__t/output", headers={"Range": "bytes=0-1023"})
        self.assertEqual((r.status_code, len(r.content)), (206, 1024))
        job = self.client.post("/api/jobs", json={"kind": "dub", "url": VIDEO}).json()
        # SSE: job lạ -> 404 (đã qua auth; chưa đăng nhập là 401). Stream thật kiểm ở "Chạy thật".
        self.assertEqual(self.client.get("/api/jobs/khong-co/events").status_code, 404)
        self.assertNotIn(self.PW, json.dumps(job))
        # đã đăng nhập thì /login đẩy về next
        r = self.client.get("/login?next=/jobs", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/jobs"))

    def test_open_redirect_blocked(self) -> None:
        for bad in ("//evil.example", "https://evil.example"):
            c = self.make_client()
            r = self.login(c, nxt=bad)
            self.assertEqual((r.status_code, r.headers["location"]), (303, "/"), bad)

    def test_wrong_password_then_throttle(self) -> None:
        for _ in range(5):
            r = self.login(self.client, "sai")
            self.assertEqual(r.status_code, 401)
            self.assertIn("Sai mật khẩu", r.text)
        r = self.login(self.client)  # đúng nhưng đã bị khoá
        self.assertEqual(r.status_code, 429)
        self.assertIn("thử lại sau", r.text)
        self.assertEqual(self.client.get("/api/jobs").status_code, 401)

    def test_success_resets_counter(self) -> None:
        for _ in range(4):
            self.login(self.client, "sai")
        self.assertEqual(self.login(self.client).status_code, 303)
        for _ in range(4):
            self.assertEqual(self.login(self.client, "sai").status_code, 401)

    def test_invalid_cookies(self) -> None:
        from app.web import auth

        good = auth.make_session(self.PW)
        bad_sig = good[:-1] + ("0" if good[-1] != "0" else "1")
        expired = auth.make_session(self.PW, now=1000)
        other_pw = auth.make_session("mật khẩu cũ")
        for cookie in (bad_sig, expired, other_pw, "rac"):
            c = self.make_client()
            c.cookies.set(auth.COOKIE_NAME, cookie)
            self.assertEqual(c.get("/api/jobs").status_code, 401, cookie)
        c = self.make_client()
        c.cookies.set(auth.COOKIE_NAME, good)
        self.assertEqual(c.get("/api/jobs").status_code, 200)

    def test_logout_and_origin(self) -> None:
        self.login(self.client)
        evil = {"Origin": "http://evil.example"}
        self.assertEqual(self.client.post("/logout", headers=evil).status_code, 403)
        self.assertEqual(self.client.get("/api/jobs").status_code, 200)
        r = self.client.post("/logout", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/login"))
        self.assertIn("max-age=0", r.headers["set-cookie"].lower())
        self.assertEqual(self.client.get("/api/jobs").status_code, 401)
        r = self.client.post("/login", content=f"password={quote(self.PW)}", headers={
            **evil, "Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
