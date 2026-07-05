/**
 * Shared navigation and URL helpers for obsidianoverseer.com
 */
(function () {
  var NAV_ITEMS = [
    { id: "home", label: "Home", href: "/" },
    { id: "features", label: "Features", href: "/#features" },
    { id: "dashboard", label: "Dashboard", href: "/dashboard.html" },
    { id: "contact", label: "Contact", href: "/contact.html" },
    { id: "legal", label: "Legal", href: "/legal.html" },
  ];

  function renderNav() {
    var el = document.getElementById("site-nav");
    if (!el) return;
    var active = el.getAttribute("data-active") || "";
    var logo = document.createElement("a");
    logo.href = "/";
    logo.className = "nav-logo";
    logo.textContent = "Obsidian Overseer";
    var links = document.createElement("div");
    links.className = "nav-links";
    NAV_ITEMS.forEach(function (item) {
      var a = document.createElement("a");
      a.href = item.href;
      a.textContent = item.label;
      if (item.id === active) a.className = "active";
      links.appendChild(a);
    });
    el.innerHTML = "";
    el.appendChild(logo);
    el.appendChild(links);
  }

  function apiUrl(path) {
    var cfg = window.OBSIDIAN_SITE || {};
    var base = (cfg.BOT_API_URL || "").replace(/\/$/, "");
    if (!base) return null;
    return base + (path.startsWith("/") ? path : "/" + path);
  }

  window.ObsidianSite = {
    renderNav: renderNav,
    apiUrl: apiUrl,
    config: function () {
      return window.OBSIDIAN_SITE || {};
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderNav);
  } else {
    renderNav();
  }
})();
