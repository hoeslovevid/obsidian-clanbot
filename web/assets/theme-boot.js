/**
 * Apply saved / preferred color theme before paint (include in <head> before CSS).
 */
(function () {
  try {
    var key = "oo_theme";
    var saved = localStorage.getItem(key);
    var theme =
      saved === "light" || saved === "dark"
        ? saved
        : window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches
          ? "light"
          : "dark";
    document.documentElement.setAttribute("data-theme", theme);
  } catch (_) {
    document.documentElement.setAttribute("data-theme", "dark");
  }
})();
