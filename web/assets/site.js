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

  function isHomePage() {
    var path = window.location.pathname || "/";
    return path === "/" || path === "/index.html" || path.endsWith("/index.html");
  }

  function goHome(e) {
    if (!isHomePage()) return;
    e.preventDefault();
    if (window.location.hash) {
      history.replaceState(null, "", window.location.pathname);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function goFeatures(e) {
    if (!isHomePage()) return;
    e.preventDefault();
    var target = document.getElementById("features");
    if (window.location.hash !== "#features") {
      history.replaceState(null, "", "/#features");
    }
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function bindHomeLink(anchor) {
    anchor.addEventListener("click", goHome);
  }

  function renderNav() {
    var el = document.getElementById("site-nav");
    if (!el) return;
    var active = el.getAttribute("data-active") || "";
    var logo = document.createElement("a");
    logo.href = "/";
    logo.className = "nav-logo";
    var logoImg = document.createElement("img");
    logoImg.src = "/assets/logo.png";
    logoImg.alt = "";
    logoImg.className = "nav-logo-img";
    logoImg.width = 32;
    logoImg.height = 32;
    logo.appendChild(logoImg);
    var logoText = document.createElement("span");
    logoText.textContent = "Obsidian Overseer";
    logo.appendChild(logoText);
    bindHomeLink(logo);
    var links = document.createElement("div");
    links.className = "nav-links";
    NAV_ITEMS.forEach(function (item) {
      var a = document.createElement("a");
      a.href = item.href;
      a.textContent = item.label;
      if (item.id === active) a.className = "active";
      if (item.id === "home") bindHomeLink(a);
      if (item.id === "features") a.addEventListener("click", goFeatures);
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
    if (!/^https?:\/\//i.test(base)) base = "https://" + base;
    return base + (path.startsWith("/") ? path : "/" + path);
  }

  function formatCount(n) {
    if (n == null || isNaN(n)) return "—";
    return Number(n).toLocaleString("en-US");
  }

  function loadPublicBotStats(options) {
    options = options || {};
    var serversEl = options.serversEl;
    var usersEl = options.usersEl;
    var wrapEl = options.wrapEl;
    var url = apiUrl("/api/health");
    if (!url || !serversEl || !usersEl) return Promise.resolve(null);

    if (wrapEl) wrapEl.classList.add("loading");

    return fetch(url)
      .then(function (res) {
        return res.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        if (data.guild_count != null) serversEl.textContent = formatCount(data.guild_count);
        if (data.user_count != null) usersEl.textContent = formatCount(data.user_count);
        if (wrapEl) wrapEl.classList.remove("loading");
        return data;
      })
      .catch(function () {
        serversEl.textContent = "—";
        usersEl.textContent = "—";
        if (wrapEl) wrapEl.classList.remove("loading");
        return null;
      });
  }

  window.ObsidianSite = {
    renderNav: renderNav,
    apiUrl: apiUrl,
    loadPublicBotStats: loadPublicBotStats,
    formatCount: formatCount,
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
