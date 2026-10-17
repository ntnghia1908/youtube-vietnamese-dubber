// Trang episode: click câu -> tua, highlight câu đang phát, đổi output/source giữ thời điểm,
// lọc too_long, chọn kiểu phụ đề (song ngữ/Việt/gốc), ẩn/hiện khung phụ đề.
(function () {
  const video = document.getElementById("video");
  const rows = Array.from(document.querySelectorAll("#segments [data-start]"));
  const filter = document.getElementById("only-too-long");
  const box = document.getElementById("segments-box");
  const autoScroll = document.getElementById("auto-scroll");
  const layout = document.querySelector(".episode-layout");
  const togglePane = document.getElementById("toggle-pane");
  const modeButtons = Array.from(document.querySelectorAll(".seg-mode [data-mode]"));
  // Tuỳ chọn hiển thị theo trình duyệt; storage có thể bị chặn (private mode).
  const load = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const save = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };

  // Kiểu phụ đề: song ngữ / chỉ tiếng Việt / chỉ bản gốc (CSS ẩn dòng theo data-mode).
  function setMode(mode) {
    box.dataset.mode = mode;
    modeButtons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === mode)));
    save("dubber.subMode", mode);
  }
  modeButtons.forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  const savedMode = load("dubber.subMode");
  if (modeButtons.some((b) => b.dataset.mode === savedMode)) setMode(savedMode);

  // Ẩn/hiện cả khung phụ đề; ẩn thì video chiếm hết chiều ngang.
  function setPane(shown) {
    layout.classList.toggle("pane-hidden", !shown);
    if (togglePane) {
      togglePane.textContent = shown ? "Ẩn phụ đề" : "Hiện phụ đề";
      togglePane.setAttribute("aria-expanded", String(shown));
    }
    save("dubber.paneShown", shown ? "1" : "0");
  }
  if (togglePane) togglePane.addEventListener("click", () => setPane(layout.classList.contains("pane-hidden")));
  if (load("dubber.paneShown") === "0") setPane(false);

  if (load("dubber.autoScroll") === "0") autoScroll.checked = false;
  autoScroll.addEventListener("change", () => save("dubber.autoScroll", autoScroll.checked ? "1" : "0"));

  filter.addEventListener("change", () => {
    rows.forEach((r) => (r.hidden = filter.checked && r.dataset.status !== "too_long"));
  });

  // Tải video lồng tiếng: trình duyệt tự tải qua link; ở đây chỉ cập nhật dấu ✓ tại chỗ.
  const dlBox = document.getElementById("download-box");
  if (dlBox) {
    const dlStatus = document.getElementById("download-status");
    const dlClear = document.getElementById("download-clear");
    const dlError = document.getElementById("download-error");
    // "HH:MM dd/mm/yyyy" theo giờ trình duyệt, tự đệm 2 chữ số (không phụ thuộc locale).
    const p2 = (n) => String(n).padStart(2, "0");
    const fmt = (d) => p2(d.getHours()) + ":" + p2(d.getMinutes()) + " " + p2(d.getDate()) + "/" + p2(d.getMonth() + 1) + "/" + d.getFullYear();
    dlStatus.querySelectorAll("time[datetime]").forEach((t) => {
      const d = new Date(t.getAttribute("datetime"));
      if (!isNaN(d)) t.textContent = fmt(d);
    });
    const showMark = (on, at) => {
      dlStatus.hidden = !on;
      dlClear.hidden = !on;
      if (on) dlStatus.textContent = "✓ Đã tải" + (at ? " lúc " + fmt(at) : "");
    };
    document.getElementById("download-link").addEventListener("click", () => {
      dlError.textContent = "";
      showMark(true, new Date());
    });
    dlClear.addEventListener("click", async () => {
      dlError.textContent = "";
      try {
        const r = await fetch("/api/episodes/" + encodeURIComponent(dlBox.dataset.key) + "/downloaded", { method: "DELETE" });
        if (!r.ok) throw new Error("HTTP " + r.status);
        showMark(false);
      } catch (e) {
        dlError.textContent = "Không bỏ đánh dấu được: " + e.message;
      }
    });
  }
  if (!video) return;

  // Mobile: player dính đầu màn hình (app.css) — báo chiều cao cho CSS để
  // scrollIntoView không đẩy câu đang phát xuống dưới video.
  const player = video.closest(".player");
  const syncPlayerHeight = () =>
    document.documentElement.style.setProperty("--player-h", player.offsetHeight + "px");
  syncPlayerHeight();
  window.addEventListener("resize", syncPlayerHeight);
  video.addEventListener("loadedmetadata", syncPlayerHeight);

  rows.forEach((r) =>
    r.addEventListener("click", () => {
      video.currentTime = parseFloat(r.dataset.start);
      video.play();
    })
  );

  let active = null;
  video.addEventListener("timeupdate", () => {
    const t = video.currentTime;
    const cur = rows.find((r) => t >= parseFloat(r.dataset.start) && t < parseFloat(r.dataset.end));
    if (cur === active) return;
    if (active) active.classList.remove("active");
    active = cur || null;
    if (active) {
      active.classList.add("active");
      if (!active.hidden && autoScroll.checked && !layout.classList.contains("pane-hidden")) reveal(active);
    }
  });

  // Desktop: khung câu tự cuộn (overflow) -> chỉ cuộn khung, không đụng tới trang.
  // Mobile: khung không cuộn riêng, video sticky -> scrollIntoView trên trang như cũ.
  function reveal(row) {
    if (box.scrollHeight <= box.clientHeight) {
      row.scrollIntoView({ block: "nearest" });
      return;
    }
    const top = row.offsetTop;
    const bottom = row.offsetTop + row.offsetHeight;
    if (top < box.scrollTop || bottom > box.scrollTop + box.clientHeight) {
      box.scrollTop = Math.max(0, top - box.clientHeight / 3);
    }
  }

  function switchTo(src) {
    if (!src || video.getAttribute("src") === src) return;
    const t = video.currentTime;
    const wasPlaying = !video.paused;
    video.addEventListener(
      "loadedmetadata",
      () => {
        video.currentTime = t;
        if (wasPlaying) video.play();
      },
      { once: true }
    );
    video.src = src;
  }
  document.getElementById("use-output").addEventListener("click", () => switchTo(video.dataset.output));
  document.getElementById("use-source").addEventListener("click", () => switchTo(video.dataset.source));
})();
