/**
 * Public Warframe world-state page — fetches api.warframestat.us (no bot login).
 */
(function () {
  var API_HOST = "https://api.warframestat.us";
  var CDN_IMG = "https://cdn.warframestat.us/img/";
  var ITEM_IMG_LS = "oo_wf_item_img_v1";
  var REFRESH_MS = 60 * 1000;
  var SOON_MS = 30 * 60 * 1000;
  var URGENT_MS = 15 * 60 * 1000;
  var PLATFORM_KEY = "oo_wf_platform";
  var LANG_KEY = "oo_wf_lang";
  var DENSE_KEY = "oo_wf_dense";
  var COLLAPSE_KEY = "oo_wf_collapsed";
  var FISSURE_TIERS_KEY = "oo_wf_fissure_tiers";
  var FISSURE_MISSION_KEY = "oo_wf_fissure_mission";
  var FISSURE_MODE_KEY = "oo_wf_fissure_mode";
  var FISSURE_SORT_KEY = "oo_wf_fissure_sort";
  var FISSURE_PLANET_KEY = "oo_wf_fissure_planet";
  var WATCH_KEY = "oo_wf_watch";
  var WATCH_ONLY_KEY = "oo_wf_watch_only";
  var PINS_KEY = "oo_wf_pins";
  var PANELS_KEY = "oo_wf_panels";
  var TV_KEY = "oo_wf_tv";

  var PLATFORMS = { pc: "PC", ps4: "PlayStation", xb1: "Xbox", swi: "Switch" };
  var LANGS = ["en", "de", "es", "fr", "pt", "ru", "zh", "ko", "tc", "uk"];
  var DEFAULT_FISSURE_TIERS = ["Lith", "Meso", "Neo", "Axi"];
  var ALL_FISSURE_TIERS = ["Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia"];
  var BAND_ORDER = ["wf-trader", "wf-cycles", "wf-missions", "wf-bounties", "wf-events", "wf-void", "wf-market", "wf-news", "wf-invasions"];
  var BOUNTY_SYNDICATES = ["Ostrons", "Solaris United", "Entrati", "The Holdfasts", "Cavia", "Kahl's Garrison", "The Hex"];
  var WS_KEY_MAP = {
    voidTrader: "/voidTrader", vaultTrader: "/vaultTrader", dailyDeals: "/dailyDeals",
    cetusCycle: "/cetusCycle", vallisCycle: "/vallisCycle", cambionCycle: "/cambionCycle",
    earthCycle: "/earthCycle", duviriCycle: "/duviriCycle", zarimanCycle: "/zarimanCycle",
    sortie: "/sortie", archonHunt: "/archonHunt", steelPath: "/steelPath", arbitration: "/arbitration",
    nightwave: "/nightwave", archimedeas: "/archimedeas", events: "/events",
    constructionProgress: "/constructionProgress", fissures: "/fissures", alerts: "/alerts",
    invasions: "/invasions", news: "/news", sentientOutposts: "/sentientOutposts",
    syndicateMissions: "/syndicateMissions", conclaveChallenges: "/conclaveChallenges",
    flashSales: "/flashSales", globalUpgrades: "/globalUpgrades", simaris: "/simaris",
    kuva: "/kuva", persistentEnemies: "/persistentEnemies"
  };

  var root = document.getElementById("wf-root");
  var statusEl = document.getElementById("wf-status");
  var teaserEl = document.getElementById("wf-teaser");
  var staleEl = document.getElementById("wf-stale");
  var soonEl = document.getElementById("wf-soon");
  var refreshBtn = document.getElementById("wf-refresh");
  var platformSelect = document.getElementById("wf-platform");
  var langSelect = document.getElementById("wf-lang");
  var denseBtn = document.getElementById("wf-dense");
  var collapseBtn = document.getElementById("wf-collapse-all");
  var platformLabel = document.getElementById("wf-platform-label");
  var tvBtn = document.getElementById("wf-tv");
  var timer = null;
  var tickTimer = null;
  var jumpObs = null;
  var lastBundle = null;
  var lastFissures = [];
  var lastRivens = null;
  var lastBaroInv = [];
  var lastUpdateTime = null;
  var panelSeq = 0;
  var collapsedPrefer = loadCollapsedPrefer();
  var platform = loadPlatform();
  var lang = loadLang();
  var pendingSection = null;
  var rivensLoading = false;

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
    pin: '<svg viewBox="0 0 24 24"><path d="M12 17v5M9 3h6l1 7h4l-5 6v-3H9v3L4 10h4l1-7z"/></svg>'
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
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

  function etaUrgencyClass(iso) {
    var t = parseTime(iso);
    if (t == null) return "";
    var ms = t - Date.now();
    if (ms > 0 && ms < URGENT_MS) return " urgent";
    if (ms > 0 && ms < SOON_MS) return " soonish";
    return "";
  }

  function etaTitle(iso) {
    var t = parseTime(iso);
    return t == null ? "" : new Date(t).toLocaleString();
  }

  function etaHtml(iso) {
    return '<span class="wf-eta tick' + etaUrgencyClass(iso) + '" data-expiry="' + esc(iso || "") + '" title="' + esc(etaTitle(iso)) + '">' + esc(timeUntil(iso)) + "</span>";
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
    try { var v = localStorage.getItem(key); return v == null ? fallback : v; } catch (e) { return fallback; }
  }

  function lsSet(key, value) {
    try { localStorage.setItem(key, value); } catch (e) {}
  }

  function lsGetJson(key, fallback) {
    try {
      var raw = lsGet(key, null);
      if (raw == null) return fallback;
      return JSON.parse(raw);
    } catch (e) { return fallback; }
  }

  function lsSetJson(key, value) {
    lsSet(key, JSON.stringify(value));
  }

  function factionClass(faction) {
    var f = String(faction || "").toLowerCase();
    if (f.indexOf("grineer") >= 0) return "faction-grineer";
    if (f.indexOf("corpus") >= 0) return "faction-corpus";
    if (f.indexOf("infest") >= 0) return "faction-infested";
    return "";
  }

  function thumbHtml(url, itemName) {
    if (url) {
      return (
        '<img class="wf-thumb" loading="lazy" alt="" src="' +
        esc(url) +
        '" onerror="this.remove()">'
      );
    }
    if (itemName) {
      return (
        '<img class="wf-thumb wf-thumb-pending" loading="lazy" alt="" data-wf-item="' +
        esc(itemName) +
        '" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">'
      );
    }
    return "";
  }

  function marketLink(name) {
    return "/market.html?q=" + encodeURIComponent(name || "");
  }

  function parseNodePlanet(node) {
    var m = String(node || "").match(/\(([^)]+)\)\s*$/);
    return m ? m[1] : "";
  }

  // Invasion/alert reward.thumbnail from warframestat is a guessed slug URL that 404s
  // (e.g. detonite-injector.png). Real icons use WFCD imageName (GrineerComponent.png).
  var itemImgCache = loadItemImgCache();

  function loadItemImgCache() {
    try {
      var raw = sessionStorage.getItem(ITEM_IMG_LS);
      if (!raw) return {};
      var parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function saveItemImgCache() {
    try {
      sessionStorage.setItem(ITEM_IMG_LS, JSON.stringify(itemImgCache));
    } catch (_) {}
  }

  function rewardItemName(reward) {
    if (!reward) return "";
    var counted = reward.countedItems || [];
    if (counted.length) {
      var c0 = counted[0];
      if (typeof c0 === "string") return c0;
      if (c0 && (c0.type || c0.key)) return String(c0.type || c0.key);
    }
    var items = reward.items || [];
    if (items.length) {
      var it0 = items[0];
      if (typeof it0 === "string") return it0;
      if (it0 && (it0.type || it0.name || it0.key)) return String(it0.type || it0.name || it0.key);
    }
    if (reward.itemString) return String(reward.itemString);
    return "";
  }

  function parentItemName(name) {
    return String(name || "")
      .replace(
        /\s+(Blueprint|Chassis|Neuroptics|Systems|Barrel|Receiver|Stock|Blade|Handle|Head|Link|Gauntlet|Grip|String|Lower Limb|Upper Limb|Hilt|Pouch|Stars|Boot|Ornament|Chain|Limb)$/i,
        ""
      )
      .trim();
  }

  function cdnFromImageName(imageName) {
    if (!imageName) return "";
    return CDN_IMG + String(imageName).replace(/^\/+/, "");
  }

  function pickItemImage(items, query) {
    if (!items || !items.length) return "";
    var q = String(query || "").toLowerCase();
    var scored = [];
    items.forEach(function (it) {
      if (!it || !it.imageName) return;
      var name = String(it.name || "").toLowerCase();
      var type = String(it.type || "").toLowerCase();
      var score = 0;
      if (name === q) score = 100;
      else if (name.indexOf(q) === 0) score = 80;
      else if (name.indexOf(q) >= 0 || q.indexOf(name) >= 0) score = 50;
      else score = 10;
      if (type === "resource" || type === "misc" || type === "component") score += 5;
      if (type === "skin") score -= 20;
      scored.push({ score: score, img: it.imageName });
    });
    if (!scored.length) return "";
    scored.sort(function (a, b) {
      return b.score - a.score;
    });
    return cdnFromImageName(scored[0].img);
  }

  function fetchItemImage(name) {
    var key = String(name || "")
      .trim()
      .toLowerCase();
    if (!key) return Promise.resolve("");
    if (Object.prototype.hasOwnProperty.call(itemImgCache, key)) {
      return Promise.resolve(itemImgCache[key] || "");
    }
    return fetch(API_HOST + "/items/search/" + encodeURIComponent(name) + "?language=en", {
      cache: "force-cache",
      headers: { Accept: "application/json" },
    })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (items) {
        var url = pickItemImage(items, name);
        if (!url) {
          var parent = parentItemName(name);
          if (parent && parent.toLowerCase() !== key) {
            return fetchItemImage(parent).then(function (parentUrl) {
              itemImgCache[key] = parentUrl || "";
              saveItemImgCache();
              return itemImgCache[key];
            });
          }
        }
        itemImgCache[key] = url || "";
        saveItemImgCache();
        return itemImgCache[key];
      })
      .catch(function () {
        itemImgCache[key] = "";
        saveItemImgCache();
        return "";
      });
  }

  function rewardThumb(reward) {
    var name = rewardItemName(reward);
    if (!name) return "";
    return itemImgCache[name.toLowerCase()] || "";
  }

  function thumbHtmlForReward(reward) {
    var name = rewardItemName(reward);
    if (!name) return "";
    return thumbHtml(rewardThumb(reward), name);
  }

  function hydrateRewardThumbs(scope) {
    var rootEl = scope || document;
    var imgs = rootEl.querySelectorAll("img.wf-thumb[data-wf-item]");
    if (!imgs.length) return;
    var names = [];
    imgs.forEach(function (img) {
      var n = img.getAttribute("data-wf-item");
      if (n && names.indexOf(n) < 0) names.push(n);
    });
    names.forEach(function (name) {
      fetchItemImage(name).then(function (url) {
        var attr =
          typeof CSS !== "undefined" && CSS.escape
            ? CSS.escape(name)
            : String(name).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
        var nodes = rootEl.querySelectorAll('img.wf-thumb[data-wf-item="' + attr + '"]');
        nodes.forEach(function (img) {
          if (!url) {
            img.remove();
            return;
          }
          img.src = url;
          img.removeAttribute("data-wf-item");
          img.classList.remove("wf-thumb-pending");
        });
      });
    });
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

  function loadPins() {
    var arr = lsGetJson(PINS_KEY, []);
    return Array.isArray(arr) ? arr.filter(function (id) { return BAND_ORDER.indexOf(id) >= 0; }) : [];
  }

  function savePins(pins) {
    lsSetJson(PINS_KEY, pins);
  }

  function loadPanels() {
    var m = lsGetJson(PANELS_KEY, {});
    return m && typeof m === "object" ? m : {};
  }

  function savePanels(map) {
    lsSetJson(PANELS_KEY, map || {});
  }

  function loadWatch() {
    var arr = lsGetJson(WATCH_KEY, []);
    return Array.isArray(arr) ? arr : [];
  }

  function saveWatch(arr) {
    lsSetJson(WATCH_KEY, arr);
  }

  function isWatched(node) {
    return loadWatch().indexOf(node) >= 0;
  }

  function loadWatchOnly() {
    return lsGet(WATCH_ONLY_KEY, "0") === "1";
  }

  function saveWatchOnly(on) {
    lsSet(WATCH_ONLY_KEY, on ? "1" : "0");
    syncUrlParams();
  }

  function applyDense(on) {
    document.body.classList.toggle("wf-dense", !!on);
    lsSet(DENSE_KEY, on ? "1" : "0");
    if (denseBtn) {
      denseBtn.setAttribute("aria-pressed", on ? "true" : "false");
      denseBtn.classList.toggle("on", !!on);
    }
  }

  function applyTv(on) {
    document.body.classList.toggle("wf-tv", !!on);
    lsSet(TV_KEY, on ? "1" : "0");
    if (tvBtn) {
      tvBtn.setAttribute("aria-pressed", on ? "true" : "false");
      tvBtn.classList.toggle("on", !!on);
    }
    syncUrlParams();
  }

  function loadTv() {
    return lsGet(TV_KEY, "0") === "1";
  }

  function setStale(show) {
    if (!staleEl) return;
    if (show && lastUpdateTime) {
      staleEl.hidden = false;
      staleEl.textContent = "Offline — showing cached data from " + new Date(lastUpdateTime).toLocaleString();
    } else {
      staleEl.hidden = true;
      staleEl.textContent = "";
    }
  }

  function syncUrlParams() {
    try {
      var url = new URL(window.location.href);
      url.searchParams.set("platform", platform);
      url.searchParams.set("lang", lang);
      if (document.body.classList.contains("wf-embed")) url.searchParams.set("embed", "1");
      else url.searchParams.delete("embed");
      if (document.body.classList.contains("wf-tv")) url.searchParams.set("tv", "1");
      else url.searchParams.delete("tv");
      var tiers = loadFissureTiers();
      if (tiers.join(",") !== DEFAULT_FISSURE_TIERS.join(",")) url.searchParams.set("tiers", tiers.join(","));
      else url.searchParams.delete("tiers");
      var mission = loadFissureMission();
      if (mission) url.searchParams.set("mission", mission); else url.searchParams.delete("mission");
      var mode = loadFissureMode();
      if (mode && mode !== "all") url.searchParams.set("mode", mode); else url.searchParams.delete("mode");
      var planet = loadFissurePlanet();
      if (planet) url.searchParams.set("planet", planet); else url.searchParams.delete("planet");
      var sort = loadFissureSort();
      if (sort && sort !== "tier") url.searchParams.set("sort", sort); else url.searchParams.delete("sort");
      if (loadWatchOnly()) url.searchParams.set("watch", "1"); else url.searchParams.delete("watch");
      history.replaceState(null, "", url.pathname + url.search + url.hash);
    } catch (e) {}
  }

  function applyDeepLinks() {
    try {
      var params = new URLSearchParams(window.location.search);
      var p = params.get("platform");
      var l = params.get("lang");
      var section = params.get("section");
      if (p && PLATFORMS[p]) { platform = p; lsSet(PLATFORM_KEY, platform); }
      if (l && LANGS.indexOf(l) >= 0) { lang = l; lsSet(LANG_KEY, lang); }
      if (params.get("embed") === "1") document.body.classList.add("wf-embed");
      if (params.get("tv") === "1" || loadTv()) applyTv(true);
      if (section) pendingSection = section.indexOf("wf-") === 0 ? section : "wf-" + section;
      if (params.has("tiers")) {
        var tiers = params.get("tiers").split(",").filter(function (t) { return ALL_FISSURE_TIERS.indexOf(t) >= 0; });
        if (tiers.length) saveFissureTiers(tiers);
      }
      if (params.has("mission")) saveFissureMission(params.get("mission") || "");
      if (params.has("mode")) saveFissureMode(params.get("mode") || "all");
      if (params.has("planet")) saveFissurePlanet(params.get("planet") || "");
      if (params.has("sort")) saveFissureSort(params.get("sort") || "tier");
      if (params.has("watch")) saveWatchOnly(params.get("watch") === "1");
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
    var pid = opts.id || ("wf-panel-" + (++panelSeq));
    var panels = loadPanels();
    var open = panels[pid] != null ? !!panels[pid] : (opts.forceOpen || !collapsedPrefer);
    return (
      '<details class="wf-panel wf-collapse' + (opts.cls ? " " + opts.cls : "") + '" data-panel-id="' + esc(pid) + '"' + (open ? " open" : "") + ">" +
      '<summary class="wf-panel-head"><span class="ico" aria-hidden="true">' + (ICO[ico] || ICO.ops) + "</span>" +
      "<h2>" + esc(title) + "</h2>" + (opts.cmd ? '<span class="wf-cmd meta">' + esc(opts.cmd) + "</span>" : "") +
      "</summary><div class=\"wf-panel-body\">" + bodyHtml + "</div></details>"
    );
  }

  function band(id, label) {
    var pins = loadPins();
    var pinned = pins.indexOf(id) >= 0;
    return (
      '<div class="wf-band" id="' + id + '"><div class="wf-band-label">' +
      '<button type="button" class="wf-pin' + (pinned ? " pinned" : "") + '" data-pin="' + esc(id) + '" aria-pressed="' + (pinned ? "true" : "false") + '" title="Pin section">' +
      (ICO.pin || "") + "</button>" + esc(label) + "</div>"
    );
  }

  function assembleBands(bands) {
    var pins = loadPins();
    var pinned = [];
    var unpinned = [];
    BAND_ORDER.forEach(function (id) {
      if (!bands[id]) return;
      if (pins.indexOf(id) >= 0) pinned.push({ id: id, html: bands[id], idx: pins.indexOf(id) });
      else unpinned.push(bands[id]);
    });
    pinned.sort(function (a, b) { return a.idx - b.idx; });
    var out = "";
    pinned.forEach(function (p) { out += p.html; });
    unpinned.forEach(function (h) { out += h; });
    return out;
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
      return arr.filter(function (t) { return ALL_FISSURE_TIERS.indexOf(t) >= 0; });
    } catch (e) { return DEFAULT_FISSURE_TIERS.slice(); }
  }

  function saveFissureTiers(tiers) { lsSet(FISSURE_TIERS_KEY, JSON.stringify(tiers)); syncUrlParams(); }
  function loadFissureMission() { return lsGet(FISSURE_MISSION_KEY, "") || ""; }
  function saveFissureMission(m) { lsSet(FISSURE_MISSION_KEY, m || ""); syncUrlParams(); }
  function loadFissureMode() {
    var m = lsGet(FISSURE_MODE_KEY, "all");
    return m === "normal" || m === "hard" || m === "storm" ? m : "all";
  }
  function saveFissureMode(m) { lsSet(FISSURE_MODE_KEY, m || "all"); syncUrlParams(); }
  function loadFissureSort() {
    var s = lsGet(FISSURE_SORT_KEY, "tier");
    return s === "eta" || s === "planet" ? s : "tier";
  }
  function saveFissureSort(s) {
    lsSet(FISSURE_SORT_KEY, s === "eta" || s === "planet" ? s : "tier");
    syncUrlParams();
  }
  function loadFissurePlanet() { return lsGet(FISSURE_PLANET_KEY, "") || ""; }
  function saveFissurePlanet(p) { lsSet(FISSURE_PLANET_KEY, p || ""); syncUrlParams(); }

  function apiBase() { return API_HOST + "/" + platform; }

  function fetchJson(path) {
    return fetch(apiBase() + path + (path.indexOf("?") >= 0 ? "&" : "?") + "language=" + encodeURIComponent(lang), {
      cache: "no-store", headers: { Accept: "application/json" }
    }).then(function (res) {
      if (!res.ok) throw new Error(path + " HTTP " + res.status);
      return res.json();
    });
  }

  function mapWorldState(data) {
    var map = {};
    Object.keys(WS_KEY_MAP).forEach(function (k) {
      map[WS_KEY_MAP[k]] = data && data[k] != null ? data[k] : null;
    });
    return map;
  }

  function loadAll() {
    return fetch(apiBase() + "?language=" + encodeURIComponent(lang), {
      cache: "no-store", headers: { Accept: "application/json" }
    }).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    }).then(function (data) {
      return { map: mapWorldState(data), fails: 0, total: Object.keys(WS_KEY_MAP).length };
    });
  }

  function fetchRivensIncremental() {
    if (rivensLoading) return;
    rivensLoading = true;
    fetchJson("/rivens").then(function (data) {
      if (lastBundle) lastBundle.map["/rivens"] = data;
      patchRivenHost(data);
    }).catch(function () {
      patchRivenHost(null);
    }).then(function () { rivensLoading = false; });
  }

  function patchRivenHost(data) {
    var host = document.getElementById("wf-riven-host");
    if (!host) return;
    var html = renderRivens(data);
    host.innerHTML = html || '<p class="wf-empty">Riven prices unavailable.</p>';
    bindRivens();
  }

  function cycleInfo(c, kind) {
    var mark = { cetus: "C", vallis: "V", cambion: "D", earth: "E", duviri: "U", zariman: "Z" }[kind] || "?";
    var name = { cetus: "Cetus", vallis: "Orb Vallis", cambion: "Cambion Drift", earth: "Earth", duviri: "Duviri", zariman: "Zariman" }[kind];
    if (!c) return { mark: mark, name: name, state: "—", tone: "", expiry: null };
    if (kind === "vallis") return { mark: mark, name: name, state: c.isWarm ? "Warm" : "Cold", tone: c.isWarm ? "warm" : "cold", expiry: c.expiry };
    if (kind === "cambion") {
      var st = String(c.state || "").toLowerCase();
      return { mark: mark, name: name, state: c.state || "—", tone: st.indexOf("vome") >= 0 ? "vome" : st.indexOf("fass") >= 0 ? "fass" : "", expiry: c.expiry };
    }
    if (kind === "duviri") return { mark: mark, name: name, state: c.state || "—", tone: "mood", expiry: c.expiry };
    if (kind === "zariman") {
      var zs = String(c.state || (c.isCorpus ? "corpus" : "grineer")).toLowerCase();
      return { mark: mark, name: name, state: c.state || (c.isCorpus ? "Corpus" : "Grineer"), tone: zs.indexOf("corpus") >= 0 ? "corpus" : "grineer", expiry: c.expiry, faction: zs.indexOf("corpus") >= 0 ? "corpus" : "grineer" };
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
      if (active) parts.push("<strong>Baro</strong> at " + esc(vt.location || "relay") + " · leaves " + etaHtml(vt.expiry));
      else if (vt.activation) parts.push("<strong>Baro</strong> next in " + etaHtml(vt.activation));
    }
    if (cetus) parts.push("<strong>Cetus</strong> " + esc(cetus.isDay ? "Day" : "Night") + " · " + etaHtml(cetus.expiry) + " left");
    if (!parts.length) { teaserEl.hidden = true; return; }
    teaserEl.innerHTML = parts.join('<span aria-hidden="true"> · </span>');
    teaserEl.hidden = false;
  }

  function collectSoonItems(map) {
    var items = [];
    function add(label, iso, href) {
      var t = parseTime(iso);
      if (t == null) return;
      var ms = t - Date.now();
      if (ms > 0 && ms < SOON_MS) items.push({ label: label, iso: iso, ms: ms, href: href || "" });
    }
    var cycles = [
      { c: map["/cetusCycle"], n: "Cetus" }, { c: map["/vallisCycle"], n: "Vallis" },
      { c: map["/cambionCycle"], n: "Cambion" }, { c: map["/earthCycle"], n: "Earth" },
      { c: map["/duviriCycle"], n: "Duviri" }, { c: map["/zarimanCycle"], n: "Zariman" }
    ];
    cycles.forEach(function (x) { if (x.c && x.c.expiry) add(x.n + " cycle", x.c.expiry, "#wf-cycles"); });
    var vt = map["/voidTrader"];
    if (vt) {
      var active = isActiveWindow(vt.activation, vt.expiry);
      add(active ? "Baro leaves" : "Baro arrives", active ? vt.expiry : vt.activation, "#wf-trader");
    }
    var arb = map["/arbitration"];
    if (arb && !arb.expired && arb.expiry) add("Arbitration", arb.expiry, "#wf-missions");
    (map["/fissures"] || []).filter(function (f) { return !f.expired; }).forEach(function (f) {
      if (f.expiry) add((f.tier || "?") + " " + (f.node || "fissure"), f.expiry, "#wf-void");
    });
    (map["/events"] || []).forEach(function (ev) {
      if (ev.expiry) add(ev.description || ev.tooltip || "Event", ev.expiry, "#wf-events");
    });
    items.sort(function (a, b) { return a.ms - b.ms; });
    return items;
  }

  function updateSoonStrip(map) {
    if (!soonEl) return;
    var items = collectSoonItems(map || (lastBundle && lastBundle.map) || {});
    if (!items.length) { soonEl.hidden = true; soonEl.innerHTML = ""; return; }
    var html = '<div class="wf-soon-inner"><strong>Changing soon</strong><ul class="wf-soon-list">';
    items.forEach(function (it) {
      html += "<li>" + (it.href ? '<a href="' + esc(it.href) + '">' + esc(it.label) + "</a>" : esc(it.label)) + " · " + etaHtml(it.iso) + "</li>";
    });
    html += "</ul></div>";
    soonEl.innerHTML = html;
    soonEl.hidden = false;
  }

  function formatReward(reward) {
    if (!reward) return "";
    var bits = [];
    (reward.items || []).forEach(function (it) { bits.push(it); });
    (reward.countedItems || []).forEach(function (it) { bits.push((it.count > 1 ? it.count + "× " : "") + (it.type || it.key || "?")); });
    if (reward.credits) bits.push(reward.credits + " cr");
    return bits.join(", ");
  }

  function ayaLabel(item) {
    var name = String(item.item || item.name || item.uniqueName || "");
    if (/MegaPrimeVault|MPV|Pack/i.test(name)) return "Regal Aya";
    return "Aya";
  }

  function renderInventoryGrid(inv, emptyMsg, opts) {
    opts = opts || {};
    var primaryLabel = opts.primaryLabel || "ducats";
    var market = !!opts.market;
    var ayaMode = !!opts.ayaMode;
    if (!inv || !inv.length) return '<p class="meta">' + esc(emptyMsg || "No inventory listed.") + "</p>";
    var html = '<div class="wf-inv-grid" id="' + (opts.gridId || "") + '">';
    inv.forEach(function (item, idx) {
      var name = item.item || item.name || "?";
      var label = ayaMode ? ayaLabel(item) : primaryLabel;
      var primary = item.aya != null ? item.aya : item.ducats != null ? item.ducats : null;
      var priceBits = [];
      if (primary != null) priceBits.push("<em>" + esc(primary) + "</em> " + esc(label));
      if (item.credits != null) priceBits.push(esc(item.credits) + " cr");
      html += '<div class="wf-inv-item" data-name="' + esc(name.toLowerCase()) + '" data-ducats="' + esc(primary != null ? primary : 0) + '" data-idx="' + idx + '"><span class="name">';
      if (market) html += '<a href="' + esc(marketLink(name)) + '">' + esc(name) + "</a>";
      else html += esc(name);
      html += '</span><span class="price">' + (priceBits.length ? priceBits.join(" · ") : "—") + "</span></div>";
    });
    return html + "</div>";
  }

  function renderBaro(vt) {
    var body = "";
    if (!vt) {
      body = '<p class="wf-empty">Could not load Baro.</p>';
      return band("wf-trader", "Trader") + panel("Baro Ki'Teer", "baro", body, { forceOpen: true, cls: "wf-baro", id: "baro", cmd: "/baro" });
    }
    var active = isActiveWindow(vt.activation, vt.expiry);
    var loc = vt.location || "Unknown relay";
    body += '<div class="wf-baro-top"><div><span class="wf-baro-badge' + (active ? "" : " away") + '">' + (active ? "At relay" : "In transit") + "</span>";
    body += '<p class="wf-baro-loc"><strong>' + esc(loc) + "</strong></p></div>";
    body += '<div class="wf-baro-countdown">';
    if (active) body += '<span class="label">Leaves in</span>' + etaHtml(vt.expiry);
    else if (vt.activation) body += '<span class="label">Arrives in</span>' + etaHtml(vt.activation);
    else body += '<span class="label">Status</span><span class="wf-eta">—</span>';
    body += "</div></div>";
    var inv = vt.inventory || [];
    lastBaroInv = inv.slice();
    if (active && inv.length) {
      body += '<div class="wf-baro-tools"><input type="search" id="wf-baro-q" class="wf-filter-select wf-riven-search" placeholder="Search inventory…" aria-label="Search Baro inventory" />';
      body += '<select id="wf-baro-sort" class="wf-filter-select" aria-label="Sort inventory"><option value="name">By name</option><option value="ducats">By ducats</option></select></div>';
      body += '<div id="wf-baro-inv-host">' + renderInventoryGrid(inv, "Inventory not listed yet.", { market: true, gridId: "wf-baro-inv" }) + "</div>";
      body += '<p class="meta" style="margin-top:12px">' + inv.length + " items</p>";
    } else if (active) {
      body += '<p class="meta">Inventory not listed yet — check closer to arrival.</p>';
    }
    var schedule = vt.schedule || [];
    if (schedule.length) {
      body += '<h3 class="wf-subhead">Upcoming visits</h3><ul class="wf-mission-list">';
      schedule.slice(0, 6).forEach(function (s) {
        body += "<li><strong>" + esc(s.location || s.node || "Relay") + "</strong>" + (s.expiry ? " · leaves " + etaHtml(s.expiry) : "") + (s.activation ? " · arrives " + etaHtml(s.activation) : "") + "</li>";
      });
      body += "</ul>";
    }
    return band("wf-trader", "Trader") + panel("Baro Ki'Teer", "baro", body, { forceOpen: true, cls: "wf-baro", id: "baro", cmd: "/baro" });
  }

  function renderVarzia(vt) {
    if (!vt) return "";
    var body = '<p class="meta">' + esc(vt.location || "Maroo's Bazaar") + (vt.expiry ? " · ends in " + etaHtml(vt.expiry) : "") + "</p>";
    body += renderInventoryGrid(vt.inventory || [], "No vault inventory listed.", { ayaMode: true, market: true });
    return panel(vt.character || "Varzia", "baro", body, { id: "varzia" });
  }

  function renderDarvoPanel(list) {
    if (!list || !list.length) return "";
    var body = '<ul class="wf-mission-list">';
    list.forEach(function (d) {
      body += "<li><strong>" + esc(d.item || "?") + "</strong> · " + esc(d.salePrice != null ? d.salePrice : "?") + " platinum" +
        (d.discount != null ? " (−" + esc(d.discount) + "%)" : "") +
        (d.sold != null && d.total != null ? ' <span class="meta">— ' + esc(d.sold) + "/" + esc(d.total) + " sold</span>" : "") +
        (d.expiry ? " · " + etaHtml(d.expiry) + " left" : "") + "</li>";
    });
    return panel("Darvo deal", "ops", body + "</ul>", { id: "darvo" });
  }

  function renderCycles(map) {
    var items = [
      cycleInfo(map["/cetusCycle"], "cetus"), cycleInfo(map["/vallisCycle"], "vallis"),
      cycleInfo(map["/cambionCycle"], "cambion"), cycleInfo(map["/earthCycle"], "earth"),
      cycleInfo(map["/duviriCycle"], "duviri"), cycleInfo(map["/zarimanCycle"], "zariman")
    ];
    var body = '<div class="wf-cycle-grid">';
    items.forEach(function (c) {
      var fc = c.faction ? " " + factionClass(c.faction) : "";
      body += '<div class="wf-cycle-card ' + esc(c.tone) + fc + '"><span class="wf-cycle-mark" aria-hidden="true">' + esc(c.mark) + '</span><div class="state">' + esc(c.state) + '</div><div class="name">' + esc(c.name) + "</div>" + (c.expiry ? '<div class="eta">' + etaHtml(c.expiry) + " left</div>" : "") + "</div>";
    });
    return band("wf-cycles", "Cycles") + panel("Open-world cycles", "cycle", body + "</div>", { forceOpen: true, id: "cycles" }) + "</div>";
  }

  function renderMission(title, data, ico, pid) {
    if (!data) return panel(title, ico, '<p class="wf-empty">No data.</p>', { id: pid });
    var missions = data.variants && data.variants.length ? data.variants : data.missions || [];
    var body = '<p class="meta">' + esc(data.boss || "") + (data.faction ? " · " + esc(data.faction) : "") + (data.expiry ? " · resets in " + etaHtml(data.expiry) : "") + "</p>";
    if (!missions.length) body += '<p class="wf-empty">No missions listed.</p>';
    else {
      body += '<ul class="wf-mission-list">';
      missions.forEach(function (m, idx) {
        body += "<li><strong>" + (idx + 1) + ". " + esc(m.node || m.missionType || m.type || "?") + "</strong> · " + esc(m.missionType || m.type || "") + (m.modifier ? ' <span class="meta">— ' + esc(m.modifier) + "</span>" : "") + "</li>";
      });
      body += "</ul>";
    }
    return panel(title, ico, body, { forceOpen: true, id: pid });
  }

  function archimedeaTitle(entry) {
    var key = String(entry.typeKey || entry.type || "").replace(/\s+/g, "").toUpperCase();
    if (key.indexOf("HEX") >= 0) return "Temporal Archimedea";
    if (key.indexOf("LAB") >= 0) return "Deep Archimedea";
    return entry.type || entry.typeKey || "Archimedea";
  }

  function renderArchimedeas(list) {
    if (!list || !list.length) return "";
    var html = "";
    list.forEach(function (entry, i) {
      var body = '<p class="meta">' + (entry.expiry ? "Resets in " + etaHtml(entry.expiry) : "Active") + "</p>";
      var missions = entry.missions || [];
      if (missions.length) {
        body += '<ul class="wf-mission-list">';
        missions.forEach(function (m, idx) {
          body += "<li><strong>" + (idx + 1) + ". " + esc(m.missionType || "?") + "</strong>" + (m.faction ? " · " + esc(m.faction) : "");
          if (m.deviation && m.deviation.name) body += '<div class="wf-mod-line"><strong>Deviation:</strong> ' + esc(m.deviation.name) + (m.deviation.description ? " — " + esc(m.deviation.description) : "") + "</div>";
          (m.risks || []).forEach(function (r) {
            body += '<div class="wf-mod-line"><strong>Risk' + (r.isHard ? " (hard)" : "") + ":</strong> " + esc(r.name || "") + (r.description ? " — " + esc(r.description) : "") + "</div>";
          });
          body += "</li>";
        });
        body += "</ul>";
      }
      var mods = entry.personalModifiers || [];
      if (mods.length) {
        body += '<h3 class="wf-subhead">Personal modifiers</h3><ul class="wf-mission-list">';
        mods.forEach(function (m) { body += "<li><strong>" + esc(m.name || m.key) + "</strong>" + (m.description ? " — " + esc(m.description) : "") + "</li>"; });
        body += "</ul>";
      }
      html += panel(archimedeaTitle(entry), "ops", body, { id: "archimedea-" + i });
    });
    return html;
  }

  function renderNightwave(nw) {
    if (!nw) return "";
    var challenges = nw.activeChallenges || [];
    var body = '<p class="meta">Season ' + esc(nw.season != null ? nw.season : "?") + (nw.phase != null ? " · phase " + esc(nw.phase) : "") + (nw.expiry ? " · ends " + etaHtml(nw.expiry) : "") + "</p>";
    if (!challenges.length) body += '<p class="wf-empty">No active challenges.</p>';
    else {
      function list(items, label) {
        if (!items.length) return "";
        var h = '<h3 class="wf-subhead">' + label + '</h3><ul class="wf-mission-list">';
        items.forEach(function (c) {
          h += "<li><strong>" + esc(c.title || "Challenge") + "</strong>" + (c.isElite ? ' <span class="wf-tag elite">Elite</span>' : "") + (c.reputation != null ? ' <span class="meta">+' + esc(c.reputation) + "</span>" : "") + '<div class="meta">' + esc(c.desc || "") + (c.expiry ? " · " + etaHtml(c.expiry) : "") + "</div></li>";
        });
        return h + "</ul>";
      }
      var daily = challenges.filter(function (c) { return c.isDaily; });
      var weekly = challenges.filter(function (c) { return !c.isDaily; });
      body += list(daily, "Daily") + list(weekly, "Weekly / other");
    }
    return panel("Nightwave", "ops", body, { id: "nightwave" });
  }

  function renderKuva(list) {
    if (!list || !list.length) return "";
    var body = '<ul class="wf-mission-list">';
    list.slice(0, 12).forEach(function (k) {
      body += "<li><strong>" + esc(k.node || k.enemy || "Kuva") + "</strong>" + (k.type || k.missionType ? " · " + esc(k.type || k.missionType) : "") + (k.expiry ? " · " + etaHtml(k.expiry) : "") + "</li>";
    });
    return panel("Kuva missions", "ops", body + "</ul>", { id: "kuva" });
  }

  function renderPersistent(list) {
    if (!list || !list.length) return "";
    var body = '<ul class="wf-mission-list">';
    list.forEach(function (e) {
      body += "<li><strong>" + esc(e.agentType || e.discordId || "Acolyte") + "</strong>" + (e.lastDiscoveredAt ? " · last seen " + esc(e.lastDiscoveredAt) : "") + (e.healthPercent != null ? " · " + Math.round(e.healthPercent) + "% HP" : "") + (e.region ? " · " + esc(e.region) : "") + "</li>";
    });
    return panel("Acolytes / persistent", "alert", body + "</ul>", { id: "persistent" });
  }

  function renderUpgrades(list) {
    if (!list || !list.length) return "";
    var active = list.filter(function (u) { return !u.expired && isActiveWindow(u.start || u.activation, u.end || u.expiry); });
    if (!active.length) active = list;
    var body = '<ul class="wf-mission-list">';
    active.forEach(function (u) {
      body += "<li><strong>" + esc(u.upgrade || u.description || u.operationType || "Upgrade") + "</strong>" + (u.upgradeOperationValue != null ? " · ×" + esc(u.upgradeOperationValue) : "") + (u.end || u.expiry ? " · " + etaHtml(u.end || u.expiry) + " left" : "") + "</li>";
    });
    return panel("Global upgrades", "build", body + "</ul>", { id: "upgrades" });
  }

  function renderDaily(map) {
    var cards = [];
    var sp = map["/steelPath"];
    if (sp) {
      var reward = sp.currentReward;
      var rewardName = reward && typeof reward === "object" ? reward.name || "?" : String(reward || "?");
      cards.push('<div class="wf-mini-card"><strong>Steel Path</strong><span>' + esc(rewardName) + "</span><span>" + etaHtml(sp.expiry) + " left</span></div>");
    }
    var arb = map["/arbitration"];
    if (arb && !arb.expired) {
      cards.push('<div class="wf-mini-card"><strong>Arbitration</strong><span>' + esc(arb.node || "?") + " · " + esc(arb.type || "") + "</span><span>" + esc(arb.enemy || "") + (arb.expiry ? " · " + etaHtml(arb.expiry) : "") + "</span></div>");
    }
    var so = map["/sentientOutposts"];
    if (so && so.active && so.mission) {
      cards.push('<div class="wf-mini-card"><strong>Sentient anomaly</strong><span>' + esc(so.mission.node || so.node || "?") + " · " + esc(so.mission.type || "") + "</span><span>" + esc(so.mission.faction || "") + "</span></div>");
    }
    var sim = map["/simaris"];
    if (sim && sim.target) {
      cards.push('<div class="wf-mini-card"><strong>Simaris</strong><span>' + esc(sim.target) + "</span><span>" + (sim.isTargetActive ? "Target active" : "Synthesis idle") + "</span></div>");
    }
    var html = "";
    if (cards.length) html += panel("Daily ops", "ops", '<div class="wf-mini-row">' + cards.join("") + "</div>", { id: "daily-ops" });
    html += renderNightwave(map["/nightwave"]);
    html += renderKuva(map["/kuva"]);
    html += renderPersistent(map["/persistentEnemies"]);
    html += renderUpgrades(map["/globalUpgrades"]);
    return html;
  }

  function renderConclave(list) {
    if (!list || !list.length) return "";
    var body = '<ul class="wf-mission-list">';
    list.forEach(function (c) {
      body += "<li><strong>" + esc(c.title || "Challenge") + "</strong>" + (c.daily ? ' <span class="wf-tag">Daily</span>' : "") + ' <span class="meta">' + esc(c.category || "") + (c.mode ? " · " + esc(c.mode) : "") + '</span><div class="meta">' + esc(c.description || "") + (c.amount != null ? " (" + esc(c.amount) + ")" : "") + (c.expiry ? " · " + etaHtml(c.expiry) : "") + "</div></li>";
    });
    return panel("Conclave", "ops", body + "</ul>", { id: "conclave" });
  }

  function renderBountiesAndConclave(syndicates, conclave) {
    var html = band("wf-bounties", "Bounties");
    if (!syndicates || !syndicates.length) html += panel("Syndicate bounties", "bounty", '<p class="wf-empty">No syndicate data.</p>', { id: "bounties" });
    else {
      var withJobs = syndicates.filter(function (s) { return (s.jobs || []).length; });
      var preferred = withJobs.length ? withJobs : syndicates.filter(function (s) { return BOUNTY_SYNDICATES.indexOf(s.syndicate) >= 0; });
      var body = "";
      preferred.forEach(function (s) {
        var jobs = s.jobs || [];
        body += '<div class="wf-bounty-block"><h3>' + esc(s.syndicate || "Syndicate") + "</h3>";
        body += '<p class="meta">' + (s.expiry ? "Resets " + etaHtml(s.expiry) : "Active") + (jobs.length ? " · " + jobs.length + " jobs" : "") + "</p>";
        if (jobs.length) {
          body += '<ul class="wf-mission-list">';
          jobs.forEach(function (j) {
            var levels = (j.enemyLevels || []).join("–");
            var rewards = (j.rewardPool || []).slice(0, 4).join(", ");
            body += "<li><strong>" + esc(j.type || "Bounty") + "</strong>" + (levels ? " · lv " + esc(levels) : "") + (j.minMR != null ? " · MR " + esc(j.minMR) + "+" : "") + (rewards ? '<div class="meta">Pool: ' + esc(rewards) + ((j.rewardPool || []).length > 4 ? "…" : "") + "</div>" : "") + "</li>";
          });
          body += "</ul>";
        } else if ((s.nodes || []).length) body += '<p class="meta">Nodes: ' + esc((s.nodes || []).slice(0, 8).join(", ")) + "</p>";
        else body += '<p class="meta">No jobs listed this cycle.</p>';
        body += "</div>";
      });
      var nodesOnly = syndicates.filter(function (s) { return !(s.jobs || []).length && (s.nodes || []).length && preferred.indexOf(s) < 0; });
      if (nodesOnly.length) {
        body += '<h3 class="wf-subhead">Faction death squads</h3><ul class="wf-mission-list">';
        nodesOnly.slice(0, 8).forEach(function (s) {
          body += "<li><strong>" + esc(s.syndicate) + "</strong> · " + esc((s.nodes || []).slice(0, 4).join(", ")) + ((s.nodes || []).length > 4 ? "…" : "") + "</li>";
        });
        body += "</ul>";
      }
      html += panel("Syndicate bounties", "bounty", body || '<p class="wf-empty">No bounties.</p>', { id: "bounties" });
    }
    html += renderConclave(conclave);
    return html + "</div>";
  }

  function eventProgress(ev) {
    if (ev.health != null && !isNaN(Number(ev.health))) return Math.max(0, Math.min(100, Number(ev.health)));
    if (ev.maximumScore && ev.currentScore != null) return Math.max(0, Math.min(100, (Number(ev.currentScore) / Number(ev.maximumScore)) * 100));
    return null;
  }

  function renderEvents(list, construction) {
    var html = band("wf-events", "Events");
    var hasEvents = list && list.length;
    var hasBuild = construction && (construction.fomorianProgress || construction.razorbackProgress);
    if (!hasEvents && !hasBuild) return html + panel("Events", "event", '<p class="wf-empty">No active events.</p>', { id: "events" }) + "</div>";
    if (hasEvents) {
      var body = "";
      list.forEach(function (ev) {
        var pct = eventProgress(ev);
        var rewardItems = [];
        var thumb = "";
        var thumbName = "";
        (ev.rewards || []).forEach(function (r) {
          if (!thumbName) thumbName = rewardItemName(r);
          if (!thumb) thumb = rewardThumb(r);
          (r.items || []).forEach(function (it) { rewardItems.push(it); });
        });
        body += '<div class="wf-event-card"><h3>' + thumbHtml(thumb, thumbName) + esc(ev.description || ev.tooltip || "Event") + "</h3>";
        body += '<p class="meta">' + esc(ev.node || "") + (ev.expiry ? (ev.node ? " · " : "") + "ends in " + etaHtml(ev.expiry) : "") + "</p>";
        if (ev.tooltip && ev.tooltip !== ev.description) body += '<p class="wf-event-tip">' + esc(ev.tooltip) + "</p>";
        if (pct != null) body += '<div class="wf-progress" role="progressbar" aria-valuenow="' + Math.round(pct) + '"><span style="width:' + pct.toFixed(1) + '%"></span></div><p class="meta">' + Math.round(pct) + "% complete</p>";
        if (rewardItems.length) body += '<p class="meta">Rewards: ' + esc(rewardItems.slice(0, 6).join(", ")) + "</p>";
        body += "</div>";
      });
      html += panel("Events", "event", body, { id: "events" });
    }
    if (hasBuild) {
      var build = "";
      [{ label: "Fomorian", value: construction.fomorianProgress }, { label: "Razorback", value: construction.razorbackProgress }].forEach(function (b) {
        var n = Math.max(0, Math.min(100, parseFloat(b.value) || 0));
        build += '<div class="wf-build-row"><span>' + esc(b.label) + '</span><div class="wf-progress"><span style="width:' + n.toFixed(1) + '%"></span></div><em>' + n.toFixed(1) + "%</em></div>";
      });
      html += panel("Construction", "build", build, { id: "construction" });
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
    for (var i = 0; i < TIER_ORDER.length; i++) if (t.indexOf(TIER_ORDER[i]) >= 0) return i;
    return TIER_ORDER.length;
  }

  function tierLabel(tier) {
    var t = String(tier || "").trim();
    if (!t) return "Other";
    var lower = t.toLowerCase();
    for (var i = 0; i < TIER_ORDER.length; i++) if (lower.indexOf(TIER_ORDER[i]) >= 0) return TIER_ORDER[i].charAt(0).toUpperCase() + TIER_ORDER[i].slice(1);
    return t;
  }

  function activeFissures(list) { return (list || []).filter(function (f) { return !f.expired; }); }

  function sortFissures(list) {
    var sort = loadFissureSort();
    var arr = list.slice();
    arr.sort(function (a, b) {
      if (sort === "eta") return (parseTime(a.expiry) || 0) - (parseTime(b.expiry) || 0);
      if (sort === "planet") {
        var pa = parseNodePlanet(a.node).toLowerCase();
        var pb = parseNodePlanet(b.node).toLowerCase();
        if (pa !== pb) return pa < pb ? -1 : 1;
        var ra = tierRank(a.tier || a.tierNum);
        var rb = tierRank(b.tier || b.tierNum);
        if (ra !== rb) return ra - rb;
        return (parseTime(a.expiry) || 0) - (parseTime(b.expiry) || 0);
      }
      var ra2 = tierRank(a.tier || a.tierNum);
      var rb2 = tierRank(b.tier || b.tierNum);
      if (ra2 !== rb2) return ra2 - rb2;
      return (parseTime(a.expiry) || 0) - (parseTime(b.expiry) || 0);
    });
    return arr;
  }

  function filterFissures(list) {
    var tiers = loadFissureTiers();
    var mission = loadFissureMission();
    var mode = loadFissureMode();
    var planet = loadFissurePlanet();
    var watchOnly = loadWatchOnly();
    var watch = loadWatch();
    return sortFissures(list.filter(function (f) {
      var label = tierLabel(f.tier || f.tierNum);
      if (tiers.indexOf(label) < 0) return false;
      if (mission && String(f.missionType || "") !== mission) return false;
      if (mode === "hard" && !f.isHard) return false;
      if (mode === "storm" && !f.isStorm) return false;
      if (mode === "normal" && (f.isHard || f.isStorm)) return false;
      if (planet && parseNodePlanet(f.node) !== planet) return false;
      if (watchOnly && watch.indexOf(f.node || "") < 0) return false;
      return true;
    }));
  }

  function missionTypeCounts(list) {
    var counts = {};
    list.forEach(function (f) { var t = f.missionType || "Other"; counts[t] = (counts[t] || 0) + 1; });
    return Object.keys(counts).sort().map(function (k) { return { type: k, count: counts[k] }; });
  }

  function planetCounts(list) {
    var counts = {};
    list.forEach(function (f) { var p = parseNodePlanet(f.node) || "Unknown"; counts[p] = (counts[p] || 0) + 1; });
    return Object.keys(counts).sort().map(function (k) { return { planet: k, count: counts[k] }; });
  }

  function renderFissureChip(f) {
    var tier = f.tier || f.tierNum || "?";
    var node = f.node || "?";
    var watched = isWatched(node);
    return '<span class="wf-chip ' + tierClass(tier) + (watched ? " watched" : "") + '"><button type="button" class="wf-watch" data-watch="' + esc(node) + '" aria-pressed="' + (watched ? "true" : "false") + '" title="Toggle watchlist">' + (watched ? "★" : "☆") + '</button><span class="tier">' + esc(tier) + "</span>" + esc(node) + "<em>" + esc(f.missionType || "") + (f.enemy ? " · " + esc(f.enemy) : "") + (f.isStorm ? " · Storm" : "") + (f.isHard ? " · SP" : "") + (f.expiry ? " · " + timeUntil(f.expiry) : "") + '</em><button type="button" class="wf-copy" data-copy="' + esc(node) + '" title="Copy node">Copy</button></span>';
  }

  function renderFissureFilters(list) {
    var selectedTiers = loadFissureTiers();
    var selectedMission = loadFissureMission();
    var selectedMode = loadFissureMode();
    var selectedSort = loadFissureSort();
    var selectedPlanet = loadFissurePlanet();
    var watchOnly = loadWatchOnly();
    var tierScoped = list.filter(function (f) { return selectedTiers.indexOf(tierLabel(f.tier || f.tierNum)) >= 0; });
    var types = missionTypeCounts(tierScoped);
    var planets = planetCounts(tierScoped);
    var html = '<div class="wf-fissure-filters" id="wf-fissure-filters">';
    html += '<div class="wf-filter-row"><span class="wf-filter-label">Relic tier</span><div class="wf-filter-chips" data-filter="tiers">';
    ALL_FISSURE_TIERS.forEach(function (t) {
      var on = selectedTiers.indexOf(t) >= 0;
      html += '<button type="button" class="wf-filter-chip ' + tierClass(t) + (on ? " on" : "") + '" data-tier="' + esc(t) + '" aria-pressed="' + (on ? "true" : "false") + '">' + esc(t) + "</button>";
    });
    html += "</div></div>";
    html += '<div class="wf-filter-row"><span class="wf-filter-label">Mission type</span><select id="wf-fissure-mission" class="wf-filter-select" aria-label="Filter by mission type"><option value="">All missions (' + tierScoped.length + ")</option>";
    types.forEach(function (t) {
      html += '<option value="' + esc(t.type) + '"' + (selectedMission === t.type ? " selected" : "") + ">" + esc(t.type) + " (" + t.count + ")</option>";
    });
    html += "</select></div>";
    html += '<div class="wf-filter-row"><span class="wf-filter-label">Planet</span><select id="wf-fissure-planet" class="wf-filter-select" aria-label="Filter by planet"><option value="">All planets</option>';
    planets.forEach(function (p) {
      html += '<option value="' + esc(p.planet) + '"' + (selectedPlanet === p.planet ? " selected" : "") + ">" + esc(p.planet) + " (" + p.count + ")</option>";
    });
    html += "</select></div>";
    html += '<div class="wf-filter-row"><span class="wf-filter-label">Mode</span><div class="wf-filter-chips">';
    [["all", "All"], ["normal", "Normal"], ["hard", "Steel Path"], ["storm", "Storm"]].forEach(function (pair) {
      var on = selectedMode === pair[0];
      html += '<button type="button" class="wf-filter-chip' + (on ? " on" : "") + '" data-mode="' + pair[0] + '" aria-pressed="' + (on ? "true" : "false") + '">' + pair[1] + "</button>";
    });
    html += "</div></div>";
    html += '<div class="wf-filter-row"><span class="wf-filter-label">Sort</span><div class="wf-filter-chips">';
    [["tier", "By tier"], ["eta", "By time left"], ["planet", "By planet"]].forEach(function (pair) {
      var on = selectedSort === pair[0];
      html += '<button type="button" class="wf-filter-chip' + (on ? " on" : "") + '" data-sort="' + pair[0] + '" aria-pressed="' + (on ? "true" : "false") + '">' + pair[1] + "</button>";
    });
    html += "</div></div>";
    html += '<div class="wf-filter-row"><span class="wf-filter-label">Watchlist</span><button type="button" class="wf-filter-chip' + (watchOnly ? " on" : "") + '" id="wf-watch-only" aria-pressed="' + (watchOnly ? "true" : "false") + '">Watchlist only</button></div>';
    if (types.length) {
      html += '<div class="wf-mission-summary">';
      types.forEach(function (t) {
        html += '<button type="button" class="wf-mission-pill' + (selectedMission === t.type ? " on" : "") + '" data-mission="' + esc(t.type) + '">' + esc(t.type) + " <em>" + t.count + "</em></button>";
      });
      html += "</div>";
    }
    return html + "</div>";
  }

  function renderFissureList(filtered) {
    if (!filtered.length) return '<p class="wf-empty">No fissures match these filters.</p>';
    var sort = loadFissureSort();
    if (sort === "eta") {
      var html = '<div class="wf-chips">';
      filtered.forEach(function (f) { html += renderFissureChip(f); });
      return html + "</div>";
    }
    var groups = [];
    var currentKey = null;
    var currentItems = null;
    filtered.forEach(function (f) {
      var label = sort === "planet" ? (parseNodePlanet(f.node) || "Unknown") : tierLabel(f.tier || f.tierNum);
      if (label !== currentKey) {
        currentKey = label;
        currentItems = [];
        groups.push({ label: label, tier: f.tier || f.tierNum, items: currentItems, planet: sort === "planet" });
      }
      currentItems.push(f);
    });
    var out = "";
    groups.forEach(function (g) {
      out += '<div class="wf-fissure-group"><h3 class="wf-fissure-tier ' + esc(g.planet ? "" : tierClass(g.tier)) + '">' + esc(g.label) + ' <span class="count">' + g.items.length + "</span></h3><div class=\"wf-chips\">";
      g.items.forEach(function (f) { out += renderFissureChip(f); });
      out += "</div></div>";
    });
    return out;
  }

  function renderFissures(list) {
    lastFissures = activeFissures(list);
    var filtered = filterFissures(lastFissures);
    var body = "";
    if (!lastFissures.length) body = '<p class="wf-empty">No fissures right now.</p>';
    else {
      body += renderFissureFilters(lastFissures);
      body += '<p class="meta wf-fissure-count" id="wf-fissure-count">Showing ' + filtered.length + " of " + lastFissures.length + " active</p>";
      body += '<div id="wf-fissure-list">' + renderFissureList(filtered) + "</div>";
    }
    return band("wf-void", "Void") + panel("Void fissures", "void", body, { forceOpen: true, id: "fissures", cmd: "/fissure" }) + "</div>";
  }

  function renderFlashSales(list) {
    if (!list || !list.length) return "";
    var now = Date.now();
    var items = list.filter(function (s) {
      if (s.isShownInMarket === false) return false;
      var exp = parseTime(s.expiry);
      return exp == null || exp > now;
    }).slice(0, 16);
    if (!items.length) return "";
    var body = '<ul class="wf-mission-list">';
    items.forEach(function (s) {
      body += "<li><strong>" + esc(s.item || "?") + "</strong>" + (s.discount != null ? " · −" + esc(s.discount) + "%" : "") + (s.expiry && parseTime(s.expiry) < now + 86400000 * 60 ? " · " + etaHtml(s.expiry) + " left" : "") + "</li>";
    });
    return panel("Flash sales", "market", body + "</ul>", { id: "flash-sales" });
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
          rows.push({ category: cat, name: name, kind: kind, median: stats.median, avg: stats.avg, min: stats.min, max: stats.max, pop: stats.pop });
        });
      });
    });
    return rows;
  }

  function renderRivens(data) {
    lastRivens = flattenRivens(data);
    if (!lastRivens.length) return "";
    var cats = [];
    lastRivens.forEach(function (r) { if (cats.indexOf(r.category) < 0) cats.push(r.category); });
    var body = '<div class="wf-riven-tools"><input type="search" id="wf-riven-q" class="wf-filter-select wf-riven-search" placeholder="Search weapon…" aria-label="Search rivens" /><select id="wf-riven-cat" class="wf-filter-select" aria-label="Riven category"><option value="">All categories</option>';
    cats.forEach(function (c) { body += '<option value="' + esc(c) + '">' + esc(c.replace(" Riven Mod", "")) + "</option>"; });
    body += '</select></div><p class="meta">Community trade medians (platinum). Not disposition values.</p><div id="wf-riven-list"></div>';
    return panel("Riven prices", "market", body, { id: "rivens" });
  }

  function renderMarket(map) {
    var html = band("wf-market", "Market");
    var flash = renderFlashSales(map["/flashSales"]);
    if (flash) html += flash;
    html += '<div id="wf-riven-host">';
    if (map["/rivens"]) html += renderRivens(map["/rivens"]) || '<p class="wf-empty">No riven data.</p>';
    else html += '<p class="meta">Loading riven prices…</p>';
    html += "</div></div>";
    return html;
  }

  function renderAlerts(list) {
    if (!list || !list.length) return "";
    var body = '<ul class="wf-mission-list">';
    list.slice(0, 10).forEach(function (a) {
      var mission = a.mission || {};
      var reward = formatReward(mission.reward || a.reward);
      var thumb = thumbHtmlForReward(mission.reward || a.reward);
      body += "<li>" + thumb + "<strong>" + esc(mission.node || a.tag || "Alert") + "</strong> · " + esc(mission.type || "") + (mission.faction ? " · " + esc(mission.faction) : "") + (reward ? '<div class="meta">Reward: ' + esc(reward) + "</div>" : "") + (a.expiry ? '<div class="meta">' + etaHtml(a.expiry) + " left</div>" : "") + "</li>";
    });
    return panel("Alerts", "alert", body + "</ul>", { id: "alerts", cmd: "/alert" });
  }

  function renderInvasions(list) {
    var open = (list || []).filter(function (i) { return !i.completed; }).slice(0, 12);
    var body = "";
    if (!open.length) body = '<p class="wf-empty">No active invasions.</p>';
    else {
      open.forEach(function (i) {
        var pct = i.completion != null ? Math.max(0, Math.min(100, Number(i.completion))) : 0;
        var atk = i.attacker || {};
        var def = i.defender || {};
        var atkR = formatReward(atk.reward);
        var defR = formatReward(def.reward);
        var atkThumb = thumbHtmlForReward(atk.reward);
        var defThumb = thumbHtmlForReward(def.reward);
        var fc = factionClass(atk.faction || (i.vsInfestation ? "infested" : ""));
        body += '<div class="wf-invasion-card ' + fc + '"><h3>' + esc(i.node || "?") + '</h3><p class="meta">' + esc(i.desc || "") + (i.vsInfestation ? " · vs Infested" : "") + "</p>";
        body += '<div class="wf-invasion-sides"><div><strong>' + esc(atk.faction || "Attacker") + "</strong>" + atkThumb + "<span>" + esc(atkR || "—") + "</span></div><div><strong>" + esc(def.faction || "Defender") + "</strong>" + defThumb + "<span>" + esc(defR || "—") + "</span></div></div>";
        body += '<div class="wf-progress" role="progressbar" aria-valuenow="' + Math.round(pct) + '"><span style="width:' + pct.toFixed(1) + '%"></span></div><p class="meta">' + Math.round(pct) + "% complete" + (i.expiry ? " · " + etaHtml(i.expiry) : "") + "</p></div>";
      });
    }
    return panel("Invasions", "invasion", body, { forceOpen: true, id: "invasions", cmd: "/invasion" });
  }

  function renderInvasionsBand(list, alertsHtml) {
    return band("wf-invasions", "Invasions") + renderInvasions(list) + (alertsHtml || "") + "</div>";
  }

  function newsMessage(n) {
    if (n.translations && n.translations[lang]) return n.translations[lang];
    if (n.translations && n.translations.en) return n.translations.en;
    return n.message || "News";
  }

  function renderNews(list) {
    var items = (list || []).filter(function (n) {
      var t = parseTime(n.date);
      return t == null || t > Date.parse("2000-01-01");
    }).slice().sort(function (a, b) { return (parseTime(b.date) || 0) - (parseTime(a.date) || 0); }).slice(0, 10);
    var body = "";
    if (!items.length) body = '<p class="wf-empty">No recent news.</p>';
    else {
      body = '<ul class="wf-news-list">';
      items.forEach(function (n) {
        var msg = newsMessage(n);
        var tags = [];
        if (n.update) tags.push("Update");
        if (n.primeAccess) tags.push("Prime Access");
        if (n.stream) tags.push("Stream");
        if (n.priority) tags.push("Priority");
        body += "<li>";
        if (n.link) body += '<a href="' + esc(n.link) + '" target="_blank" rel="noopener noreferrer">' + esc(msg) + "</a>";
        else body += "<strong>" + esc(msg) + "</strong>";
        if (tags.length || n.date) body += ' <span class="meta">' + (tags.length ? esc(tags.join(" · ")) : "") + (tags.length && n.date ? " · " : "") + (n.date ? esc(new Date(n.date).toLocaleDateString()) : "") + "</span>";
        body += "</li>";
      });
      body += "</ul>";
    }
    return band("wf-news", "News") + panel("News", "news", body, { id: "news" }) + "</div>";
  }

  function skeleton() {
    return '<div class="wf-skel-grid"><div class="wf-skel-card tall"></div><div class="wf-skel-row">' +
      '<div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div>' +
      '</div><div class="wf-skel-row"><div class="wf-skel-card"></div><div class="wf-skel-card"></div></div>' +
      '<div class="wf-skel-card"></div><div class="wf-skel-row"><div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div></div></div>';
  }

  function tickEtas() {
    document.querySelectorAll(".wf-eta[data-expiry]").forEach(function (node) {
      var iso = node.getAttribute("data-expiry");
      if (!iso) return;
      node.textContent = timeUntil(iso);
      node.className = "wf-eta tick" + etaUrgencyClass(iso);
      node.setAttribute("title", etaTitle(iso));
    });
  }

  function setAllCollapsed(collapsed) {
    saveCollapsedPrefer(collapsed);
    var panels = loadPanels();
    document.querySelectorAll("details.wf-collapse").forEach(function (d) {
      d.open = !collapsed;
      var id = d.getAttribute("data-panel-id");
      if (id) panels[id] = !collapsed;
    });
    savePanels(panels);
    if (collapseBtn) collapseBtn.textContent = collapsed ? "Expand" : "Collapse";
  }

  function refreshFissurePanel() {
    var filtersHost = document.getElementById("wf-fissure-filters");
    var listHost = document.getElementById("wf-fissure-list");
    var countEl = document.getElementById("wf-fissure-count");
    if (!listHost) return;
    var filtered = filterFissures(lastFissures);
    if (filtersHost) filtersHost.outerHTML = renderFissureFilters(lastFissures);
    listHost.innerHTML = renderFissureList(filtered);
    if (countEl) countEl.textContent = "Showing " + filtered.length + " of " + lastFissures.length + " active";
    bindFissureFilters();
    bindWatchlist();
  }

  function paintBaroInventory() {
    var host = document.getElementById("wf-baro-inv-host");
    var qEl = document.getElementById("wf-baro-q");
    var sortEl = document.getElementById("wf-baro-sort");
    if (!host || !lastBaroInv.length) return;
    var query = ((qEl && qEl.value) || "").trim().toLowerCase();
    var sort = (sortEl && sortEl.value) || "name";
    var items = lastBaroInv.filter(function (it) {
      var name = String(it.item || it.name || "").toLowerCase();
      return !query || name.indexOf(query) >= 0;
    });
    items.sort(function (a, b) {
      if (sort === "ducats") {
        var da = a.ducats != null ? a.ducats : 0;
        var db = b.ducats != null ? b.ducats : 0;
        return db - da;
      }
      var na = String(a.item || a.name || "").toLowerCase();
      var nb = String(b.item || b.name || "").toLowerCase();
      return na < nb ? -1 : na > nb ? 1 : 0;
    });
    host.innerHTML = renderInventoryGrid(items, "No matches.", { market: true, gridId: "wf-baro-inv" });
  }

  function bindBaroTools() {
    var q = document.getElementById("wf-baro-q");
    var sort = document.getElementById("wf-baro-sort");
    if (q) q.addEventListener("input", paintBaroInventory);
    if (sort) sort.addEventListener("change", paintBaroInventory);
  }

  function bindFissureFilters() {
    var host = document.getElementById("wf-fissure-filters");
    if (host) {
      host.querySelectorAll("[data-tier]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var tier = btn.getAttribute("data-tier");
          var tiers = loadFissureTiers();
          var idx = tiers.indexOf(tier);
          if (idx >= 0) { if (tiers.length === 1) return; tiers.splice(idx, 1); }
          else { tiers.push(tier); tiers = ALL_FISSURE_TIERS.filter(function (t) { return tiers.indexOf(t) >= 0; }); }
          saveFissureTiers(tiers);
          var scoped = lastFissures.filter(function (f) { return tiers.indexOf(tierLabel(f.tier || f.tierNum)) >= 0; });
          var mission = loadFissureMission();
          if (mission && !scoped.some(function (f) { return f.missionType === mission; })) saveFissureMission("");
          refreshFissurePanel();
        });
      });
      host.querySelectorAll("[data-mode]").forEach(function (btn) {
        btn.addEventListener("click", function () { saveFissureMode(btn.getAttribute("data-mode") || "all"); refreshFissurePanel(); });
      });
      host.querySelectorAll("[data-sort]").forEach(function (btn) {
        btn.addEventListener("click", function () { saveFissureSort(btn.getAttribute("data-sort") || "tier"); refreshFissurePanel(); });
      });
      host.querySelectorAll("[data-mission]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var m = btn.getAttribute("data-mission") || "";
          saveFissureMission(loadFissureMission() === m ? "" : m);
          refreshFissurePanel();
        });
      });
      var select = document.getElementById("wf-fissure-mission");
      if (select) select.addEventListener("change", function () { saveFissureMission(select.value || ""); refreshFissurePanel(); });
      var planetSel = document.getElementById("wf-fissure-planet");
      if (planetSel) planetSel.addEventListener("change", function () { saveFissurePlanet(planetSel.value || ""); refreshFissurePanel(); });
    }
    var watchBtn = document.getElementById("wf-watch-only");
    if (watchBtn) watchBtn.addEventListener("click", function () { saveWatchOnly(!loadWatchOnly()); refreshFissurePanel(); });
    document.querySelectorAll(".wf-copy[data-copy]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault(); e.stopPropagation();
        var text = btn.getAttribute("data-copy") || "";
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(function () {
            btn.textContent = "Copied";
            setTimeout(function () { btn.textContent = "Copy"; }, 1200);
          }, function () {});
        }
      });
    });
  }

  function bindWatchlist() {
    document.querySelectorAll(".wf-watch[data-watch]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault(); e.stopPropagation();
        var node = btn.getAttribute("data-watch") || "";
        var watch = loadWatch();
        var idx = watch.indexOf(node);
        if (idx >= 0) watch.splice(idx, 1); else watch.push(node);
        saveWatch(watch);
        refreshFissurePanel();
      });
    });
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
      rows.sort(function (a, b) { return (b.median || 0) - (a.median || 0); });
      rows = rows.slice(0, 40);
      if (!rows.length) { list.innerHTML = '<p class="wf-empty">No matches.</p>'; return; }
      var html = '<ul class="wf-mission-list">';
      rows.forEach(function (r) {
        html += "<li><strong><a href=\"" + esc(marketLink(r.name)) + "\">" + esc(r.name) + "</a></strong> · " + esc(r.kind) + ' <span class="meta">' + esc(r.category.replace(" Riven Mod", "")) + '</span><div class="meta">median ' + esc(r.median) + "p · avg " + esc(Math.round(r.avg || 0)) + "p · pop " + esc(r.pop || 0) + "</div></li>";
      });
      list.innerHTML = html + "</ul>";
    }
    if (q) q.addEventListener("input", paint);
    if (cat) cat.addEventListener("change", paint);
    paint();
  }

  function bindPins() {
    document.querySelectorAll(".wf-pin[data-pin]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault(); e.stopPropagation();
        var id = btn.getAttribute("data-pin");
        var pins = loadPins();
        var idx = pins.indexOf(id);
        if (idx >= 0) pins.splice(idx, 1); else pins.push(id);
        savePins(pins);
        if (lastBundle) render(lastBundle);
      });
    });
  }

  function bindPanelMemory() {
    document.querySelectorAll("details.wf-collapse[data-panel-id]").forEach(function (d) {
      d.addEventListener("toggle", function () {
        var panels = loadPanels();
        panels[d.getAttribute("data-panel-id")] = d.open;
        savePanels(panels);
      });
    });
  }

  function bindJumpObserver() {
    if (jumpObs) { jumpObs.disconnect(); jumpObs = null; }
    if (!("IntersectionObserver" in window)) return;
    var links = document.querySelectorAll(".wf-jump a");
    if (!links.length) return;
    var sections = [];
    links.forEach(function (a) {
      var id = (a.getAttribute("href") || "").replace("#", "");
      var el = document.getElementById(id);
      if (el) sections.push({ a: a, el: el });
    });
    if (!sections.length) return;
    jumpObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var id = entry.target.id;
        links.forEach(function (a) { a.classList.toggle("is-active", a.getAttribute("href") === "#" + id); });
      });
    }, { rootMargin: "-40% 0px -50% 0px", threshold: 0 });
    sections.forEach(function (s) { jumpObs.observe(s.el); });
  }

  function render(bundle) {
    if (!root) return;
    lastBundle = bundle;
    var map = bundle.map;
    updateTeaser(map);
    updateSoonStrip(map);
    panelSeq = 0;
    var bands = {};
    var trader = renderBaro(map["/voidTrader"]);
    var side = renderVarzia(map["/vaultTrader"]) + renderDarvoPanel(map["/dailyDeals"]);
    if (side) trader += '<div class="wf-grid-2" style="margin-top:16px">' + side + "</div>";
    bands["wf-trader"] = trader + "</div>";
    bands["wf-cycles"] = renderCycles(map);
    bands["wf-missions"] = band("wf-missions", "Missions") + '<div class="wf-grid-2">' + renderMission("Sortie", map["/sortie"], "sortie", "sortie") + renderMission("Archon hunt", map["/archonHunt"], "archon", "archon") + "</div>" + renderArchimedeas(map["/archimedeas"]) + renderDaily(map) + "</div>";
    bands["wf-bounties"] = renderBountiesAndConclave(map["/syndicateMissions"], map["/conclaveChallenges"]);
    bands["wf-events"] = renderEvents(map["/events"], map["/constructionProgress"]);
    bands["wf-void"] = renderFissures(map["/fissures"]);
    bands["wf-market"] = renderMarket(map);
    bands["wf-news"] = renderNews(map["/news"]);
    bands["wf-invasions"] = renderInvasionsBand(map["/invasions"], renderAlerts(map["/alerts"]));
    root.innerHTML = assembleBands(bands);
    root.removeAttribute("aria-busy");
    hydrateRewardThumbs(root);
    bindFissureFilters();
    bindWatchlist();
    bindBaroTools();
    bindRivens();
    bindPins();
    bindPanelMemory();
    bindJumpObserver();
    if (collapseBtn) collapseBtn.textContent = collapsedPrefer ? "Expand" : "Collapse";
    scrollPendingSection();
    var platName = PLATFORMS[platform] || "PC";
    if (bundle.fails === 0) setStatus(true, "Live · " + platName + " · " + lang.toUpperCase() + " · " + new Date().toLocaleTimeString());
    else if (bundle.fails < bundle.total) setStatus(true, "Partial · " + bundle.fails + " failed · " + platName + " · " + new Date().toLocaleTimeString());
    else setStatus(false, "Could not reach Warframe world-state API");
  }

  function refresh() {
    setStatus(true, "Refreshing…");
    if (root && !root.dataset.ready) root.innerHTML = skeleton();
    return loadAll().then(function (bundle) {
      lastUpdateTime = Date.now();
      setStale(false);
      if (root) root.dataset.ready = "1";
      render(bundle);
      setTimeout(fetchRivensIncremental, 0);
    }).catch(function () {
      if (lastBundle) {
        setStale(true);
        setStatus(false, "Offline · showing cached data · " + (lastUpdateTime ? new Date(lastUpdateTime).toLocaleTimeString() : ""));
        updateSoonStrip(lastBundle.map);
        return;
      }
      setStatus(false, "Could not reach Warframe world-state API");
      if (root && !root.dataset.ready) root.innerHTML = '<p class="wf-empty">Unable to load world state. Try again in a moment.</p>';
    });
  }

  applyDense(lsGet(DENSE_KEY, "0") === "1");
  applyDeepLinks();
  savePlatform(platform);
  saveLang(lang);
  syncUrlParams();

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

  if (denseBtn) denseBtn.addEventListener("click", function () { applyDense(!document.body.classList.contains("wf-dense")); });
  if (collapseBtn) collapseBtn.addEventListener("click", function () { setAllCollapsed(!collapsedPrefer); });
  if (refreshBtn) refreshBtn.addEventListener("click", function () { refresh(); });
  if (tvBtn) tvBtn.addEventListener("click", function () { applyTv(!document.body.classList.contains("wf-tv")); });

  refresh();
  timer = setInterval(refresh, REFRESH_MS);
  tickTimer = setInterval(tickEtas, 15000);
  window.addEventListener("beforeunload", function () {
    if (timer) clearInterval(timer);
    if (tickTimer) clearInterval(tickTimer);
    if (jumpObs) jumpObs.disconnect();
  });
})();

