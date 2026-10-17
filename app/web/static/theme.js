// Theme sáng/tối: nạp trong <head> (không defer) để đặt data-theme trước khi vẽ,
// tránh nháy trắng. Chưa chọn thì theo hệ thống; nút trong nav ghi đè và nhớ lại.
(function () {
  const root = document.documentElement;
  const query = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const stored = () => { try { return localStorage.getItem("dubber.theme"); } catch (e) { return null; } };
  const system = () => (query && query.matches ? "dark" : "light");
  const apply = (theme) => { root.dataset.theme = theme; };
  apply(stored() || system());
  if (query && query.addEventListener) {
    query.addEventListener("change", () => { if (!stored()) apply(system()); });
  }

  document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("theme-toggle");
    if (!button) return;
    const label = () => {
      const dark = root.dataset.theme === "dark";
      button.textContent = dark ? "☀ Sáng" : "☾ Tối";
      button.setAttribute("aria-label", dark ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối");
    };
    label();
    button.addEventListener("click", () => {
      const next = root.dataset.theme === "dark" ? "light" : "dark";
      apply(next);
      try { localStorage.setItem("dubber.theme", next); } catch (e) {}
      label();
    });
  });
})();
