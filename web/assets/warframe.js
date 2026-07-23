/**
 * Public Warframe world-state page — fetches api.warframestat.us (no bot login).
 */
(function () {
  var API_HOST = "https://api.warframestat.us";
  var REFRESH_MS = 60 * 1000;
  var PLATFORM_KEY = "oo_wf_platform";
  var LANG_KEY = "oo_wf_lang";
  var DENSE_KEY = "oo_wf_dense";
  var COLLAPSE_KEY = "oo_wf_collapsed";
  var FISSURE_TIERS_KEY = "oo_wf_fissure_tiers";
  var FISSURE_MISSION_KEY = "oo_wf_fissure_mission";
  var FISSURE_MODE_KEY = "oo_wf_fissure_mode";
  var FISSURE_SORT_KEY = "oo_wf_fissure_sort";

  var PLATFORMS = { pc: "PC", ps4: "PlayStation", xb1: "Xbox", swi: "Switch" };
  var LANGS = ["en", "de", "es", "fr", "pt", "ru", "zh", "ko", "tc", "uk"];
  var DEFAULT_FISSURE_TIERS = ["Lith", "Meso", "Neo", "Axi"];
  var ALL_FISSURE_TIERS = ["Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia"];
  var BOUNTY_SYNDICATES = [
    "Ostrons",
    "Solaris United",
    "Entrati",
    "The Holdfasts",
    "Cavia",
    "Kahl's Garrison",
    "The Hex",
  ];

  var root = document.getElementById("wf-root");
  var statusEl = document.getElementById("wf-status");
  var teaserEl = document.getElementById("wf-teaser");
  var refreshBtn = document.getElementById("wf-refresh");
  var platformSelect = document.getElementById("wf-platform");
  var langSelect = document.getElementById("wf-lang");
  var denseBtn = document.getElementById("wf-dense");
  var collapseBtn = document.getElementById("wf-collapse-all");
  var platformLabel = document.getElementById("wf-platform-label");
  var timer = null;
  var tickTimer = null;
  var lastBundle = null;
  var lastFissures = [];
  var lastRivens = null;
  var collapsedPrefer = loadCollapsedPrefer();
  var platform = loadPlatform();
  var lang = loadLang();
  var pendingSection = null;

  var ICO = {
    baro: '<svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5M2 12l10 5 10-5"/></svg>',
    cycle: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
    sortie: '<svg viewBox="0 0 24 24"><path d="M14.5 17.5L3 6V3h3l11.5 11.5M13 19l6-6M16 16l4 4"/></svg>',
    archon: '<svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
    ops: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    void: '<svg viewBox="0 0 24 24"><path d="M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3z"/></svg>',
    alert: '<svg viewBox="0 0 24 24"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg>',
    invasion: '<svg viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    event: '<svg viewBox="0 0 24 24"><path d="M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/></svg>',
    news: '<svg viewBox="0 0 24 24"><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8M15 18h-5M10 6h8v4h-8z"/></svg>',
    build: '<svg viewBox="0 0 24 24"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
    bounty: '<svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/></svg>',
    market: '<svg viewBox="0 0 24 24"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/></svg>',
  };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function parseTime(iso) {
    if (!iso) return null;
    var t = Date.parse(iso);
    return isNaN(t) ? null : t;
  }

  function timeUntil(iso) {
    var t = parseTime(iso);
    if (t == null) return "—";
    var ms = t - Date.now();
    if (ms <= 0) return "soon";
    var sec = Math.floor(ms / 1000);
    var d = Math.floor(sec / 86400);
    var h = Math.floor((sec % 86400) / 3600);
    var m = Math.floor((sec % 3600) / 60);
    if (d > 0) return d + "d " + h + "h";
    if (h > 0) return h + "h " + m + "m";
    return Math.max(m, 1) + "m";
  }

  function etaHtml(iso) {
    return '<span class="wf-eta tick" data-expiry="' + esc(iso || "") + '">' + esc(timeUntil(iso)) + "</span>";
  }

  function isActiveWindow(activation, expiry) {
    var a = parseTime(activation);
    var e = parseTime(expiry);
    var now = Date.now();
    if (a != null && e != null) return now >= a && now < e;
    if (e != null) return now < e;
    return false;
  }

  function lsGet(key, fallback) {
    try {
      var v = localStorage.getItem(key);
      return v == null ? fallback : v;
    } catch (e) {
      return fallback;
    }
  }

  function lsSet(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (e) {}
  }

  function loadPlatform() {
    var p = lsGet(PLATFORM_KEY, "pc");
    return PLATFORMS[p] ? p : "pc";
  }

  function savePlatform(p) {
    platform = PLATFORMS[p] ? p : "pc";
    lsSet(PLATFORM_KEY, platform);
    if (platformSelect) platformSelect.value = platform;
    if (platformLabel) platformLabel.textContent = PLATFORMS[platform];
    syncUrlParams();
  }

  function loadLang() {
    var l = lsGet(LANG_KEY, "en");
    return LANGS.indexOf(l) >= 0 ? l : "en";
  }

  function saveLang(l) {
    lang = LANGS.indexOf(l) >= 0 ? l : "en";
    lsSet(LANG_KEY, lang);
    if (langSelect) langSelect.value = lang;
    syncUrlParams();
  }

  function loadCollapsedPrefer() {
    return lsGet(COLLAPSE_KEY, "0") === "1";
  }

  function saveCollapsedPrefer(on) {
    collapsedPrefer = !!on;
    lsSet(COLLAPSE_KEY, collapsedPrefer ? "1" : "0");
  }

  function applyDense(on) {
    document.body.classList.toggle("wf-dense", !!on);
    lsSet(DENSE_KEY, on ? "1" : "0");
    if (denseBtn) {
      denseBtn.setAttribute("aria-pressed", on ? "true" : "false");
      denseBtn.classList.toggle("on", !!on);
    }
  }

  function syncUrlParams() {
    try {
      var url = new URL(window.location.href);
      url.searchParams.set("platform", platform);
      url.searchParams.set("lang", lang);
      history.replaceState(null, "", url.pathname + url.search + url.hash);
    } catch (e) {}
  }

  function applyDeepLinks() {
    try {
      var params = new URLSearchParams(window.location.search);
      var p = params.get("platform");
      var l = params.get("lang");
      var section = params.get("section");
      if (p && PLATFORMS[p]) {
        platform = p;
        lsSet(PLATFORM_KEY, platform);
      }
      if (l && LANGS.indexOf(l) >= 0) {
        lang = l;
        lsSet(LANG_KEY, lang);
      }
      if (section) {
        pendingSection = section.indexOf("wf-") === 0 ? section : "wf-" + section;
      }
    } catch (e) {}
  }

  function scrollPendingSection() {
    if (!pendingSection) return;
    var el = document.getElementById(pendingSection);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    pendingSection = null;
  }

  function panel(title, ico, bodyHtml, opts) {
    opts = opts || {};
    var open = opts.forceOpen || !collapsedPrefer;
    return (
      '<details class="wf-panel wf-collapse' +
      (opts.cls ? " " + opts.cls : "") +
      '"' +
      (open ? " open" : "") +
      ">" +
      "<summary class=\"wf-panel-head\"><span class=\"ico\" aria-hidden=\"true\">" +
      (ICO[ico] || ICO.ops) +
      "</span><h2>" +
      esc(title) +
      "</h2></summary>" +
      '<div class="wf-panel-body">' +
      bodyHtml +
      "</div></details>"
    );
  }

  function band(id, label) {
    return (
      '<div class="wf-band" id="' +
      id +
      '"><div class="wf-band-label">' +
      esc(label) +
      "</div>"
    );
  }

  function setStatus(ok, text) {
    if (!statusEl) return;
    statusEl.className = "wf-status " + (ok ? "ok" : "err");
    statusEl.innerHTML = '<span class="dot" aria-hidden="true"></span>' + esc(text);
  }

  function loadFissureTiers() {
    try {
      var raw = lsGet(FISSURE_TIERS_KEY, null);
      if (!raw) return DEFAULT_FISSURE_TIERS.slice();
      var arr = JSON.parse(raw);
      if (!Array.isArray(arr) || !arr.length) return DEFAULT_FISSURE_TIERS.slice();
      return arr.filter(function (t) {
        return ALL_FISSURE_TIERS.indexOf(t) >= 0;
      });
    } catch (e) {
      return DEFAULT_FISSURE_TIERS.slice();
    }
  }

  function saveFissureTiers(tiers) {
    lsSet(FISSURE_TIERS_KEY, JSON.stringify(tiers));
  }

  function loadFissureMission() {
    return lsGet(FISSURE_MISSION_KEY, "") || "";
  }

  function saveFissureMission(m) {
    lsSet(FISSURE_MISSION_KEY, m || "");
  }

  function loadFissureMode() {
    var m = lsGet(FISSURE_MODE_KEY, "all");
    return m === "normal" || m === "hard" || m === "storm" ? m : "all";
  }

  function saveFissureMode(m) {
    lsSet(FISSURE_MODE_KEY, m || "all");
  }

  function loadFissureSort() {
    var s = lsGet(FISSURE_SORT_KEY, "tier");
    return s === "eta" ? "eta" : "tier";
  }

  function saveFissureSort(s) {
    lsSet(FISSURE_SORT_KEY, s === "eta" ? "eta" : "tier");
  }

  function apiBase() {
    return API_HOST + "/" + platform;
  }

  function fetchJson(path) {
    return fetch(apiBase() + path + (path.indexOf("?") >= 0 ? "&" : "?") + "language=" + encodeURIComponent(lang), {
      cache: "no-store",
      headers: { Accept: "application/json" },
    }).then(function (res) {
      if (!res.ok) throw new Error(path + " HTTP " + res.status);
      return res.json();
    });
  }

  function loadAll() {
    var paths = [
      "/voidTrader",
      "/vaultTrader",
      "/dailyDeals",
      "/cetusCycle",
      "/vallisCycle",
      "/cambionCycle",
      "/earthCycle",
      "/duviriCycle",
      "/zarimanCycle",
      "/sortie",
      "/archonHunt",
      "/steelPath",
      "/arbitration",
      "/nightwave",
      "/archimedeas",
      "/events",
      "/constructionProgress",
      "/fissures",
      "/alerts",
      "/invasions",
      "/news",
      "/sentientOutposts",
      "/syndicateMissions",
      "/conclaveChallenges",
      "/flashSales",
      "/globalUpgrades",
      "/simaris",
      "/kuva",
      "/persistentEnemies",
      "/rivens",
    ];
    return Promise.all(
      paths.map(function (p) {
        return fetchJson(p).then(
          function (data) {
            return { path: p, data: data, ok: true };
          },
          function () {
            return { path: p, data: null, ok: false };
          }
        );
      })
    ).then(function (results) {
      var map = {};
      var fails = 0;
      results.forEach(function (r) {
        map[r.path] = r.data;
        if (!r.ok) fails++;
      });
      return { map: map, fails: fails, total: results.length };
    });
  }

  function cycleInfo(c, kind) {
    var mark = { cetus: "C", vallis: "V", cambion: "D", earth: "E", duviri: "U", zariman: "Z" }[kind] || "?";
    var name = {
      cetus: "Cetus",
      vallis: "Orb Vallis",
      cambion: "Cambion Drift",
      earth: "Earth",
      duviri: "Duviri",
      zariman: "Zariman",
    }[kind];
    if (!c) return { mark: mark, name: name, state: "—", tone: "", expiry: null };
    if (kind === "vallis") {
      return { mark: mark, name: name, state: c.isWarm ? "Warm" : "Cold", tone: c.isWarm ? "warm" : "cold", expiry: c.expiry };
    }
    if (kind === "cambion") {
      var st = String(c.state || "").toLowerCase();
      return {
        mark: mark,
        name: name,
        state: c.state || "—",
        tone: st.indexOf("vome") >= 0 ? "vome" : st.indexOf("fass") >= 0 ? "fass" : "",
        expiry: c.expiry,
      };
    }
    if (kind === "duviri") {
      return { mark: mark, name: name, state: c.state || "—", tone: "mood", expiry: c.expiry };
    }
    if (kind === "zariman") {
      var zs = String(c.state || (c.isCorpus ? "corpus" : "grineer")).toLowerCase();
      return {
        mark: mark,
        name: name,
        state: c.state || (c.isCorpus ? "Corpus" : "Grineer"),
        tone: zs.indexOf("corpus") >= 0 ? "corpus" : "grineer",
        expiry: c.expiry,
      };
    }
    return { mark: mark, name: name, state: c.isDay ? "Day" : "Night", tone: c.isDay ? "day" : "night", expiry: c.expiry };
  }

  function updateTeaser(map) {
    if (!teaserEl) return;
    var vt = map["/voidTrader"];
    var cetus = map["/cetusCycle"];
    var parts = [];
    if (vt) {
      var active = isActiveWindow(vt.activation, vt.expiry);
      if (active) {
        parts.push(
          "<strong>Baro</strong> at " +
            esc(vt.location || "relay") +
            ' · leaves <span class="wf-eta tick" data-expiry="' +
            esc(vt.expiry) +
            '">' +
            esc(timeUntil(vt.expiry)) +
            "</span>"
        );
      } else if (vt.activation) {
        parts.push(
          '<strong>Baro</strong> next in <span class="wf-eta tick" data-expiry="' +
            esc(vt.activation) +
            '">' +
            esc(timeUntil(vt.activation)) +
            "</span>"
        );
      }
    }
    if (cetus) {
      parts.push(
        "<strong>Cetus</strong> " +
          esc(cetus.isDay ? "Day" : "Night") +
          ' · <span class="wf-eta tick" data-expiry="' +
          esc(cetus.expiry || "") +
          '">' +
          esc(timeUntil(cetus.expiry)) +
          "</span> left"
      );
    }
    if (!parts.length) {
      teaserEl.hidden = true;
      return;
    }
    teaserEl.innerHTML = parts.join('<span aria-hidden="true"> · </span>');
    teaserEl.hidden = false;
  }

  function formatReward(reward) {
    if (!reward) return "";
    var bits = [];
    (reward.items || []).forEach(function (it) {
      bits.push(it);
    });
    (reward.countedItems || []).forEach(function (it) {
      bits.push((it.count > 1 ? it.count + "× " : "") + (it.type || it.key || "?"));
    });
    if (reward.credits) bits.push(reward.credits + " cr");
    return bits.join(", ");
  }

  function renderInventoryGrid(inv, emptyMsg, opts) {
    opts = opts || {};
    var primaryLabel = opts.primaryLabel || "ducats";
    if (!inv || !inv.length) {
      return '<p class="meta">' + esc(emptyMsg || "No inventory listed.") + "</p>";
    }
    var html = '<div class="wf-inv-grid">';
    inv.forEach(function (item) {
      var priceBits = [];
      var primary = item.aya != null ? item.aya : item.ducats != null ? item.ducats : null;
      if (primary != null) priceBits.push("<em>" + esc(primary) + "</em> " + esc(primaryLabel));
      if (item.credits != null) priceBits.push(esc(item.credits) + " cr");
      html +=
        '<div class="wf-inv-item"><span class="name">' +
        esc(item.item || item.name || "?") +
        '</span><span class="price">' +
        (priceBits.length ? priceBits.join(" · ") : "—") +
        "</span></div>";
    });
    return html + "</div>";
  }

  function renderBaro(vt) {
    var body = "";
    if (!vt) {
      body = '<p class="wf-empty">Could not load Baro.</p>';
      return band("wf-trader", "Trader") + panel("Baro Ki'Teer", "baro", body, { forceOpen: true, cls: "wf-baro" });
    }
    var active = isActiveWindow(vt.activation, vt.expiry);
    var loc = vt.location || "Unknown relay";
    body += '<div class="wf-baro-top"><div>';
    body +=
      '<span class="wf-baro-badge' +
      (active ? "" : " away") +
      '">' +
      (active ? "At relay" : "In transit") +
      "</span>";
    body += '<p class="wf-baro-loc"><strong>' + esc(loc) + "</strong></p></div>";
    body += '<div class="wf-baro-countdown">';
    if (active) {
      body += '<span class="label">Leaves in</span>' + etaHtml(vt.expiry);
    } else if (vt.activation) {
      body += '<span class="label">Arrives in</span>' + etaHtml(vt.activation);
    } else {
      body += '<span class="label">Status</span><span class="wf-eta">—</span>';
    }
    body += "</div></div>";

    var inv = vt.inventory || [];
    if (active) {
      body += renderInventoryGrid(inv, "Inventory not listed yet — check closer to arrival.");
      if (inv.length) body += '<p class="meta" style="margin-top:12px">' + inv.length + " items</p>";
    }

    var schedule = vt.schedule || [];
    if (schedule.length) {
      body += '<h3 class="wf-subhead">Upcoming visits</h3><ul class="wf-mission-list">';
      schedule.slice(0, 6).forEach(function (s) {
        body +=
          "<li><strong>" +
          esc(s.location || s.node || "Relay") +
          "</strong>" +
          (s.expiry ? " · leaves " + etaHtml(s.expiry) : "") +
          (s.activation ? " · arrives " + etaHtml(s.activation) : "") +
          "</li>";
      });
      body += "</ul>";
    }

    return band("wf-trader", "Trader") + panel("Baro Ki'Teer", "baro", body, { forceOpen: true, cls: "wf-baro" });
  }

  function renderVarzia(vt) {
    if (!vt) return "";
    var body =
      '<p class="meta">' +
      esc(vt.location || "Maroo's Bazaar") +
      (vt.expiry ? " · ends in " + etaHtml(vt.expiry) : "") +
      "</p>" +
      renderInventoryGrid(vt.inventory || [], "No vault inventory listed.", { primaryLabel: "Aya" });
    return panel(vt.character || "Varzia", "baro", body);
  }

  function renderDarvo(list) {
    if (!list || !list.length) return "";
    var body = '<ul class="wf-mission-list">';
    list.forEach(function (d) {
      body +=
        "<li><strong>" +
        esc(d.item || "?") +
        "</strong> · " +
        esc(d.salePrice != null ? d.salePrice : "?") +
        " platinum" +
        (d.discount != null ? " (−" + esc(d.discount) + "%)" : "") +
        (d.sold != null && d.total != null
          ? ' <span class="meta">— ' + esc(d.sold) + "/" + esc(d.total) + " sold</span>"
          : "") +
        (d.expiry ? " · " + etaHtml(d.expiry) + " left" : "") +
        "</li>";
    });
    body += "</ul>";
    return panel("Darvo deal", "ops", body);
  }

  function renderCycles(map) {
    var items = [
      cycleInfo(map["/cetusCycle"], "cetus"),
      cycleInfo(map["/vallisCycle"], "vallis"),
      cycleInfo(map["/cambionCycle"], "cambion"),
      cycleInfo(map["/earthCycle"], "earth"),
      cycleInfo(map["/duviriCycle"], "duviri"),
      cycleInfo(map["/zarimanCycle"], "zariman"),
    ];
    var body = '<div class="wf-cycle-grid">';
    items.forEach(function (c) {
      body +=
        '<div class="wf-cycle-card ' +
        esc(c.tone) +
        '"><span class="wf-cycle-mark" aria-hidden="true">' +
        esc(c.mark) +
        '</span><div class="state">' +
        esc(c.state) +
        '</div><div class="name">' +
        esc(c.name) +
        "</div>" +
        (c.expiry ? '<div class="eta">' + etaHtml(c.expiry) + " left</div>" : "") +
        "</div>";
    });
    body += "</div>";
    return band("wf-cycles", "Cycles") + panel("Open-world cycles", "cycle", body, { forceOpen: true }) + "</div>";
  }

  function renderMission(title, data, ico) {
    if (!data) return panel(title, ico, '<p class="wf-empty">No data.</p>');
    var missions = data.variants && data.variants.length ? data.variants : data.missions || [];
    var body =
      '<p class="meta">' +
      esc(data.boss || "") +
      (data.faction ? " · " + esc(data.faction) : "") +
      (data.expiry ? " · resets in " + etaHtml(data.expiry) : "") +
      "</p>";
    if (!missions.length) {
      body += '<p class="wf-empty">No missions listed.</p>';
    } else {
      body += '<ul class="wf-mission-list">';
      missions.forEach(function (m, idx) {
        body +=
          "<li><strong>" +
          (idx + 1) +
          ". " +
          esc(m.node || m.missionType || m.type || "?") +
          "</strong> · " +
          esc(m.missionType || m.type || "") +
          (m.modifier ? ' <span class="meta">— ' + esc(m.modifier) + "</span>" : "") +
          "</li>";
      });
      body += "</ul>";
    }
    return panel(title, ico, body, { forceOpen: true });
  }

  function archimedeaTitle(entry) {
    var key = String(entry.typeKey || entry.type || "")
      .replace(/\s+/g, "")
      .toUpperCase();
    if (key.indexOf("HEX") >= 0) return "Temporal Archimedea";
    if (key.indexOf("LAB") >= 0) return "Deep Archimedea";
    return entry.type || entry.typeKey || "Archimedea";
  }

  function renderArchimedeas(list) {
    if (!list || !list.length) return "";
    var html = "";
    list.forEach(function (entry) {
      var body = '<p class="meta">' + (entry.expiry ? "Resets in " + etaHtml(entry.expiry) : "Active") + "</p>";
      var missions = entry.missions || [];
      if (missions.length) {
        body += '<ul class="wf-mission-list">';
        missions.forEach(function (m, idx) {
          body +=
            "<li><strong>" +
            (idx + 1) +
            ". " +
            esc(m.missionType || "?") +
            "</strong>" +
            (m.faction ? " · " + esc(m.faction) : "");
          if (m.deviation && m.deviation.name) {
            body +=
              '<div class="wf-mod-line"><strong>Deviation:</strong> ' +
              esc(m.deviation.name) +
              (m.deviation.description ? " — " + esc(m.deviation.description) : "") +
              "</div>";
          }
          (m.risks || []).forEach(function (r) {
            body +=
              '<div class="wf-mod-line"><strong>Risk' +
              (r.isHard ? " (hard)" : "") +
              ":</strong> " +
              esc(r.name || "") +
              (r.description ? " — " + esc(r.description) : "") +
              "</div>";
          });
          body += "</li>";
        });
        body += "</ul>";
      }
      var mods = entry.personalModifiers || [];
      if (mods.length) {
        body += '<h3 class="wf-subhead">Personal modifiers</h3><ul class="wf-mission-list">';
        mods.forEach(function (m) {
          body +=
            "<li><strong>" +
            esc(m.name || m.key) +
            "</strong>" +
            (m.description ? " — " + esc(m.description) : "") +
            "</li>";
        });
        body += "</ul>";
      }
      html += panel(archimedeaTitle(entry), "ops", body);
    });
    return html;
  }

  function renderNightwave(nw) {
    if (!nw) return "";
    var challenges = nw.activeChallenges || [];
    var body =
      '<p class="meta">Season ' +
      esc(nw.season != null ? nw.season : "?") +
      (nw.phase != null ? " · phase " + esc(nw.phase) : "") +
      (nw.expiry ? " · ends " + etaHtml(nw.expiry) : "") +
      "</p>";
    if (!challenges.length) {
      body += '<p class="wf-empty">No active challenges.</p>';
    } else {
      var daily = challenges.filter(function (c) {
        return c.isDaily;
      });
      var weekly = challenges.filter(function (c) {
        return !c.isDaily;
      });
      function list(items, label) {
        if (!items.length) return "";
        var h = '<h3 class="wf-subhead">' + label + "</h3><ul class=\"wf-mission-list\">";
        items.forEach(function (c) {
          h +=
            "<li><strong>" +
            esc(c.title || "Challenge") +
            "</strong>" +
            (c.isElite ? ' <span class="wf-tag elite">Elite</span>' : "") +
            (c.reputation != null ? ' <span class="meta">+' + esc(c.reputation) + "</span>" : "") +
            "<div class=\"meta\">" +
            esc(c.desc || "") +
            (c.expiry ? " · " + etaHtml(c.expiry) : "") +
            "</div></li>";
        });
        return h + "</ul>";
      }
      body += list(daily, "Daily") + list(weekly, "Weekly / other");
    }
    return panel("Nightwave", "ops", body);
  }

  function renderDaily(map) {
    var cards = [];
    var sp = map["/steelPath"];
    if (sp) {
      var reward = sp.currentReward;
      var rewardName =
        reward && typeof reward === "object" ? reward.name || "?" : String(reward || "?");
      cards.push(
        '<div class="wf-mini-card"><strong>Steel Path</strong><span>' +
          esc(rewardName) +
          "</span><span>" +
          etaHtml(sp.expiry) +
          " left</span></div>"
      );
    }
    var arb = map["/arbitration"];
    if (arb && !arb.expired) {
      cards.push(
        '<div class="wf-mini-card"><strong>Arbitration</strong><span>' +
          esc(arb.node || "?") +
          " · " +
          esc(arb.type || "") +
          "</span><span>" +
          esc(arb.enemy || "") +
          (arb.expiry ? " · " + etaHtml(arb.expiry) : "") +
          "</span></div>"
      );
    }
    var so = map["/sentientOutposts"];
    if (so && so.active && so.mission) {
      cards.push(
        '<div class="wf-mini-card"><strong>Sentient anomaly</strong><span>' +
          esc(so.mission.node || so.node || "?") +
          " · " +
          esc(so.mission.type || "") +
          "</span><span>" +
          esc(so.mission.faction || "") +
          "</span></div>"
      );
    }
    var sim = map["/simaris"];
    if (sim && sim.target) {
      cards.push(
        '<div class="wf-mini-card"><strong>Simaris</strong><span>' +
          esc(sim.target) +
          "</span><span>" +
          (sim.isTargetActive ? "Target active" : "Synthesis idle") +
          "</span></div>"
      );
    }
    var html = "";
    if (cards.length) {
      html += panel("Daily ops", "ops", '<div class="wf-mini-row">' + cards.join("") + "</div>");
    }
    html += renderNightwave(map["/nightwave"]);
    html += renderKuva(map["/kuva"]);
    html += renderPersistent(map["/persistentEnemies"]);
    html += renderUpgrades(map["/globalUpgrades"]);
    return html;
  }

  function renderKuva(list) {
    if (!list || !list.length) return "";
    var body = '<ul class="wf-mission-list">';
    list.slice(0, 12).forEach(function (k) {
      body +=
        "<li><strong>" +
        esc(k.node || k.enemy || "Kuva") +
        "</strong>" +
        (k.type || k.missionType ? " · " + esc(k.type || k.missionType) : "") +
        (k.expiry ? " · " + etaHtml(k.expiry) : "") +
        "</li>";
    });
    body += "</ul>";
    return panel("Kuva missions", "ops", body);
  }

  function renderPersistent(list) {
    if (!list || !list.length) return "";
    var body = '<ul class="wf-mission-list">';
    list.forEach(function (e) {
      body +=
        "<li><strong>" +
        esc(e.agentType || e.discordId || "Acolyte") +
        "</strong>" +
        (e.lastDiscoveredAt ? " · last seen " + esc(e.lastDiscoveredAt) : "") +
        (e.healthPercent != null ? " · " + Math.round(e.healthPercent) + "% HP" : "") +
        (e.region ? " · " + esc(e.region) : "") +
        "</li>";
    });
    body += "</ul>";
    return panel("Acolytes / persistent", "alert", body);
  }

  function renderUpgrades(list) {
    if (!list || !list.length) return "";
    var active = list.filter(function (u) {
      return !u.expired && isActiveWindow(u.start || u.activation, u.end || u.expiry);
    });
    if (!active.length) active = list;
    var body = '<ul class="wf-mission-list">';
    active.forEach(function (u) {
      body +=
        "<li><strong>" +
        esc(u.upgrade || u.description || u.operationType || "Upgrade") +
        "</strong>" +
        (u.upgradeOperationValue != null ? " · ×" + esc(u.upgradeOperationValue) : "") +
        (u.end || u.expiry ? " · " + etaHtml(u.end || u.expiry) + " left" : "") +
        "</li>";
    });
    body += "</ul>";
    return panel("Global upgrades", "build", body);
  }

  function renderConclave(list) {
    if (!list || !list.length) return "";
    var body = '<ul class="wf-mission-list">';
    list.forEach(function (c) {
      body +=
        "<li><strong>" +
        esc(c.title || "Challenge") +
        "</strong>" +
        (c.daily ? ' <span class="wf-tag">Daily</span>' : "") +
        ' <span class="meta">' +
        esc(c.category || "") +
        (c.mode ? " · " + esc(c.mode) : "") +
        "</span><div class=\"meta\">" +
        esc(c.description || "") +
        (c.amount != null ? " (" + esc(c.amount) + ")" : "") +
        (c.expiry ? " · " + etaHtml(c.expiry) : "") +
        "</div></li>";
    });
    body += "</ul>";
    return panel("Conclave", "ops", body);
  }

  function renderBountiesAndConclave(syndicates, conclave) {
    var html = band("wf-bounties", "Bounties");
    if (!syndicates || !syndicates.length) {
      html += panel("Syndicate bounties", "bounty", '<p class="wf-empty">No syndicate data.</p>');
    } else {
      var withJobs = syndicates.filter(function (s) {
        return (s.jobs || []).length;
      });
      var preferred = withJobs.length
        ? withJobs
        : syndicates.filter(function (s) {
            return BOUNTY_SYNDICATES.indexOf(s.syndicate) >= 0;
          });
      var body = "";
      preferred.forEach(function (s) {
        var jobs = s.jobs || [];
        body += '<div class="wf-bounty-block"><h3>' + esc(s.syndicate || "Syndicate") + "</h3>";
        body +=
          '<p class="meta">' +
          (s.expiry ? "Resets " + etaHtml(s.expiry) : "Active") +
          (jobs.length ? " · " + jobs.length + " jobs" : "") +
          "</p>";
        if (jobs.length) {
          body += '<ul class="wf-mission-list">';
          jobs.forEach(function (j) {
            var levels = (j.enemyLevels || []).join("–");
            var rewards = (j.rewardPool || []).slice(0, 4).join(", ");
            body +=
              "<li><strong>" +
              esc(j.type || "Bounty") +
              "</strong>" +
              (levels ? " · lv " + esc(levels) : "") +
              (j.minMR != null ? " · MR " + esc(j.minMR) + "+" : "") +
              (rewards
                ? '<div class="meta">Pool: ' +
                  esc(rewards) +
                  ((j.rewardPool || []).length > 4 ? "…" : "") +
                  "</div>"
                : "") +
              "</li>";
          });
          body += "</ul>";
        } else if ((s.nodes || []).length) {
          body += '<p class="meta">Nodes: ' + esc((s.nodes || []).slice(0, 8).join(", ")) + "</p>";
        } else {
          body += '<p class="meta">No jobs listed this cycle.</p>';
        }
        body += "</div>";
      });
      var nodesOnly = syndicates.filter(function (s) {
        return !(s.jobs || []).length && (s.nodes || []).length && preferred.indexOf(s) < 0;
      });
      if (nodesOnly.length) {
        body += '<h3 class="wf-subhead">Faction death squads</h3><ul class="wf-mission-list">';
        nodesOnly.slice(0, 8).forEach(function (s) {
          body +=
            "<li><strong>" +
            esc(s.syndicate) +
            "</strong> · " +
            esc((s.nodes || []).slice(0, 4).join(", ")) +
            ((s.nodes || []).length > 4 ? "…" : "") +
            "</li>";
        });
        body += "</ul>";
      }
      html += panel("Syndicate bounties", "bounty", body || '<p class="wf-empty">No bounties.</p>');
    }
    html += renderConclave(conclave);
    return html + "</div>";
  }

  function eventProgress(ev) {
    if (ev.health != null && !isNaN(Number(ev.health))) {
      return Math.max(0, Math.min(100, Number(ev.health)));
    }
    if (ev.maximumScore && ev.currentScore != null) {
      return Math.max(0, Math.min(100, (Number(ev.currentScore) / Number(ev.maximumScore)) * 100));
    }
    return null;
  }

  function renderEvents(list, construction) {
    var html = band("wf-events", "Events");
    var hasEvents = list && list.length;
    var hasBuild =
      construction && (construction.fomorianProgress || construction.razorbackProgress);

    if (!hasEvents && !hasBuild) {
      return (
        html +
        panel("Events", "event", '<p class="wf-empty">No active events.</p>') +
        "</div>"
      );
    }

    if (hasEvents) {
      var body = "";
      list.forEach(function (ev) {
        var pct = eventProgress(ev);
        var rewardItems = [];
        (ev.rewards || []).forEach(function (r) {
          (r.items || []).forEach(function (it) {
            rewardItems.push(it);
          });
        });
        body += '<div class="wf-event-card"><h3>' + esc(ev.description || ev.tooltip || "Event") + "</h3>";
        body +=
          '<p class="meta">' +
          esc(ev.node || "") +
          (ev.expiry ? (ev.node ? " · " : "") + "ends in " + etaHtml(ev.expiry) : "") +
          "</p>";
        if (ev.tooltip && ev.tooltip !== ev.description) {
          body += '<p class="wf-event-tip">' + esc(ev.tooltip) + "</p>";
        }
        if (pct != null) {
          body +=
            '<div class="wf-progress" role="progressbar" aria-valuenow="' +
            Math.round(pct) +
            '"><span style="width:' +
            pct.toFixed(1) +
            '%"></span></div><p class="meta">' +
            Math.round(pct) +
            "% complete</p>";
        }
        if (rewardItems.length) {
          body += '<p class="meta">Rewards: ' + esc(rewardItems.slice(0, 6).join(", ")) + "</p>";
        }
        body += "</div>";
      });
      html += panel("Events", "event", body);
    }

    if (hasBuild) {
      var build = "";
      [
        { label: "Fomorian", value: construction.fomorianProgress },
        { label: "Razorback", value: construction.razorbackProgress },
      ].forEach(function (b) {
        var n = Math.max(0, Math.min(100, parseFloat(b.value) || 0));
        build +=
          '<div class="wf-build-row"><span>' +
          esc(b.label) +
          '</span><div class="wf-progress"><span style="width:' +
          n.toFixed(1) +
          '%"></span></div><em>' +
          n.toFixed(1) +
          "%</em></div>";
      });
      html += panel("Construction", "build", build);
    }

    return html + "</div>";
  }

  function tierClass(tier) {
    var t = String(tier || "").toLowerCase();
    if (t.indexOf("lith") >= 0) return "tier-lith";
    if (t.indexOf("meso") >= 0) return "tier-meso";
    if (t.indexOf("neo") >= 0) return "tier-neo";
    if (t.indexOf("axi") >= 0) return "tier-axi";
    if (t.indexOf("requiem") >= 0) return "tier-requiem";
    if (t.indexOf("omnia") >= 0) return "tier-omnia";
    return "";
  }

  var TIER_ORDER = ["lith", "meso", "neo", "axi", "requiem", "omnia"];

  function tierRank(tier) {
    var t = String(tier || "").toLowerCase();
    for (var i = 0; i < TIER_ORDER.length; i++) {
      if (t.indexOf(TIER_ORDER[i]) >= 0) return i;
    }
    return TIER_ORDER.length;
  }

  function tierLabel(tier) {
    var t = String(tier || "").trim();
    if (!t) return "Other";
    var lower = t.toLowerCase();
    for (var i = 0; i < TIER_ORDER.length; i++) {
      if (lower.indexOf(TIER_ORDER[i]) >= 0) {
        return TIER_ORDER[i].charAt(0).toUpperCase() + TIER_ORDER[i].slice(1);
      }
    }
    return t;
  }

  function activeFissures(list) {
    return (list || []).filter(function (f) {
      return !f.expired;
    });
  }

  function sortFissures(list) {
    var sort = loadFissureSort();
    var arr = list.slice();
    arr.sort(function (a, b) {
      if (sort === "eta") {
        return (parseTime(a.expiry) || 0) - (parseTime(b.expiry) || 0);
      }
      var ra = tierRank(a.tier || a.tierNum);
      var rb = tierRank(b.tier || b.tierNum);
      if (ra !== rb) return ra - rb;
      return (parseTime(a.expiry) || 0) - (parseTime(b.expiry) || 0);
    });
    return arr;
  }

  function filterFissures(list) {
    var tiers = loadFissureTiers();
    var mission = loadFissureMission();
    var mode = loadFissureMode();
    return sortFissures(
      list.filter(function (f) {
        var label = tierLabel(f.tier || f.tierNum);
        if (tiers.indexOf(label) < 0) return false;
        if (mission && String(f.missionType || "") !== mission) return false;
        if (mode === "hard" && !f.isHard) return false;
        if (mode === "storm" && !f.isStorm) return false;
        if (mode === "normal" && (f.isHard || f.isStorm)) return false;
        return true;
      })
    );
  }

  function missionTypeCounts(list) {
    var counts = {};
    list.forEach(function (f) {
      var t = f.missionType || "Other";
      counts[t] = (counts[t] || 0) + 1;
    });
    return Object.keys(counts)
      .sort()
      .map(function (k) {
        return { type: k, count: counts[k] };
      });
  }

  function renderFissureFilters(list) {
    var selectedTiers = loadFissureTiers();
    var selectedMission = loadFissureMission();
    var selectedMode = loadFissureMode();
    var selectedSort = loadFissureSort();
    var tierScoped = list.filter(function (f) {
      return selectedTiers.indexOf(tierLabel(f.tier || f.tierNum)) >= 0;
    });
    var types = missionTypeCounts(tierScoped);

    var html = '<div class="wf-fissure-filters" id="wf-fissure-filters">';
    html += '<div class="wf-filter-row"><span class="wf-filter-label">Relic tier</span><div class="wf-filter-chips" data-filter="tiers">';
    ALL_FISSURE_TIERS.forEach(function (t) {
      var on = selectedTiers.indexOf(t) >= 0;
      html +=
        '<button type="button" class="wf-filter-chip ' +
        tierClass(t) +
        (on ? " on" : "") +
        '" data-tier="' +
        esc(t) +
        '" aria-pressed="' +
        (on ? "true" : "false") +
        '">' +
        esc(t) +
        "</button>";
    });
    html += "</div></div>";

    html +=
      '<div class="wf-filter-row"><span class="wf-filter-label">Mission type</span>' +
      '<select id="wf-fissure-mission" class="wf-filter-select" aria-label="Filter by mission type">' +
      '<option value="">All missions (' +
      tierScoped.length +
      ")</option>";
    types.forEach(function (t) {
      html +=
        '<option value="' +
        esc(t.type) +
        '"' +
        (selectedMission === t.type ? " selected" : "") +
        ">" +
        esc(t.type) +
        " (" +
        t.count +
        ")</option>";
    });
    html += "</select></div>";

    html += '<div class="wf-filter-row"><span class="wf-filter-label">Mode</span><div class="wf-filter-chips">';
    [
      ["all", "All"],
      ["normal", "Normal"],
      ["hard", "Steel Path"],
      ["storm", "Storm"],
    ].forEach(function (pair) {
      var on = selectedMode === pair[0];
      html +=
        '<button type="button" class="wf-filter-chip' +
        (on ? " on" : "") +
        '" data-mode="' +
        pair[0] +
        '" aria-pressed="' +
        (on ? "true" : "false") +
        '">' +
        pair[1] +
        "</button>";
    });
    html += "</div></div>";

    html += '<div class="wf-filter-row"><span class="wf-filter-label">Sort</span><div class="wf-filter-chips">';
    [
      ["tier", "By tier"],
      ["eta", "By time left"],
    ].forEach(function (pair) {
      var on = selectedSort === pair[0];
      html +=
        '<button type="button" class="wf-filter-chip' +
        (on ? " on" : "") +
        '" data-sort="' +
        pair[0] +
        '" aria-pressed="' +
        (on ? "true" : "false") +
        '">' +
        pair[1] +
        "</button>";
    });
    html += "</div></div>";

    if (types.length) {
      html += '<div class="wf-mission-summary">';
      types.forEach(function (t) {
        html +=
          '<button type="button" class="wf-mission-pill' +
          (selectedMission === t.type ? " on" : "") +
          '" data-mission="' +
          esc(t.type) +
          '">' +
          esc(t.type) +
          " <em>" +
          t.count +
          "</em></button>";
      });
      html += "</div>";
    }
    html += "</div>";
    return html;
  }

  function renderFissureList(filtered) {
    if (!filtered.length) return '<p class="wf-empty">No fissures match these filters.</p>';
    var sort = loadFissureSort();
    if (sort === "eta") {
      var html = '<div class="wf-chips">';
      filtered.forEach(function (f) {
        var tier = f.tier || f.tierNum || "?";
        var node = f.node || "?";
        html +=
          '<span class="wf-chip ' +
          tierClass(tier) +
          '"><span class="tier">' +
          esc(tier) +
          "</span>" +
          esc(node) +
          "<em>" +
          esc(f.missionType || "") +
          (f.enemy ? " · " + esc(f.enemy) : "") +
          (f.isStorm ? " · Storm" : "") +
          (f.isHard ? " · SP" : "") +
          (f.expiry ? " · " + timeUntil(f.expiry) : "") +
          '</em><button type="button" class="wf-copy" data-copy="' +
          esc(node) +
          '" title="Copy node">Copy</button></span>';
      });
      return html + "</div>";
    }

    var groups = [];
    var currentKey = null;
    var currentItems = null;
    filtered.forEach(function (f) {
      var label = tierLabel(f.tier || f.tierNum);
      if (label !== currentKey) {
        currentKey = label;
        currentItems = [];
        groups.push({ label: label, tier: f.tier || f.tierNum, items: currentItems });
      }
      currentItems.push(f);
    });

    var out = "";
    groups.forEach(function (g) {
      out +=
        '<div class="wf-fissure-group"><h3 class="wf-fissure-tier ' +
        esc(tierClass(g.tier)) +
        '">' +
        esc(g.label) +
        ' <span class="count">' +
        g.items.length +
        "</span></h3><div class=\"wf-chips\">";
      g.items.forEach(function (f) {
        var tier = f.tier || f.tierNum || "?";
        var node = f.node || "?";
        out +=
          '<span class="wf-chip ' +
          tierClass(tier) +
          '"><span class="tier">' +
          esc(tier) +
          "</span>" +
          esc(node) +
          "<em>" +
          esc(f.missionType || "") +
          (f.enemy ? " · " + esc(f.enemy) : "") +
          (f.isStorm ? " · Storm" : "") +
          (f.isHard ? " · SP" : "") +
          (f.expiry ? " · " + timeUntil(f.expiry) : "") +
          '</em><button type="button" class="wf-copy" data-copy="' +
          esc(node) +
          '" title="Copy node">Copy</button></span>';
      });
      out += "</div></div>";
    });
    return out;
  }

  function renderFissures(list) {
    lastFissures = activeFissures(list);
    var filtered = filterFissures(lastFissures);
    var body = "";
    if (!lastFissures.length) {
      body = '<p class="wf-empty">No fissures right now.</p>';
    } else {
      body += renderFissureFilters(lastFissures);
      body +=
        '<p class="meta wf-fissure-count" id="wf-fissure-count">Showing ' +
        filtered.length +
        " of " +
        lastFissures.length +
        " active</p>";
      body += '<div id="wf-fissure-list">' + renderFissureList(filtered) + "</div>";
    }
    return band("wf-void", "Void") + panel("Void fissures", "void", body, { forceOpen: true }) + "</div>";
  }

  function refreshFissurePanel() {
    var filtersHost = document.getElementById("wf-fissure-filters");
    var listHost = document.getElementById("wf-fissure-list");
    var countEl = document.getElementById("wf-fissure-count");
    if (!listHost) return;
    var filtered = filterFissures(lastFissures);
    if (filtersHost) {
      filtersHost.outerHTML = renderFissureFilters(lastFissures);
    }
    listHost.innerHTML = renderFissureList(filtered);
    if (countEl) {
      countEl.textContent = "Showing " + filtered.length + " of " + lastFissures.length + " active";
    }
    bindFissureFilters();
  }

  function bindFissureFilters() {
    var host = document.getElementById("wf-fissure-filters");
    if (host) {
      host.querySelectorAll("[data-tier]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var tier = btn.getAttribute("data-tier");
          var tiers = loadFissureTiers();
          var idx = tiers.indexOf(tier);
          if (idx >= 0) {
            if (tiers.length === 1) return;
            tiers.splice(idx, 1);
          } else {
            tiers.push(tier);
            tiers = ALL_FISSURE_TIERS.filter(function (t) {
              return tiers.indexOf(t) >= 0;
            });
          }
          saveFissureTiers(tiers);
          var scoped = lastFissures.filter(function (f) {
            return tiers.indexOf(tierLabel(f.tier || f.tierNum)) >= 0;
          });
          var mission = loadFissureMission();
          if (
            mission &&
            !scoped.some(function (f) {
              return f.missionType === mission;
            })
          ) {
            saveFissureMission("");
          }
          refreshFissurePanel();
        });
      });
      host.querySelectorAll("[data-mode]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          saveFissureMode(btn.getAttribute("data-mode") || "all");
          refreshFissurePanel();
        });
      });
      host.querySelectorAll("[data-sort]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          saveFissureSort(btn.getAttribute("data-sort") || "tier");
          refreshFissurePanel();
        });
      });
      host.querySelectorAll("[data-mission]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var m = btn.getAttribute("data-mission") || "";
          saveFissureMission(loadFissureMission() === m ? "" : m);
          refreshFissurePanel();
        });
      });
      var select = document.getElementById("wf-fissure-mission");
      if (select) {
        select.addEventListener("change", function () {
          saveFissureMission(select.value || "");
          refreshFissurePanel();
        });
      }
    }
    document.querySelectorAll(".wf-copy[data-copy]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var text = btn.getAttribute("data-copy") || "";
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(
            function () {
              btn.textContent = "Copied";
              setTimeout(function () {
                btn.textContent = "Copy";
              }, 1200);
            },
            function () {}
          );
        }
      });
    });
  }

  function renderFlashSales(list) {
    if (!list || !list.length) return "";
    var now = Date.now();
    var items = list
      .filter(function (s) {
        if (s.isShownInMarket === false) return false;
        var exp = parseTime(s.expiry);
        return exp == null || exp > now;
      })
      .slice(0, 16);
    if (!items.length) return "";
    var body = '<ul class="wf-mission-list">';
    items.forEach(function (s) {
      body +=
        "<li><strong>" +
        esc(s.item || "?") +
        "</strong>" +
        (s.discount != null ? " · −" + esc(s.discount) + "%" : "") +
        (s.expiry && parseTime(s.expiry) < now + 86400000 * 60
          ? " · " + etaHtml(s.expiry) + " left"
          : "") +
        "</li>";
    });
    body += "</ul>";
    return panel("Flash sales", "market", body);
  }

  function flattenRivens(data) {
    var rows = [];
    if (!data || typeof data !== "object") return rows;
    Object.keys(data).forEach(function (cat) {
      var weapons = data[cat];
      if (!weapons || typeof weapons !== "object") return;
      Object.keys(weapons).forEach(function (name) {
        var variants = weapons[name];
        if (!variants || typeof variants !== "object") return;
        ["unrolled", "rerolled"].forEach(function (kind) {
          var stats = variants[kind];
          if (!stats) return;
          rows.push({
            category: cat,
            name: name,
            kind: kind,
            median: stats.median,
            avg: stats.avg,
            min: stats.min,
            max: stats.max,
            pop: stats.pop,
          });
        });
      });
    });
    return rows;
  }

  function renderRivens(data) {
    lastRivens = flattenRivens(data);
    if (!lastRivens.length) return "";
    var cats = [];
    lastRivens.forEach(function (r) {
      if (cats.indexOf(r.category) < 0) cats.push(r.category);
    });
    var body =
      '<div class="wf-riven-tools">' +
      '<input type="search" id="wf-riven-q" class="wf-filter-select wf-riven-search" placeholder="Search weapon…" aria-label="Search rivens" />' +
      '<select id="wf-riven-cat" class="wf-filter-select" aria-label="Riven category"><option value="">All categories</option>';
    cats.forEach(function (c) {
      body += '<option value="' + esc(c) + '">' + esc(c.replace(" Riven Mod", "")) + "</option>";
    });
    body +=
      "</select></div>" +
      '<p class="meta">Community trade medians (platinum). Not disposition values.</p>' +
      '<div id="wf-riven-list"></div>';
    return panel("Riven prices", "market", body);
  }

  function bindRivens() {
    var q = document.getElementById("wf-riven-q");
    var cat = document.getElementById("wf-riven-cat");
    var list = document.getElementById("wf-riven-list");
    if (!list || !lastRivens) return;

    function paint() {
      var query = ((q && q.value) || "").trim().toLowerCase();
      var category = (cat && cat.value) || "";
      var rows = lastRivens.filter(function (r) {
        if (category && r.category !== category) return false;
        if (query && r.name.toLowerCase().indexOf(query) < 0) return false;
        return true;
      });
      rows.sort(function (a, b) {
        return (b.median || 0) - (a.median || 0);
      });
      rows = rows.slice(0, 40);
      if (!rows.length) {
        list.innerHTML = '<p class="wf-empty">No matches.</p>';
        return;
      }
      var html = '<ul class="wf-mission-list">';
      rows.forEach(function (r) {
        html +=
          "<li><strong>" +
          esc(r.name) +
          "</strong> · " +
          esc(r.kind) +
          ' <span class="meta">' +
          esc(r.category.replace(" Riven Mod", "")) +
          "</span><div class=\"meta\">median " +
          esc(r.median) +
          "p · avg " +
          esc(Math.round(r.avg || 0)) +
          "p · pop " +
          esc(r.pop || 0) +
          "</div></li>";
      });
      list.innerHTML = html + "</ul>";
    }

    if (q) q.addEventListener("input", paint);
    if (cat) cat.addEventListener("change", paint);
    paint();
  }

  function renderMarket(map) {
    var html = band("wf-market", "Market");
    var flash = renderFlashSales(map["/flashSales"]);
    var riv = renderRivens(map["/rivens"]);
    html += flash + riv;
    if (!flash && !riv) {
      html += panel("Market", "market", '<p class="wf-empty">No market extras right now.</p>');
    }
    return html + "</div>";
  }

  function renderAlerts(list) {
    if (!list || !list.length) return "";
    var body = '<ul class="wf-mission-list">';
    list.slice(0, 10).forEach(function (a) {
      var mission = a.mission || {};
      var reward = formatReward(mission.reward || a.reward);
      body +=
        "<li><strong>" +
        esc(mission.node || a.tag || "Alert") +
        "</strong> · " +
        esc(mission.type || "") +
        (mission.faction ? " · " + esc(mission.faction) : "") +
        (reward ? '<div class="meta">Reward: ' + esc(reward) + "</div>" : "") +
        (a.expiry ? '<div class="meta">' + etaHtml(a.expiry) + " left</div>" : "") +
        "</li>";
    });
    body += "</ul>";
    return panel("Alerts", "alert", body);
  }

  function renderInvasions(list) {
    var open = (list || [])
      .filter(function (i) {
        return !i.completed;
      })
      .slice(0, 12);
    var body = "";
    if (!open.length) {
      body = '<p class="wf-empty">No active invasions.</p>';
    } else {
      open.forEach(function (i) {
        var pct = i.completion != null ? Math.max(0, Math.min(100, Number(i.completion))) : 0;
        var atk = i.attacker || {};
        var def = i.defender || {};
        var atkR = formatReward(atk.reward);
        var defR = formatReward(def.reward);
        body += '<div class="wf-invasion-card">';
        body +=
          "<h3>" +
          esc(i.node || "?") +
          '</h3><p class="meta">' +
          esc(i.desc || "") +
          (i.vsInfestation ? " · vs Infested" : "") +
          "</p>";
        body +=
          '<div class="wf-invasion-sides"><div><strong>' +
          esc(atk.faction || "Attacker") +
          "</strong><span>" +
          esc(atkR || "—") +
          "</span></div><div><strong>" +
          esc(def.faction || "Defender") +
          "</strong><span>" +
          esc(defR || "—") +
          "</span></div></div>";
        body +=
          '<div class="wf-progress" role="progressbar" aria-valuenow="' +
          Math.round(pct) +
          '"><span style="width:' +
          pct.toFixed(1) +
          '%"></span></div>';
        body += '<p class="meta">' + Math.round(pct) + "% complete</p></div>";
      });
    }
    return (
      band("wf-invasions", "Invasions") +
      panel("Invasions", "invasion", body, { forceOpen: true }) +
      "</div>"
    );
  }

  function newsMessage(n) {
    if (n.translations && n.translations[lang]) return n.translations[lang];
    if (n.translations && n.translations.en) return n.translations.en;
    return n.message || "News";
  }

  function renderNews(list) {
    var items = (list || [])
      .filter(function (n) {
        var t = parseTime(n.date);
        return t == null || t > Date.parse("2000-01-01");
      })
      .slice()
      .sort(function (a, b) {
        return (parseTime(b.date) || 0) - (parseTime(a.date) || 0);
      })
      .slice(0, 10);
    var body = "";
    if (!items.length) {
      body = '<p class="wf-empty">No recent news.</p>';
    } else {
      body = '<ul class="wf-news-list">';
      items.forEach(function (n) {
        var msg = newsMessage(n);
        var tags = [];
        if (n.update) tags.push("Update");
        if (n.primeAccess) tags.push("Prime Access");
        if (n.stream) tags.push("Stream");
        if (n.priority) tags.push("Priority");
        body += "<li>";
        if (n.link) {
          body +=
            '<a href="' +
            esc(n.link) +
            '" target="_blank" rel="noopener noreferrer">' +
            esc(msg) +
            "</a>";
        } else {
          body += "<strong>" + esc(msg) + "</strong>";
        }
        if (tags.length || n.date) {
          body +=
            ' <span class="meta">' +
            (tags.length ? esc(tags.join(" · ")) : "") +
            (tags.length && n.date ? " · " : "") +
            (n.date ? esc(new Date(n.date).toLocaleDateString()) : "") +
            "</span>";
        }
        body += "</li>";
      });
      body += "</ul>";
    }
    return band("wf-news", "News") + panel("News", "news", body) + "</div>";
  }

  function skeleton() {
    return (
      '<div class="wf-skel-grid"><div class="wf-skel-card tall"></div><div class="wf-skel-row">' +
      '<div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div>' +
      '</div><div class="wf-skel-card"></div><div class="wf-skel-card"></div></div>'
    );
  }

  function tickEtas() {
    document.querySelectorAll(".wf-eta[data-expiry]").forEach(function (node) {
      var iso = node.getAttribute("data-expiry");
      if (iso) node.textContent = timeUntil(iso);
    });
  }

  function setAllCollapsed(collapsed) {
    saveCollapsedPrefer(collapsed);
    document.querySelectorAll("details.wf-collapse").forEach(function (d) {
      d.open = !collapsed;
    });
    if (collapseBtn) collapseBtn.textContent = collapsed ? "Expand" : "Collapse";
  }

  function render(bundle) {
    if (!root) return;
    lastBundle = bundle;
    var map = bundle.map;
    updateTeaser(map);

    var html = "";
    html += renderBaro(map["/voidTrader"]);
    var side = renderVarzia(map["/vaultTrader"]) + renderDarvo(map["/dailyDeals"]);
    if (side) html += '<div class="wf-grid-2" style="margin-top:16px">' + side + "</div>";
    html += "</div>";
    html += renderCycles(map);
    html += band("wf-missions", "Missions");
    html += '<div class="wf-grid-2">';
    html += renderMission("Sortie", map["/sortie"], "sortie");
    html += renderMission("Archon hunt", map["/archonHunt"], "archon");
    html += "</div>";
    html += renderArchimedeas(map["/archimedeas"]);
    html += renderDaily(map);
    html += "</div>";
    html += renderBountiesAndConclave(map["/syndicateMissions"], map["/conclaveChallenges"]);
    html += renderEvents(map["/events"], map["/constructionProgress"]);
    html += renderFissures(map["/fissures"]);
    html += renderMarket(map);
    html += renderNews(map["/news"]);
    html += renderAlerts(map["/alerts"]);
    html += renderInvasions(map["/invasions"]);
    root.innerHTML = html;
    root.removeAttribute("aria-busy");
    bindFissureFilters();
    bindRivens();
    if (collapseBtn) collapseBtn.textContent = collapsedPrefer ? "Expand" : "Collapse";
    scrollPendingSection();

    var platName = PLATFORMS[platform] || "PC";
    if (bundle.fails === 0) {
      setStatus(true, "Live · " + platName + " · " + lang.toUpperCase() + " · " + new Date().toLocaleTimeString());
    } else if (bundle.fails < bundle.total) {
      setStatus(
        true,
        "Partial · " + bundle.fails + " failed · " + platName + " · " + new Date().toLocaleTimeString()
      );
    } else {
      setStatus(false, "Could not reach Warframe world-state API");
    }
  }

  function refresh() {
    setStatus(true, "Refreshing…");
    if (root && !root.dataset.ready) root.innerHTML = skeleton();
    return loadAll()
      .then(function (bundle) {
        if (root) root.dataset.ready = "1";
        render(bundle);
      })
      .catch(function () {
        setStatus(false, "Could not reach Warframe world-state API");
        if (root && !root.dataset.ready) {
          root.innerHTML = '<p class="wf-empty">Unable to load world state. Try again in a moment.</p>';
        }
      });
  }

  applyDense(lsGet(DENSE_KEY, "0") === "1");
  applyDeepLinks();
  savePlatform(platform);
  saveLang(lang);

  if (platformSelect) {
    platformSelect.value = platform;
    platformSelect.addEventListener("change", function () {
      savePlatform(platformSelect.value);
      if (root) delete root.dataset.ready;
      refresh();
    });
  }

  if (langSelect) {
    langSelect.value = lang;
    langSelect.addEventListener("change", function () {
      saveLang(langSelect.value);
      if (root) delete root.dataset.ready;
      refresh();
    });
  }

  if (denseBtn) {
    denseBtn.addEventListener("click", function () {
      applyDense(!document.body.classList.contains("wf-dense"));
    });
  }

  if (collapseBtn) {
    collapseBtn.addEventListener("click", function () {
      setAllCollapsed(!collapsedPrefer);
    });
  }

  if (refreshBtn) {
    refreshBtn.addEventListener("click", function () {
      refresh();
    });
  }

  refresh();
  timer = setInterval(refresh, REFRESH_MS);
  tickTimer = setInterval(tickEtas, 15000);
  window.addEventListener("beforeunload", function () {
    if (timer) clearInterval(timer);
    if (tickTimer) clearInterval(tickTimer);
  });
})();
