// Trang episode: click câu -> tua, highlight câu đang phát, đổi output/source giữ thời điểm, lọc too_long.
(function () {
  const video = document.getElementById("video");
  const rows = Array.from(document.querySelectorAll("#segments tr[data-start]"));
  const filter = document.getElementById("only-too-long");
  const box = document.getElementById("segments-box");
  const autoScroll = document.getElementById("auto-scroll");
  // Nhớ lựa chọn tự cuộn theo trình duyệt; storage có thể bị chặn (private mode).
  try {
    if (localStorage.getItem("dubber.autoScroll") === "0") autoScroll.checked = false;
  } catch (e) {}
  autoScroll.addEventListener("change", () => {
    try { localStorage.setItem("dubber.autoScroll", autoScroll.checked ? "1" : "0"); } catch (e) {}
  });

  filter.addEventListener("change", () => {
    rows.forEach((r) => (r.hidden = filter.checked && r.dataset.status !== "too_long"));
  });
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
      if (!active.hidden && autoScroll.checked) reveal(active);
    }
  });

  // Desktop: khung câu tự cuộn (overflow) -> chỉ cuộn khung, không đụng tới trang.
  // Mobile: khung không cuộn riêng, video sticky -> scrollIntoView trên trang như cũ.
  function reveal(row) {
    if (box.scrollHeight <= box.clientHeight) {
      row.scrollIntoView({ block: "nearest" });
      return;
    }
    const head = box.querySelector("thead");
    const top = row.offsetTop - (head ? head.offsetHeight : 0);
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
