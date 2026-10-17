// Form nhập URL: gửi JSON tới /api/jobs rồi chuyển sang trang job.
(function () {
  const form = document.getElementById("job-form");
  const err = document.getElementById("form-error");
  const kind = form.elements["kind"];

  function syncKind() {
    // items/--download-only chỉ có nghĩa với playlist.
    const isPl = kind.value === "playlist";
    form.querySelectorAll(".pl-only").forEach((el) => (el.style.display = isPl ? "" : "none"));
  }
  kind.addEventListener("change", syncKind);
  // Dán URL có list= thì tự chọn playlist.
  form.elements["url"].addEventListener("input", (e) => {
    try {
      const u = new URL(e.target.value);
      kind.value = u.searchParams.get("list") && !u.searchParams.get("v") ? "playlist" : "dub";
      syncKind();
    } catch (_) {}
  });
  syncKind();

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    const f = form.elements;
    const body = {
      kind: f["kind"].value,
      url: f["url"].value.trim(),
      source_lang: f["source_lang"].value.trim() || null,
      items: f["items"].value.trim() || null,
      force: f["force"].checked,
      download_only: f["download_only"].checked,
    };
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      err.textContent = data.error || data.detail || "Lỗi " + res.status;
      return;
    }
    location.href = "/jobs/" + data.id;
  });
})();
