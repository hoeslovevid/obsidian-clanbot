/**
 * Shared navigation, footer, and URL helpers for obsidianoverseer.com
 */
(function () {
  var NAV_ITEMS = [
    { id: "home", label: "Home", href: "/" },
    { id: "features", label: "Features", href: "/#features" },
    { id: "setup", label: "Setup", href: "/setup.html" },
    { id: "dashboard", label: "Dashboard", href: "/dashboard.html" },
    { id: "faq", label: "FAQ", href: "/faq.html" },
    { id: "contact", label: "Contact", href: "/contact.html" },
  ];

  function cfg() {
    return window.OBSIDIAN_SITE || {};
  }

  function dashboardUrl() {
    try {
      var c = cfg();
      var override = (c.DASHBOARD_PUBLIC_URL || "").replace(/\/$/, "");
      if (override) {
        if (!/^https?:\/\//i.test(override)) override = "https://" + override;
        return /dashboard\.html$/i.test(override) ? override : override + "/dashboard.html";
      }
      var api = (c.BOT_API_URL || "").replace(/\/$/, "");
      if (!api) return "/dashboard.html";
      if (!/^https?:\/\//i.test(api)) api = "https://" + api;
      return api + "/dashboard.html";
    } catch (_) {
      return "/dashboard.html";
    }
  }

  function inviteUrl() {
    var c = cfg();
    var clientId = c.DISCORD_CLIENT_ID || "";
    if (!clientId || clientId === "YOUR_BOT_CLIENT_ID") return "#";
    var permissions = c.DISCORD_PERMISSIONS || "277025508160";
    var scope = encodeURIComponent(c.DISCORD_SCOPE || "bot applications.commands");
    return (
      "https://discord.com/api/oauth2/authorize?client_id=" +
      encodeURIComponent(clientId) +
      "&permissions=" +
      encodeURIComponent(permissions) +
      "&scope=" +
      scope
    );
  }

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
    closeMobileNav();
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
    closeMobileNav();
  }

  function siteOrigin() {
    try {
      var apiBase = (cfg().BOT_API_URL || "").replace(/\/$/, "");
      if (apiBase && typeof window !== "undefined" && window.location) {
        var apiHost = new URL(apiBase).host;
        if (window.location.host === apiHost) {
          return "https://obsidianoverseer.com";
        }
      }
    } catch (_) {}
    return "";
  }

  function resolveHref(item, origin) {
    if (item.id === "dashboard") {
      return origin ? "/dashboard.html" : dashboardUrl();
    }
    var href = item.href;
    if (origin && href.charAt(0) === "/") {
      return origin + href;
    }
    return href;
  }

  function closeMobileNav() {
    var el = document.getElementById("site-nav");
    if (el) el.classList.remove("open");
    var btn = el && el.querySelector(".site-nav-toggle");
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function renderNav() {
    var el = document.getElementById("site-nav");
    if (!el) return;
    var active = el.getAttribute("data-active") || "";
    var origin = siteOrigin();

    el.className = (el.className || "").replace(/\bsite-nav\b/g, "").trim();
    el.classList.add("site-nav");

    var logo = document.createElement("a");
    logo.href = origin ? origin + "/" : "/";
    logo.className = "site-nav-brand";
    var logoImg = document.createElement("img");
    logoImg.src = (origin || "") + "/assets/logo.png";
    logoImg.alt = "";
    logoImg.width = 32;
    logoImg.height = 32;
    logo.appendChild(logoImg);
    var logoText = document.createElement("span");
    logoText.textContent = "Obsidian Overseer";
    logo.appendChild(logoText);
    if (!origin) logo.addEventListener("click", goHome);

    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "site-nav-toggle";
    toggle.setAttribute("aria-label", "Menu");
    toggle.setAttribute("aria-expanded", "false");
    toggle.innerHTML =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>';
    toggle.addEventListener("click", function () {
      var open = !el.classList.contains("open");
      el.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });

    var links = document.createElement("div");
    links.className = "site-nav-links";
    NAV_ITEMS.forEach(function (item) {
      var a = document.createElement("a");
      a.href = resolveHref(item, origin);
      a.textContent = item.label;
      if (item.id === active) a.className = "active";
      if (!origin && item.id === "home") a.addEventListener("click", goHome);
      if (!origin && item.id === "features") a.addEventListener("click", goFeatures);
      a.addEventListener("click", closeMobileNav);
      links.appendChild(a);
    });

    var cta = document.createElement("a");
    cta.href = inviteUrl();
    cta.className = "site-nav-cta";
    cta.textContent = "Add to Discord";
    cta.target = "_blank";
    cta.rel = "noopener noreferrer";
    if (cta.href.endsWith("#") || cta.getAttribute("href") === "#") {
      cta.addEventListener("click", function (e) {
        e.preventDefault();
      });
    }
    links.appendChild(cta);

    el.innerHTML = "";
    el.appendChild(logo);
    el.appendChild(toggle);
    el.appendChild(links);
  }

  function renderFooter() {
    var el = document.getElementById("site-footer");
    if (!el) return;
    var origin = siteOrigin();
    var prefix = origin || "";
    var dash = origin ? "/dashboard.html" : dashboardUrl();
    var invite = inviteUrl();
    var discord = cfg().DISCORD_SERVER_INVITE || "https://discord.gg/bJscayQNK4";

    el.className = "site-footer";
    el.innerHTML =
      '<div class="site-footer-grid">' +
      '<div><div class="site-footer-brand">Obsidian Overseer<span>Warframe Discord bot for clans and communities.</span></div></div>' +
      "<div><h4>Product</h4>" +
      '<a href="' + prefix + '/">Home</a>' +
      '<a href="' + prefix + '/#features">Features</a>' +
      '<a href="' + dash + '">Dashboard</a>' +
      '<a href="' + invite + '" target="_blank" rel="noopener noreferrer">Add to Discord</a>' +
      "</div>" +
      "<div><h4>Guides</h4>" +
      '<a href="' + prefix + '/setup.html">Setup guide</a>' +
      '<a href="' + prefix + '/faq.html">FAQ</a>' +
      '<a href="' + prefix + '/changelog.html">Changelog</a>' +
      "</div>" +
      "<div><h4>Support</h4>" +
      '<a href="' + prefix + '/contact.html">Contact</a>' +
      '<a href="' + discord + '" target="_blank" rel="noopener noreferrer">Discord server</a>' +
      '<a href="' + prefix + '/legal.html#privacy">Privacy</a>' +
      '<a href="' + prefix + '/legal.html#terms">Terms</a>' +
      "</div>" +
      "</div>" +
      '<div class="site-footer-bottom">Not affiliated with Discord or Digital Extremes / Warframe. © Obsidian Overseer</div>';
  }

  function apiUrl(path) {
    var base = (cfg().BOT_API_URL || "").replace(/\/$/, "");
    if (!base) return null;
    if (!/^https?:\/\//i.test(base)) base = "https://" + base;
    try {
      if (typeof window !== "undefined" && window.location && window.location.origin) {
        var apiHost = new URL(base).host;
        if (window.location.host === apiHost) {
          return path.startsWith("/") ? path : "/" + path;
        }
      }
    } catch (_) {}
    return base + (path.startsWith("/") ? path : "/" + path);
  }

  function formatCount(n) {
    if (n == null || isNaN(n)) return "—";
    return Number(n).toLocaleString("en-US");
  }

  function statsFromConfig() {
    var s = cfg().BOT_STATS;
    if (!s || (s.guild_count == null && s.user_count == null)) return null;
    return s;
  }

  function applyPublicStats(data, options) {
    var serversEl = options.serversEl;
    var usersEl = options.usersEl;
    var wrapEl = options.wrapEl;
    if (!data) return false;
    var applied = false;
    if (serversEl && data.guild_count != null) {
      serversEl.textContent = formatCount(data.guild_count);
      applied = true;
    }
    if (usersEl && data.user_count != null) {
      usersEl.textContent = formatCount(data.user_count);
      applied = true;
    }
    if (wrapEl) wrapEl.classList.remove("loading");
    return applied;
  }

  function failPublicStats(options) {
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

  function setStatusEl(el, online, version) {
    if (!el) return;
    el.classList.remove("online", "offline");
    el.classList.add(online ? "online" : "offline");
    var label = online ? "Bot online" : "Status unavailable";
    if (online && version) label += " · v" + version;
    el.innerHTML = '<span class="site-status-dot" aria-hidden="true"></span>' + label;
  }

  function loadBotStatus(el) {
    if (!el) return Promise.resolve(null);
    var url = apiUrl("/api/ping");
    if (!url) {
      setStatusEl(el, false);
      return Promise.resolve(null);
    }
    return fetch(url + (url.indexOf("?") >= 0 ? "&" : "?") + "_=" + Date.now(), {
      cache: "no-store",
    })
      .then(function (res) {
        if (!res.ok) throw new Error("ping " + res.status);
        return res.json();
      })
      .then(function (data) {
        var version = data.version || data.bot_version || data.BOT_VERSION || null;
        var online = data.ok !== false && data.status !== "error";
        setStatusEl(el, online, version);
        return data;
      })
      .catch(function () {
        setStatusEl(el, false);
        return null;
      });
  }

  function initChrome() {
    renderNav();
    renderFooter();
  }

  window.ObsidianSite = {
    renderNav: renderNav,
    renderFooter: renderFooter,
    apiUrl: apiUrl,
    dashboardUrl: dashboardUrl,
    inviteUrl: inviteUrl,
    loadPublicBotStats: loadPublicBotStats,
    loadBotStatus: loadBotStatus,
    formatCount: formatCount,
    config: cfg,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initChrome);
  } else {
    initChrome();
  }
})();
