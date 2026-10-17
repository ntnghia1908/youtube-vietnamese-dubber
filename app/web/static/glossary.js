// Editor glossary: Lưu (PUT, optimistic concurrency), Tạo nháp, Dịch lại & chạy tiếp.
(function () {
  const form = document.getElementById("glossary-form");
  const text = document.getElementById("glossary-text");
  const msg = document.getElementById("msg");
  const label = document.getElementById("stale-label");
  const api = form.dataset.api;
  const isPlaylist = form.dataset.mode === "playlist";
  let baseSha = form.dataset.sha || null;
  let saved = text.value;

  const show = (m) => { msg.textContent = m || ""; };
  const dirty = () => text.value !== saved;
  window.addEventListener("beforeunload", (e) => {
    if (dirty()) { e.preventDefault(); e.returnValue = ""; }
  });

  function showState(st) {
    if (isPlaylist) {
      label.textContent = st.stale_items.length
        ? st.stale_items.length + "/" + st.translated_items.length + " tập đã dịch bằng glossary cũ (tập " + st.stale_items.join(", ") + ")."
        : "Không có tập nào cần dịch lại.";
      document.getElementById("state-error").textContent = st.error || "";
      return;
    }
    label.textContent = st.stale === null
      ? "Chưa có bản dịch (hoặc glossary đang lỗi)."
      : st.stale ? "Bản dịch CŨ — cần dịch lại." : "Bản dịch khớp glossary.";
    document.getElementById("state-error").textContent = st.error || "";
  }

  async function post(url) {
    const r = await fetch(url, { method: "POST" });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { show(data.error || "Lỗi " + r.status); return; }
    window.location.href = "/jobs/" + data.id;
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    show("");
    const r = await fetch(api + "/glossary", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: text.value, base_sha256: baseSha }),
    });
    const data = await r.json().catch(() => ({}));
    if (r.ok) {
      baseSha = data.file_sha256;
      saved = text.value;  // giữ nguyên text đang gõ, chỉ cập nhật mốc
      showState(data);
      show("Đã lưu.");
    } else if (r.status === 409) {
      // Không ghi đè text đang gõ; người dùng tự chép ra rồi tải lại trang.
      show((data.error || "Xung đột.") + " Text của bạn vẫn còn trong ô soạn thảo — sao chép lại rồi tải lại trang.");
    } else {
      show(data.error || "Lỗi " + r.status);
    }
  });

  const draft = document.getElementById("draft");
  if (draft) draft.addEventListener("click", () => post(api + "/glossary/draft"));
  const redub = document.getElementById("redub");
  if (redub) redub.addEventListener("click", () => {
    if (dirty() && !confirm("Có thay đổi chưa lưu — vẫn dịch lại với glossary đã lưu?")) return;
    post(api + "/redub");
  });
})();
