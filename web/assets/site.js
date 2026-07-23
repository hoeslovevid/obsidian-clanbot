/**
 * Shared navigation, footer, and URL helpers for obsidianoverseer.com
 */
(function () {
  var NAV_DASHBOARD = { id: "dashboard", label: "Dashboard", href: "/dashboard.html" };

  // Grouped Tools menu — keep the top bar to: Logo · Tools · Guides · Dashboard · theme · CTA
  var NAV_TOOLS = [
    { section: "Live" },
    { id: "warframe", label: "World state", href: "/warframe.html" },
    { id: "nightwave", label: "Nightwave", href: "/nightwave.html" },
    { id: "baro", label: "Baro list", href: "/baro.html" },
    { id: "circuit", label: "Steel Path", href: "/circuit.html" },
    { id: "farm", label: "Acquire", href: "/farm.html" },
    { id: "market", label: "Market", href: "/market.html" },
    { id: "relics", label: "Relics", href: "/relics.html" },
    { id: "planner", label: "Relic planner", href: "/planner.html" },
    { id: "vault", label: "Prime vault", href: "/vault.html" },
    { id: "worth", label: "Ducat / plat", href: "/worth.html" },
    { section: "Lookup" },
    { id: "rivens", label: "Riven disposition", href: "/rivens.html" },
    { id: "compare", label: "Compare items", href: "/compare.html" },
    { id: "factions", label: "Factions", href: "/factions.html" },
    { id: "incarnon", label: "Incarnon", href: "/incarnon.html" },
    { id: "shards", label: "Archon shards", href: "/shards.html" },
    { id: "builds", label: "Builds", href: "/builds.html" },
    { section: "Bot" },
    { id: "status", label: "Bot status", href: "/status.html" },
    { id: "embeds", label: "Embeds / OBS", href: "/embeds.html" },
    { id: "features", label: "All features", href: "/#features" },
  ];

  var NAV_GUIDES = [
    { section: "Getting started" },
    { id: "tenno", label: "First week", href: "/tenno.html" },
    { id: "setup", label: "Bot setup", href: "/setup.html" },
    { id: "commands", label: "Commands", href: "/commands.html" },
    { section: "Clan" },
    { id: "dojo", label: "Dojo ops", href: "/dojo.html" },
    { id: "trading", label: "Trading", href: "/trading.html" },
    { id: "lfg", label: "LFG", href: "/lfg.html" },
    { id: "events", label: "Events", href: "/events.html" },
    { section: "Help" },
    { id: "faq", label: "FAQ", href: "/faq.html" },
    { id: "changelog", label: "Changelog", href: "/changelog.html" },
    { id: "privacy", label: "Privacy", href: "/privacy.html" },
  ];

  var TOOL_IDS = {
    warframe: 1, farm: 1, relics: 1, vault: 1, compare: 1, rivens: 1,
    factions: 1, builds: 1, market: 1, embeds: 1, status: 1, features: 1,
    nightwave: 1, baro: 1, circuit: 1, planner: 1, worth: 1, incarnon: 1, shards: 1,
  };
  var GUIDE_IDS = {
    tenno: 1, dojo: 1, trading: 1, commands: 1, lfg: 1, events: 1,
    setup: 1, faq: 1, changelog: 1, privacy: 1,
  };
  var THEME_KEY = "oo_theme";
  // Show "New" chips on home / jump menu until this date (ISO)
  var NEW_UNTIL = {
    nightwave: "2026-08-20",
    baro: "2026-08-20",
    circuit: "2026-08-20",
    planner: "2026-08-20",
    worth: "2026-08-20",
    incarnon: "2026-08-20",
    shards: "2026-08-20",
  };

  function isNewTool(id) {
    var until = NEW_UNTIL[id];
    if (!until) return false;
    return Date.now() < new Date(until + "T23:59:59Z").getTime();
  }

  function routeToolSearch(q) {
    var s = String(q || "").trim().toLowerCase();
    if (!s) return "/farm.html";
    var map = [
      [/^(world|fissure|cycle|sortie|archon)/, "/warframe.html"],
      [/^(nightwave|nw\b)/, "/nightwave.html"],
      [/^(baro|void trader|ducat shop)/, "/baro.html"],
      [/^(steel|circuit|honoria|teshin)/, "/circuit.html"],
      [/^(relic|lith|meso|neo|axi)/, "/relics.html"],
      [/^(plan|planner|farm plan)/, "/planner.html"],
      [/^(vault|varzia|prime vault)/, "/vault.html"],
      [/^(worth|ducat|melt|sell or)/, "/worth.html"],
      [/^(riven|disposition)/, "/rivens.html"],
      [/^(market|plat|wfm|price)/, "/market.html"],
      [/^(compare)/, "/compare.html"],
      [/^(faction|grineer|corpus|infest)/, "/factions.html"],
      [/^(incarnon|evolution)/, "/incarnon.html"],
      [/^(shard|archon shard|tauforged)/, "/shards.html"],
      [/^(build|overframe)/, "/builds.html"],
      [/^(command|slash|\/)/, "/commands.html"],
      [/^(status|uptime|ping)/, "/status.html"],
      [/^(embed|obs|tv)/, "/embeds.html"],
      [/^(lfg|squad)/, "/lfg.html"],
      [/^(event|giveaway)/, "/events.html"],
      [/^(trade|trading)/, "/trading.html"],
      [/^(tenno|beginner|new)/, "/tenno.html"],
      [/^(dojo|clan)/, "/dojo.html"],
      [/^(setup|invite)/, "/setup.html"],
      [/^(privacy|legal|terms)/, "/privacy.html"],
      [/^(acquire|farm|drop|neurode|morphic)/, "/farm.html"],
    ];
    for (var i = 0; i < map.length; i++) {
      if (map[i][0].test(s)) return map[i][1];
    }
    return "/farm.html?q=" + encodeURIComponent(q);
  }

  function searchIndex() {
    var items = [];
    function pushList(list, group) {
      list.forEach(function (item) {
        if (item.section || !item.href) return;
        items.push({
          id: item.id,
          label: item.label,
          href: item.href,
          group: group,
          isNew: isNewTool(item.id),
        });
      });
    }
    pushList(NAV_TOOLS, "Tools");
    pushList(NAV_GUIDES, "Guides");
    items.push({ id: "home", label: "Home", href: "/", group: "Site", isNew: false });
    items.push({ id: "dashboard", label: "Dashboard", href: "/dashboard.html", group: "Site", isNew: false });
    items.push({ id: "contact", label: "Contact", href: "/contact.html", group: "Site", isNew: false });
    return items;
  }

  function cfg() {
    return window.OBSIDIAN_SITE || {};
  }

  function getTheme() {
    var t = document.documentElement.getAttribute("data-theme");
    return t === "light" ? "light" : "dark";
  }

  function applyTheme(theme) {
    theme = theme === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch (_) {}
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      var styles = getComputedStyle(document.documentElement);
      meta.setAttribute("content", (styles.getPropertyValue("--theme-meta") || "").trim() || (theme === "light" ? "#eef1f5" : "#06070a"));
    }
    document.querySelectorAll(".site-nav-theme").forEach(function (btn) {
      syncThemeButton(btn, theme);
    });
  }

  function syncThemeButton(btn, theme) {
    if (!btn) return;
    theme = theme || getTheme();
    var next = theme === "light" ? "dark" : "light";
    btn.setAttribute("aria-label", next === "light" ? "Switch to light mode" : "Switch to dark mode");
    btn.setAttribute("title", next === "light" ? "Light mode" : "Dark mode");
    btn.innerHTML =
      theme === "light"
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 14.5A8.5 8.5 0 1 1 9.5 3 7 7 0 0 0 21 14.5z"/></svg>'
        : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  }

  function toggleTheme() {
    applyTheme(getTheme() === "light" ? "dark" : "light");
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
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    closeMobileNav();
  }

  function siteOrigin() {
    try {
      var apiBase = (cfg().BOT_API_URL || "").replace(/\/$/, "");
      if (apiBase && window.location) {
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
    if (origin && href.charAt(0) === "/") return origin + href;
    return href;
  }

  function closeMobileNav() {
    var el = document.getElementById("site-nav");
    if (el) el.classList.remove("open");
    var btn = el && el.querySelector(".site-nav-toggle");
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function makeNavLink(item, origin, active) {
    var a = document.createElement("a");
    a.href = resolveHref(item, origin);
    a.textContent = item.label;
    if (item.id === active) a.className = "active";
    if (!origin && item.id === "home") a.addEventListener("click", goHome);
    if (!origin && item.id === "features") a.addEventListener("click", goFeatures);
    a.addEventListener("click", closeMobileNav);
    return a;
  }

  function makeNavDrop(label, items, origin, active, activeMap) {
    var details = document.createElement("details");
    details.className = "site-nav-drop" + (activeMap[active] ? " active" : "");
    var summary = document.createElement("summary");
    summary.textContent = label;
    details.appendChild(summary);
    var panel = document.createElement("div");
    panel.className = "site-nav-drop-panel site-nav-drop-panel--mega";
    items.forEach(function (item) {
      if (item.section) {
        var h = document.createElement("div");
        h.className = "site-nav-drop-section";
        h.textContent = item.section;
        panel.appendChild(h);
        return;
      }
      panel.appendChild(makeNavLink(item, origin, active));
    });
    details.appendChild(panel);
    details.addEventListener("toggle", function () {
      if (!details.open) return;
      var nav = document.getElementById("site-nav");
      if (nav) {
        nav.querySelectorAll("details.site-nav-drop").forEach(function (other) {
          if (other !== details) other.open = false;
        });
      }
      function onDoc(e) {
        if (!details.contains(e.target)) {
          details.open = false;
          document.removeEventListener("click", onDoc);
        }
      }
      setTimeout(function () {
        document.addEventListener("click", onDoc);
      }, 0);
    });
    return details;
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
    logoImg.width = 28;
    logoImg.height = 28;
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

    // Logo = home · Tools ▾ · Guides ▾ · Dashboard · theme · Invite
    links.appendChild(makeNavDrop("Tools", NAV_TOOLS, origin, active, TOOL_IDS));
    links.appendChild(makeNavDrop("Guides", NAV_GUIDES, origin, active, GUIDE_IDS));
    links.appendChild(makeNavLink(NAV_DASHBOARD, origin, active));

    var jumpBtn = document.createElement("button");
    jumpBtn.type = "button";
    jumpBtn.className = "site-nav-jump";
    jumpBtn.setAttribute("aria-label", "Search pages");
    jumpBtn.title = "Search (Ctrl+K)";
    jumpBtn.innerHTML =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>';
    jumpBtn.addEventListener("click", function () {
      openJumpMenu();
    });
    links.appendChild(jumpBtn);

    var themeBtn = document.createElement("button");
    themeBtn.type = "button";
    themeBtn.className = "site-nav-theme";
    syncThemeButton(themeBtn, getTheme());
    themeBtn.addEventListener("click", function () {
      toggleTheme();
    });
    links.appendChild(themeBtn);

    var cta = document.createElement("a");
    cta.href = inviteUrl();
    cta.className = "site-nav-cta";
    cta.textContent = "Invite";
    cta.target = "_blank";
    cta.rel = "noopener noreferrer";
    if (cta.getAttribute("href") === "#") {
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
    var logoSrc = (origin || "") + "/assets/logo.png";
    var dash = origin ? "/dashboard.html" : dashboardUrl();
    var invite = inviteUrl();
    var discord = cfg().DISCORD_SERVER_INVITE || "https://discord.gg/bJscayQNK4";
    var developer = cfg().BOT_DEVELOPER || "Danger!";

    el.className = "site-footer";
    el.innerHTML =
      '<div class="site-footer-inner">' +
      '<div class="site-footer-top">' +
      '<div class="site-footer-brand-block">' +
      '<a class="site-footer-logo" href="' +
      (prefix || "/") +
      '">' +
      '<img src="' +
      logoSrc +
      '" alt="" width="36" height="36" />' +
      "<span>Obsidian Overseer</span>" +
      "</a>" +
      '<p class="site-footer-blurb">Warframe world-state and clan tools for Discord.</p>' +
      '<a class="site-footer-cta" href="' +
      invite +
      '" target="_blank" rel="noopener noreferrer">Add to Discord</a>' +
      "</div>" +
      '<div class="site-footer-links">' +
      "<div><h4>Product</h4>" +
      '<a href="' +
      prefix +
      '/">Home</a>' +
      '<a href="' +
      prefix +
      '/#features">Features</a>' +
      '<a href="' +
      prefix +
      '/warframe.html">World state</a>' +
      '<a href="' +
      prefix +
      '/farm.html">Acquire</a>' +
      '<a href="' +
      prefix +
      '/relics.html">Relics</a>' +
      '<a href="' +
      prefix +
      '/market.html">Market</a>' +
      '<a href="' +
      prefix +
      '/nightwave.html">Nightwave</a>' +
      '<a href="' +
      prefix +
      '/worth.html">Ducat / plat</a>' +
      '<a href="' +
      prefix +
      '/commands.html">Commands</a>' +
      '<a href="' +
      dash +
      '">Dashboard</a>' +
      "</div>" +
      "<div><h4>Guides</h4>" +
      '<a href="' +
      prefix +
      '/tenno.html">First week</a>' +
      '<a href="' +
      prefix +
      '/setup.html">Setup</a>' +
      '<a href="' +
      prefix +
      '/faq.html">FAQ</a>' +
      '<a href="' +
      prefix +
      '/changelog.html">Changelog</a>' +
      "</div>" +
      "<div><h4>Support</h4>" +
      '<a href="' +
      prefix +
      '/contact.html">Contact</a>' +
      '<a href="' +
      discord +
      '" target="_blank" rel="noopener noreferrer">Discord</a>' +
      '<a href="' +
      prefix +
      '/privacy.html">Privacy</a>' +
      '<a href="' +
      prefix +
      '/legal.html#terms">Terms</a>' +
      "</div>" +
      "</div>" +
      "</div>" +
      '<div class="site-footer-bottom">' +
      '<div class="site-footer-meta">' +
      '<img src="' +
      logoSrc +
      '" alt="" width="18" height="18" />' +
      "<span>Built by " +
      developer +
      "</span>" +
      '<span class="site-footer-sep" aria-hidden="true">·</span>' +
      '<a href="' +
      discord +
      '" target="_blank" rel="noopener noreferrer">Join Discord</a>' +
      '<span class="site-footer-sep" aria-hidden="true">·</span>' +
      '<a href="' +
      prefix +
      '/privacy.html">Privacy</a>' +
      '<span class="site-footer-sep" aria-hidden="true">·</span>' +
      '<a href="' +
      prefix +
      '/legal.html#terms">Terms</a>' +
      "</div>" +
      '<p class="site-footer-legal">Not affiliated with Discord or Digital Extremes / Warframe.</p>' +
      "</div>" +
      "</div>";
  }

  function apiUrl(path) {
    var base = (cfg().BOT_API_URL || "").replace(/\/$/, "");
    if (!base) return null;
    if (!/^https?:\/\//i.test(base)) base = "https://" + base;
    try {
      if (window.location && window.location.origin) {
        var apiHost = new URL(base).host;
        if (window.location.host === apiHost) {
          return path.startsWith("/") ? path : "/" + path;
        }
      }
    } catch (_) {}
    return base + (path.startsWith("/") ? path : "/" + path);
  }

  /** Live Market orders host (Deno Deploy). Falls back to BOT_API_URL. */
  function wfmProxyUrl(path) {
    var base = (cfg().WFM_PROXY_URL || "").replace(/\/$/, "");
    if (base) {
      if (!/^https?:\/\//i.test(base)) base = "https://" + base;
      return base + (path.startsWith("/") ? path : "/" + path);
    }
    return apiUrl(path);
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
    options = options || {};
    if (!data) return false;
    var applied = false;
    if (options.serversEl && data.guild_count != null) {
      options.serversEl.textContent = formatCount(data.guild_count);
      applied = true;
    }
    if (options.usersEl && data.user_count != null) {
      options.usersEl.textContent = formatCount(data.user_count);
      applied = true;
    }
    if (!options.serversEl && !options.usersEl) {
      applied = data.guild_count != null || data.user_count != null;
    }
    if (options.wrapEl) options.wrapEl.classList.remove("loading");
    return applied;
  }

  function failPublicStats(options) {
    options = options || {};
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
        if (!applyPublicStats(data, options) && data.guild_count == null && data.user_count == null) {
          throw new Error("stats empty");
        }
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
        applyPublicStats(data, options);
        if (data.guild_count != null || data.user_count != null) return data;
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
    var label;
    if (online) {
      label = "Bot online";
      if (version) label += " · v" + version;
    } else if (version) {
      // Same-origin publish fallback — don't show a scary "unavailable" when Railway is blocked.
      el.classList.remove("offline");
      el.classList.add("online");
      label = "v" + version;
    } else {
      label = "Status unavailable";
    }
    el.innerHTML = '<span class="site-status-dot" aria-hidden="true"></span>' + label;
  }

  function loadPublishedStatus() {
    return fetch("/assets/bot-status.json", { cache: "no-cache" })
      .then(function (res) {
        if (!res.ok) throw new Error("bot-status missing");
        return res.json();
      })
      .catch(function () {
        return fetch("/assets/changelog.json", { cache: "no-cache" }).then(function (res) {
          if (!res.ok) throw new Error("changelog missing");
          return res.json();
        });
      })
      .then(function (data) {
        if (!data) return null;
        return {
          ok: data.ok !== false,
          version: data.version || null,
          source: data.source || "static",
        };
      })
      .catch(function () {
        return null;
      });
  }

  function tryLivePing() {
    var url = apiUrl("/api/ping");
    if (!url) return Promise.resolve(null);
    return fetch(url + (url.indexOf("?") >= 0 ? "&" : "?") + "_=" + Date.now(), {
      cache: "no-store",
      mode: "cors",
    })
      .then(function (res) {
        if (!res.ok) throw new Error("ping " + res.status);
        var ct = (res.headers.get("content-type") || "").toLowerCase();
        if (ct.indexOf("application/json") < 0) throw new Error("ping not json");
        return res.json();
      })
      .then(function (data) {
        if (!data || data.ok === false) throw new Error("ping unhealthy");
        return {
          ok: true,
          version: data.version || data.bot_version || null,
          live: true,
        };
      })
      .catch(function () {
        return null;
      });
  }

  /**
   * Resolve bot status for the site.
   * Prefers live /api/ping when Railway allows it; otherwise uses same-origin
   * bot-status.json / changelog.json so the marketing site never depends on CORS.
   * Returns { online, version, live } or null.
   */
  function resolveBotStatus() {
    return Promise.all([loadPublishedStatus(), tryLivePing()]).then(function (pair) {
      var published = pair[0];
      var live = pair[1];
      if (live) {
        return {
          online: true,
          version: live.version || (published && published.version) || null,
          live: true,
        };
      }
      if (published && published.version) {
        return {
          online: true,
          version: published.version,
          live: false,
        };
      }
      return { online: false, version: null, live: false };
    });
  }

  function loadBotStatus(el) {
    return resolveBotStatus().then(function (status) {
      if (!status) {
        if (el) setStatusEl(el, false, null);
        return null;
      }
      if (el) setStatusEl(el, status.online, status.version);
      return status;
    });
  }

  function closeJumpMenu() {
    var overlay = document.getElementById("site-jump");
    if (overlay) overlay.remove();
  }

  function openJumpMenu(initialQuery) {
    closeJumpMenu();
    var origin = siteOrigin();
    var items = searchIndex();
    var overlay = document.createElement("div");
    overlay.id = "site-jump";
    overlay.className = "site-jump";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "Jump to page");
    overlay.innerHTML =
      '<div class="site-jump-panel">' +
      '<form class="site-jump-form" role="search">' +
      '<input type="search" class="site-jump-input" placeholder="Jump to a tool or guide…" autocomplete="off" aria-label="Search pages" />' +
      '<kbd class="site-jump-kbd">Esc</kbd>' +
      "</form>" +
      '<ul class="site-jump-list" role="listbox"></ul>' +
      '<p class="site-jump-hint">Enter opens · ↑↓ move · Esc close</p>' +
      "</div>";
    document.body.appendChild(overlay);

    var input = overlay.querySelector(".site-jump-input");
    var list = overlay.querySelector(".site-jump-list");
    var form = overlay.querySelector(".site-jump-form");
    var activeIdx = 0;
    var visible = [];

    function hrefFor(item) {
      if (!origin) return item.href;
      if (item.href.indexOf("http") === 0) return item.href;
      if (item.href.charAt(0) === "/") return origin + item.href;
      return origin + "/" + item.href;
    }

    function renderList(q) {
      q = String(q || "").trim().toLowerCase();
      visible = items.filter(function (it) {
        if (!q) return true;
        return (
          it.label.toLowerCase().indexOf(q) >= 0 ||
          it.id.toLowerCase().indexOf(q) >= 0 ||
          it.group.toLowerCase().indexOf(q) >= 0
        );
      });
      if (!visible.length && q) {
        visible = [
          {
            id: "farm-q",
            label: 'Search Acquire for "' + q + '"',
            href: "/farm.html?q=" + encodeURIComponent(q),
            group: "Search",
            isNew: false,
          },
        ];
      }
      activeIdx = 0;
      list.innerHTML = visible
        .slice(0, 12)
        .map(function (it, i) {
          return (
            '<li role="option" class="site-jump-item' +
            (i === 0 ? " active" : "") +
            '" data-idx="' +
            i +
            '">' +
            '<span class="site-jump-group">' +
            it.group +
            "</span>" +
            '<span class="site-jump-label">' +
            it.label +
            (it.isNew ? ' <span class="tool-badge-new">New</span>' : "") +
            "</span></li>"
          );
        })
        .join("");
    }

    function go(idx) {
      var it = visible[idx];
      if (!it) return;
      closeJumpMenu();
      window.location.href = hrefFor(it);
    }

    function setActive(idx) {
      var nodes = list.querySelectorAll(".site-jump-item");
      if (!nodes.length) return;
      activeIdx = (idx + nodes.length) % nodes.length;
      nodes.forEach(function (n, i) {
        n.classList.toggle("active", i === activeIdx);
      });
      nodes[activeIdx].scrollIntoView({ block: "nearest" });
    }

    renderList(initialQuery || "");
    if (initialQuery) input.value = initialQuery;
    setTimeout(function () {
      input.focus();
      input.select();
    }, 0);

    input.addEventListener("input", function () {
      renderList(input.value);
    });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (visible.length) go(activeIdx);
      else window.location.href = routeToolSearch(input.value);
    });
    list.addEventListener("click", function (e) {
      var li = e.target.closest(".site-jump-item");
      if (!li) return;
      go(Number(li.getAttribute("data-idx")) || 0);
    });
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) closeJumpMenu();
    });
    function onKey(e) {
      if (e.key === "Escape") {
        e.preventDefault();
        closeJumpMenu();
        document.removeEventListener("keydown", onKey);
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive(activeIdx + 1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive(activeIdx - 1);
      }
    }
    document.addEventListener("keydown", onKey);
  }

  function bindJumpHotkey() {
    document.addEventListener("keydown", function (e) {
      var tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (e.target && e.target.isContentEditable)) {
        if (!(e.key === "Escape" && document.getElementById("site-jump"))) return;
      }
      if ((e.ctrlKey || e.metaKey) && String(e.key).toLowerCase() === "k") {
        e.preventDefault();
        if (document.getElementById("site-jump")) closeJumpMenu();
        else openJumpMenu();
      }
    });
  }

  function markNewToolCards() {
    document.querySelectorAll("[data-tool-id]").forEach(function (el) {
      var id = el.getAttribute("data-tool-id");
      if (!isNewTool(id)) return;
      if (el.querySelector(".tool-badge-new")) return;
      var badge = document.createElement("span");
      badge.className = "tool-badge-new";
      badge.textContent = "New";
      var strong = el.querySelector("strong");
      if (strong) strong.appendChild(document.createTextNode(" "));
      if (strong) strong.appendChild(badge);
      else el.insertBefore(badge, el.firstChild);
    });
  }

  function registerPwa() {
    if (!("serviceWorker" in navigator)) return;
    var host = window.location.hostname;
    if (host !== "obsidianoverseer.com" && host !== "www.obsidianoverseer.com" && host !== "localhost" && host !== "127.0.0.1") {
      return;
    }
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  }

  function ensureManifestLink() {
    if (document.querySelector('link[rel="manifest"]')) return;
    var link = document.createElement("link");
    link.rel = "manifest";
    link.href = "/manifest.webmanifest";
    document.head.appendChild(link);
  }

  function initChrome() {
    if (!document.documentElement.getAttribute("data-theme")) {
      applyTheme(
        (function () {
          try {
            var saved = localStorage.getItem(THEME_KEY);
            if (saved === "light" || saved === "dark") return saved;
          } catch (_) {}
          return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches
            ? "light"
            : "dark";
        })()
      );
    } else {
      applyTheme(getTheme());
    }
    renderNav();
    renderFooter();
    bindJumpHotkey();
    markNewToolCards();
    ensureManifestLink();
    registerPwa();
  }

  window.ObsidianSite = {
    renderNav: renderNav,
    renderFooter: renderFooter,
    apiUrl: apiUrl,
    wfmProxyUrl: wfmProxyUrl,
    dashboardUrl: dashboardUrl,
    inviteUrl: inviteUrl,
    loadPublicBotStats: loadPublicBotStats,
    loadBotStatus: loadBotStatus,
    resolveBotStatus: resolveBotStatus,
    formatCount: formatCount,
    getTheme: getTheme,
    setTheme: applyTheme,
    toggleTheme: toggleTheme,
    config: cfg,
    routeToolSearch: routeToolSearch,
    openJumpMenu: openJumpMenu,
    isNewTool: isNewTool,
    searchIndex: searchIndex,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initChrome);
  } else {
    initChrome();
  }
})();
