// Trang job: log trực tiếp qua SSE, cập nhật trạng thái/tiến độ, nút Hủy / Chạy lại.
(function () {
  const root = document.getElementById("job");
  const id = root.dataset.jobId;
  const logEl = document.getElementById("log");
  const statusEl = document.getElementById("status");
  const progressEl = document.getElementById("progress");
  const exitEl = document.getElementById("exit-code");
  const errEl = document.getElementById("action-error");
  const TERMINAL = ["completed", "failed", "cancelled", "interrupted"];

  function fmtProgress(p) {
    if (!p) return "";
    return (p.episode ? p.episode + " " : "") + p.index + "/" + p.total + " " + p.stage + " (" + p.state + ")";
  }

  const es = new EventSource("/api/jobs/" + id + "/events");
  es.addEventListener("log", (e) => {
    const stick = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 20;
    logEl.textContent += JSON.parse(e.data) + "\n";
    if (stick) logEl.scrollTop = logEl.scrollHeight;
  });
  es.addEventListener("status", (e) => {
    const s = JSON.parse(e.data);
    statusEl.textContent = s.status;
    statusEl.className = "badge st-" + s.status;
    progressEl.textContent = fmtProgress(s.progress);
    exitEl.textContent = s.exit_code === null ? "—" : s.exit_code;
    root.dataset.status = s.status;
    // Đóng khi xong: không thì EventSource tự nối lại vô hạn.
    if (TERMINAL.includes(s.status)) setTimeout(() => es.close(), 1000);
  });

  async function post(path) {
    errEl.textContent = "";
    const res = await fetch(path, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      errEl.textContent = data.error || data.detail || "Lỗi " + res.status;
      return null;
    }
    return data;
  }
  document.getElementById("cancel").addEventListener("click", () => post("/api/jobs/" + id + "/cancel"));
  document.getElementById("retry").addEventListener("click", async () => {
    const job = await post("/api/jobs/" + id + "/retry");
    if (job) location.href = "/jobs/" + job.id;
  });
})();
