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

  function statsFromConfig() {
    var cfg = window.OBSIDIAN_SITE || {};
    var s = cfg.BOT_STATS;
    if (!s || (s.guild_count == null && s.user_count == null)) return null;
    return s;
  }

  function applyPublicStats(data, options) {
    var serversEl = options.serversEl;
    var usersEl = options.usersEl;
    var wrapEl = options.wrapEl;
    if (!data) return false;
    var applied = false;
    if (serversEl) {
      if (data.guild_count != null) {
        serversEl.textContent = formatCount(data.guild_count);
        applied = true;
      }
    }
    if (usersEl) {
      if (data.user_count != null) {
        usersEl.textContent = formatCount(data.user_count);
        applied = true;
      }
    }
    if (wrapEl) wrapEl.classList.remove("loading");
    return applied;
  }

  function failPublicStats(options) {
    applyPublicStats({ guild_count: null, user_count: null }, options);
    if (options.serversEl) options.serversEl.textContent = "—";
    if (options.usersEl) options.usersEl.textContent = "—";
    if (options.wrapEl) options.wrapEl.classList.remove("loading");
  }

  function tryLiveBotStats(options) {
    var url = apiUrl("/api/stats") || apiUrl("/api/health");
    if (!url) return Promise.resolve(null);

    var cacheKey = "obsidian_bot_stats_v1";
    try {
      var cached = sessionStorage.getItem(cacheKey);
      if (cached) {
        var parsed = JSON.parse(cached);
        if (parsed && parsed.data && parsed.expires > Date.now()) {
          applyPublicStats(parsed.data, options);
          return Promise.resolve(parsed.data);
        }
      }
    } catch (_) {}

    return fetch(url)
      .then(function (res) {
        if (!res.ok) throw new Error("stats HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        if (!applyPublicStats(data, options)) throw new Error("stats empty");
        try {
          sessionStorage.setItem(
            cacheKey,
            JSON.stringify({ data: data, expires: Date.now() + 5 * 60 * 1000 })
          );
        } catch (_) {}
        return data;
      });
  }

  function loadPublicBotStats(options) {
    options = options || {};
    if (!options.serversEl || !options.usersEl) return Promise.resolve(null);
    if (options.wrapEl) options.wrapEl.classList.add("loading");

    var fromConfig = statsFromConfig();
    if (fromConfig && applyPublicStats(fromConfig, options)) {
      return Promise.resolve(fromConfig);
    }

    return fetch("/assets/bot-stats.json", { cache: "no-cache" })
      .then(function (res) {
        if (!res.ok) throw new Error("static stats missing");
        return res.json();
      })
      .then(function (data) {
        if (applyPublicStats(data, options)) return data;
        return tryLiveBotStats(options);
      })
      .catch(function () {
        return tryLiveBotStats(options);
      })
      .catch(function () {
        failPublicStats(options);
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
