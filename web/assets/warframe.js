/**
 * Public Warframe world-state page — fetches api.warframestat.us (no bot login).
 */
(function () {
  var API_HOST = "https://api.warframestat.us";
  var REFRESH_MS = 60 * 1000;
  var PLATFORM_KEY = "oo_wf_platform";
  var FISSURE_TIERS_KEY = "oo_wf_fissure_tiers";
  var FISSURE_MISSION_KEY = "oo_wf_fissure_mission";
  var FISSURE_MODE_KEY = "oo_wf_fissure_mode";

  var PLATFORMS = {
    pc: "PC",
    ps4: "PlayStation",
    xb1: "Xbox",
    swi: "Switch",
  };

  var DEFAULT_FISSURE_TIERS = ["Lith", "Meso", "Neo", "Axi"];
  var ALL_FISSURE_TIERS = ["Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia"];

  var root = document.getElementById("wf-root");
  var statusEl = document.getElementById("wf-status");
  var teaserEl = document.getElementById("wf-teaser");
  var refreshBtn = document.getElementById("wf-refresh");
  var platformSelect = document.getElementById("wf-platform");
  var platformLabel = document.getElementById("wf-platform-label");
  var timer = null;
  var tickTimer = null;
  var lastBundle = null;
  var lastFissures = [];
  var platform = loadPlatform();

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

  function head(title, ico) {
    return (
      '<div class="wf-panel-head"><span class="ico" aria-hidden="true">' +
      (ICO[ico] || ICO.ops) +
      "</span><h2>" +
      esc(title) +
      "</h2></div>"
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

  function loadPlatform() {
    try {
      var p = localStorage.getItem(PLATFORM_KEY) || "pc";
      return PLATFORMS[p] ? p : "pc";
    } catch (e) {
      return "pc";
    }
  }

  function savePlatform(p) {
    platform = PLATFORMS[p] ? p : "pc";
    try {
      localStorage.setItem(PLATFORM_KEY, platform);
    } catch (e) {}
    if (platformSelect) platformSelect.value = platform;
    if (platformLabel) platformLabel.textContent = PLATFORMS[platform];
  }

  function apiBase() {
    return API_HOST + "/" + platform;
  }

  function loadFissureTiers() {
    try {
      var raw = localStorage.getItem(FISSURE_TIERS_KEY);
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
    try {
      localStorage.setItem(FISSURE_TIERS_KEY, JSON.stringify(tiers));
    } catch (e) {}
  }

  function loadFissureMission() {
    try {
      return localStorage.getItem(FISSURE_MISSION_KEY) || "";
    } catch (e) {
      return "";
    }
  }

  function saveFissureMission(m) {
    try {
      localStorage.setItem(FISSURE_MISSION_KEY, m || "");
    } catch (e) {}
  }

  function loadFissureMode() {
    try {
      var m = localStorage.getItem(FISSURE_MODE_KEY) || "all";
      return m === "normal" || m === "hard" || m === "storm" ? m : "all";
    } catch (e) {
      return "all";
    }
  }

  function saveFissureMode(m) {
    try {
      localStorage.setItem(FISSURE_MODE_KEY, m || "all");
    } catch (e) {}
  }

  function fetchJson(path) {
    return fetch(apiBase() + path + (path.indexOf("?") >= 0 ? "&" : "?") + "language=en", {
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
    if (!c) {
      return { mark: mark, name: name, state: "—", tone: "", expiry: null };
    }
    if (kind === "vallis") {
      return {
        mark: mark,
        name: name,
        state: c.isWarm ? "Warm" : "Cold",
        tone: c.isWarm ? "warm" : "cold",
        expiry: c.expiry,
      };
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
      return {
        mark: mark,
        name: name,
        state: c.state || "—",
        tone: "mood",
        expiry: c.expiry,
      };
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
    return {
      mark: mark,
      name: name,
      state: c.isDay ? "Day" : "Night",
      tone: c.isDay ? "day" : "night",
      expiry: c.expiry,
    };
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
            " · leaves <span class=\"wf-eta tick\" data-expiry=\"" +
            esc(vt.expiry) +
            '">' +
            esc(timeUntil(vt.expiry)) +
            "</span>"
        );
      } else if (vt.activation) {
        parts.push(
          "<strong>Baro</strong> next in <span class=\"wf-eta tick\" data-expiry=\"" +
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
          " · <span class=\"wf-eta tick\" data-expiry=\"" +
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

  function renderInventoryGrid(inv, emptyMsg) {
    if (!inv || !inv.length) {
      return '<p class="meta" style="margin-top:12px">' + esc(emptyMsg || "No inventory listed.") + "</p>";
    }
    var html = '<div class="wf-inv-grid">';
    inv.forEach(function (item) {
      var priceBits = [];
      if (item.ducats != null) priceBits.push("<em>" + esc(item.ducats) + "</em> ducats");
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
    var html = band("wf-trader", "Trader") + '<section class="wf-baro">';
    if (!vt) {
      return html + '<p class="wf-empty">Could not load Baro.</p></section>';
    }
    var active = isActiveWindow(vt.activation, vt.expiry);
    var loc = vt.location || "Unknown relay";
    html += '<div class="wf-baro-top"><div>';
    html +=
      '<span class="wf-baro-badge' +
      (active ? "" : " away") +
      '">' +
      (active ? "At relay" : "In transit") +
      "</span>";
    html += "<h2>Baro Ki'Teer</h2>";
    html += '<p class="wf-baro-loc"><strong>' + esc(loc) + "</strong></p>";
    html += "</div><div class=\"wf-baro-countdown\">";
    if (active) {
      html +=
        '<span class="label">Leaves in</span>' +
        '<span class="wf-eta tick" data-expiry="' +
        esc(vt.expiry) +
        '">' +
        esc(timeUntil(vt.expiry)) +
        "</span>";
    } else if (vt.activation) {
      html +=
        '<span class="label">Arrives in</span>' +
        '<span class="wf-eta tick" data-expiry="' +
        esc(vt.activation) +
        '">' +
        esc(timeUntil(vt.activation)) +
        "</span>";
    } else {
      html += '<span class="label">Status</span><span class="wf-eta">—</span>';
    }
    html += "</div></div>";

    var inv = vt.inventory || [];
    if (active) {
      html += renderInventoryGrid(inv, "Inventory not listed yet — check closer to arrival.");
      if (inv.length) {
        html += '<p class="meta" style="margin-top:12px">' + inv.length + " items in inventory</p>";
      }
    }
    return html + "</section>";
  }

  function renderVarzia(vt) {
    if (!vt) return "";
    var html = '<section class="wf-panel">' + head(vt.character || "Varzia", "baro");
    html +=
      '<p class="meta">' +
      esc(vt.location || "Maroo's Bazaar") +
      (vt.expiry ? " · ends in " + etaHtml(vt.expiry) : "") +
      "</p>";
    html += renderInventoryGrid(vt.inventory || [], "No vault inventory listed.");
    return html + "</section>";
  }

  function renderDarvo(list) {
    if (!list || !list.length) return "";
    var html = '<section class="wf-panel">' + head("Darvo deal", "ops") + '<ul class="wf-mission-list">';
    list.forEach(function (d) {
      html +=
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
    return html + "</ul></section>";
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
    var html =
      band("wf-cycles", "Cycles") +
      '<section class="wf-panel wf-cycles-wrap">' +
      head("Open-world cycles", "cycle") +
      '<div class="wf-cycle-grid">';
    items.forEach(function (c) {
      html +=
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
    return html + "</div></section></div>";
  }

  function renderMission(title, data, ico) {
    var html = '<section class="wf-panel">' + head(title, ico);
    if (!data) {
      return html + '<p class="wf-empty">No data.</p></section>';
    }
    var missions =
      data.variants && data.variants.length ? data.variants : data.missions || [];
    html +=
      '<p class="meta">' +
      esc(data.boss || "") +
      (data.faction ? " · " + esc(data.faction) : "") +
      (data.expiry ? " · resets in " + etaHtml(data.expiry) : "") +
      "</p>";
    if (!missions.length) {
      return html + '<p class="wf-empty">No missions listed.</p></section>';
    }
    html += '<ul class="wf-mission-list">';
    missions.forEach(function (m, idx) {
      html +=
        "<li><strong>" +
        (idx + 1) +
        ". " +
        esc(m.node || m.missionType || m.type || "?") +
        "</strong> · " +
        esc(m.missionType || m.type || "") +
        (m.modifier ? ' <span class="meta">— ' + esc(m.modifier) + "</span>" : "") +
        "</li>";
    });
    return html + "</ul></section>";
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
      html += '<section class="wf-panel">' + head(archimedeaTitle(entry), "ops");
      html +=
        '<p class="meta">' +
        (entry.expiry ? "Resets in " + etaHtml(entry.expiry) : "Active") +
        "</p>";
      var missions = entry.missions || [];
      if (missions.length) {
        html += '<ul class="wf-mission-list">';
        missions.forEach(function (m, idx) {
          var bits = [];
          if (m.deviation && m.deviation.name) bits.push(m.deviation.name);
          var risks = (m.risks || [])
            .map(function (r) {
              return r.name + (r.isHard ? " (hard)" : "");
            })
            .filter(Boolean);
          if (risks.length) bits.push(risks.join(", "));
          html +=
            "<li><strong>" +
            (idx + 1) +
            ". " +
            esc(m.missionType || "?") +
            "</strong>" +
            (m.faction ? " · " + esc(m.faction) : "") +
            (bits.length ? ' <span class="meta">— ' + esc(bits.join(" · ")) + "</span>" : "") +
            "</li>";
        });
        html += "</ul>";
      }
      var mods = entry.personalModifiers || [];
      if (mods.length) {
        html +=
          '<p class="meta" style="margin-top:10px">Personal: ' +
          esc(
            mods
              .map(function (m) {
                return m.name || m.key;
              })
              .join(", ")
          ) +
          "</p>";
      }
      html += "</section>";
    });
    return html;
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
    var nw = map["/nightwave"];
    if (nw) {
      var challenges = nw.activeChallenges || [];
      cards.push(
        '<div class="wf-mini-card"><strong>Nightwave</strong><span>Season ' +
          esc(nw.season != null ? nw.season : "?") +
          " · " +
          challenges.length +
          " active</span><span>" +
          (nw.expiry ? etaHtml(nw.expiry) + " left" : "") +
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
    if (!cards.length) return "";
    return (
      '<section class="wf-panel">' +
      head("Daily ops", "ops") +
      '<div class="wf-mini-row">' +
      cards.join("") +
      "</div></section>"
    );
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
    var hasBuild = construction && (construction.fomorianProgress || construction.razorbackProgress);

    if (!hasEvents && !hasBuild) {
      return html + '<section class="wf-panel">' + head("Events", "event") + '<p class="wf-empty">No active events.</p></section></div>';
    }

    if (hasEvents) {
      html += '<section class="wf-panel">' + head("Events", "event");
      list.forEach(function (ev) {
        var pct = eventProgress(ev);
        var rewardItems = [];
        (ev.rewards || []).forEach(function (r) {
          (r.items || []).forEach(function (it) {
            rewardItems.push(it);
          });
        });
        html += '<div class="wf-event-card">';
        html += "<h3>" + esc(ev.description || ev.tooltip || "Event") + "</h3>";
        html +=
          '<p class="meta">' +
          esc(ev.node || "") +
          (ev.expiry ? (ev.node ? " · " : "") + "ends in " + etaHtml(ev.expiry) : "") +
          "</p>";
        if (ev.tooltip && ev.tooltip !== ev.description) {
          html += '<p class="wf-event-tip">' + esc(ev.tooltip) + "</p>";
        }
        if (pct != null) {
          html +=
            '<div class="wf-progress" role="progressbar" aria-valuenow="' +
            Math.round(pct) +
            '" aria-valuemin="0" aria-valuemax="100"><span style="width:' +
            pct.toFixed(1) +
            '%"></span></div>';
          html += '<p class="meta">' + Math.round(pct) + "% complete</p>";
        }
        if (rewardItems.length) {
          html += '<p class="meta">Rewards: ' + esc(rewardItems.slice(0, 6).join(", ")) + "</p>";
        }
        html += "</div>";
      });
      html += "</section>";
    }

    if (hasBuild) {
      html += '<section class="wf-panel">' + head("Construction", "build");
      var bars = [
        { label: "Fomorian", value: construction.fomorianProgress },
        { label: "Razorback", value: construction.razorbackProgress },
      ];
      bars.forEach(function (b) {
        var n = Math.max(0, Math.min(100, parseFloat(b.value) || 0));
        html +=
          '<div class="wf-build-row"><span>' +
          esc(b.label) +
          '</span><div class="wf-progress"><span style="width:' +
          n.toFixed(1) +
          '%"></span></div><em>' +
          n.toFixed(1) +
          "%</em></div>";
      });
      html += "</section>";
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
    return (list || [])
      .filter(function (f) {
        return !f.expired;
      })
      .slice()
      .sort(function (a, b) {
        var ra = tierRank(a.tier || a.tierNum);
        var rb = tierRank(b.tier || b.tierNum);
        if (ra !== rb) return ra - rb;
        var ea = parseTime(a.expiry) || 0;
        var eb = parseTime(b.expiry) || 0;
        return ea - eb;
      });
  }

  function filterFissures(list) {
    var tiers = loadFissureTiers();
    var mission = loadFissureMission();
    var mode = loadFissureMode();
    return list.filter(function (f) {
      var label = tierLabel(f.tier || f.tierNum);
      if (tiers.indexOf(label) < 0) return false;
      if (mission && String(f.missionType || "") !== mission) return false;
      if (mode === "hard" && !f.isHard) return false;
      if (mode === "storm" && !f.isStorm) return false;
      if (mode === "normal" && (f.isHard || f.isStorm)) return false;
      return true;
    });
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

    html += '<div class="wf-filter-row"><span class="wf-filter-label">Mode</span><div class="wf-filter-chips" data-filter="mode">';
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

    if (types.length) {
      html += '<div class="wf-mission-summary" aria-label="Mission types for selected tiers">';
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
    if (!filtered.length) {
      return '<p class="wf-empty">No fissures match these filters.</p>';
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

    var html = "";
    groups.forEach(function (g) {
      html +=
        '<div class="wf-fissure-group">' +
        '<h3 class="wf-fissure-tier ' +
        esc(tierClass(g.tier)) +
        '">' +
        esc(g.label) +
        ' <span class="count">' +
        g.items.length +
        "</span></h3>" +
        '<div class="wf-chips">';
      g.items.forEach(function (f) {
        var tier = f.tier || f.tierNum || "?";
        html +=
          '<span class="wf-chip ' +
          tierClass(tier) +
          '"><span class="tier">' +
          esc(tier) +
          "</span>" +
          esc(f.node || "?") +
          "<em>" +
          esc(f.missionType || "") +
          (f.isStorm ? " · Storm" : "") +
          (f.isHard ? " · SP" : "") +
          (f.expiry ? " · " + timeUntil(f.expiry) : "") +
          "</em></span>";
      });
      html += "</div></div>";
    });
    return html;
  }

  function renderFissures(list) {
    lastFissures = activeFissures(list);
    var filtered = filterFissures(lastFissures);
    var html =
      band("wf-void", "Void") +
      '<section class="wf-panel">' +
      head("Void fissures", "void");
    if (!lastFissures.length) {
      return html + '<p class="wf-empty">No fissures right now.</p></section></div>';
    }
    html += renderFissureFilters(lastFissures);
    html +=
      '<p class="meta wf-fissure-count" id="wf-fissure-count">Showing ' +
      filtered.length +
      " of " +
      lastFissures.length +
      " active</p>";
    html += '<div id="wf-fissure-list">' + renderFissureList(filtered) + "</div>";
    return html + "</section></div>";
  }

  function refreshFissurePanel() {
    var filtersHost = document.getElementById("wf-fissure-filters");
    var listHost = document.getElementById("wf-fissure-list");
    var countEl = document.getElementById("wf-fissure-count");
    if (!listHost) return;
    var filtered = filterFissures(lastFissures);
    if (filtersHost) {
      filtersHost.outerHTML = renderFissureFilters(lastFissures);
      bindFissureFilters();
    }
    listHost.innerHTML = renderFissureList(filtered);
    if (countEl) {
      countEl.textContent =
        "Showing " + filtered.length + " of " + lastFissures.length + " active";
    }
  }

  function bindFissureFilters() {
    var host = document.getElementById("wf-fissure-filters");
    if (!host) return;

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
        // Drop mission filter if it no longer exists for selected tiers
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

  function renderAlerts(list) {
    if (!list || !list.length) return "";
    var html = '<section class="wf-panel">' + head("Alerts", "alert") + '<ul class="wf-mission-list">';
    list.slice(0, 8).forEach(function (a) {
      var mission = a.mission || {};
      html +=
        "<li><strong>" +
        esc(mission.node || a.tag || "Alert") +
        "</strong> · " +
        esc(mission.type || "") +
        (a.expiry ? " — " + etaHtml(a.expiry) : "") +
        "</li>";
    });
    return html + "</ul></section>";
  }

  function renderInvasions(list) {
    var html =
      band("wf-invasions", "Invasions") +
      '<section class="wf-panel">' +
      head("Invasions", "invasion");
    if (!list || !list.length) {
      return html + '<p class="wf-empty">No invasions.</p></section></div>';
    }
    var open = list
      .filter(function (i) {
        return !i.completed;
      })
      .slice(0, 8);
    if (!open.length) {
      return html + '<p class="wf-empty">No active invasions.</p></section></div>';
    }
    html += '<ul class="wf-mission-list">';
    open.forEach(function (i) {
      var prog = i.completion != null ? Math.round(Number(i.completion)) + "%" : "";
      html +=
        "<li><strong>" +
        esc(i.node || "?") +
        "</strong> · " +
        esc(i.desc || "") +
        (prog ? ' <span class="meta">— ' + prog + "</span>" : "") +
        "</li>";
    });
    return html + "</ul></section></div>";
  }

  function newsMessage(n) {
    if (n.translations && n.translations.en) return n.translations.en;
    return n.message || "News";
  }

  function renderNews(list) {
    var html =
      band("wf-news", "News") +
      '<section class="wf-panel">' +
      head("News", "news");
    if (!list || !list.length) {
      return html + '<p class="wf-empty">No news.</p></section></div>';
    }
    var items = list
      .filter(function (n) {
        var t = parseTime(n.date);
        return t == null || t > Date.parse("2000-01-01");
      })
      .slice()
      .sort(function (a, b) {
        return (parseTime(b.date) || 0) - (parseTime(a.date) || 0);
      })
      .slice(0, 10);

    if (!items.length) {
      return html + '<p class="wf-empty">No recent news.</p></section></div>';
    }

    html += '<ul class="wf-news-list">';
    items.forEach(function (n) {
      var msg = newsMessage(n);
      var tags = [];
      if (n.update) tags.push("Update");
      if (n.primeAccess) tags.push("Prime Access");
      if (n.stream) tags.push("Stream");
      if (n.priority) tags.push("Priority");
      html += "<li>";
      if (n.link) {
        html +=
          '<a href="' +
          esc(n.link) +
          '" target="_blank" rel="noopener noreferrer">' +
          esc(msg) +
          "</a>";
      } else {
        html += "<strong>" + esc(msg) + "</strong>";
      }
      if (tags.length || n.date) {
        html +=
          ' <span class="meta">' +
          (tags.length ? esc(tags.join(" · ")) : "") +
          (tags.length && n.date ? " · " : "") +
          (n.date ? esc(new Date(n.date).toLocaleDateString()) : "") +
          "</span>";
      }
      html += "</li>";
    });
    return html + "</ul></section></div>";
  }

  function skeleton() {
    return (
      '<div class="wf-skel-grid">' +
      '<div class="wf-skel-card tall"></div>' +
      '<div class="wf-skel-row">' +
      '<div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div>' +
      "</div>" +
      '<div class="wf-skel-card"></div><div class="wf-skel-card"></div>' +
      "</div>"
    );
  }

  function tickEtas() {
    document.querySelectorAll(".wf-eta[data-expiry]").forEach(function (node) {
      var iso = node.getAttribute("data-expiry");
      if (iso) node.textContent = timeUntil(iso);
    });
  }

  function render(bundle) {
    if (!root) return;
    lastBundle = bundle;
    var map = bundle.map;
    updateTeaser(map);

    var html = "";
    html += renderBaro(map["/voidTrader"]);
    var side = renderVarzia(map["/vaultTrader"]) + renderDarvo(map["/dailyDeals"]);
    if (side) {
      html += '<div class="wf-grid-2" style="margin-top:16px">' + side + "</div>";
    }
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
    html += renderEvents(map["/events"], map["/constructionProgress"]);
    html += renderFissures(map["/fissures"]);
    html += renderNews(map["/news"]);
    html += renderAlerts(map["/alerts"]);
    html += renderInvasions(map["/invasions"]);
    root.innerHTML = html;
    root.removeAttribute("aria-busy");
    bindFissureFilters();

    var platName = PLATFORMS[platform] || "PC";
    if (bundle.fails === 0) {
      setStatus(true, "Live · " + platName + " · updated " + new Date().toLocaleTimeString());
    } else if (bundle.fails < bundle.total) {
      setStatus(
        true,
        "Partial · " +
          bundle.fails +
          " failed · " +
          platName +
          " · " +
          new Date().toLocaleTimeString()
      );
    } else {
      setStatus(false, "Could not reach Warframe world-state API");
    }
  }

  function refresh() {
    setStatus(true, "Refreshing…");
    if (root && !root.dataset.ready) {
      root.innerHTML = skeleton();
    }
    return loadAll()
      .then(function (bundle) {
        if (root) root.dataset.ready = "1";
        render(bundle);
      })
      .catch(function () {
        setStatus(false, "Could not reach Warframe world-state API");
        if (root && !root.dataset.ready) {
          root.innerHTML =
            '<p class="wf-empty">Unable to load world state. Try again in a moment.</p>';
        }
      });
  }

  savePlatform(platform);

  if (platformSelect) {
    platformSelect.value = platform;
    platformSelect.addEventListener("change", function () {
      savePlatform(platformSelect.value);
      if (root) delete root.dataset.ready;
      refresh();
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
