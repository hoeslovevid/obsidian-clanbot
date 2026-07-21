/**
 * Public Warframe world-state page — fetches api.warframestat.us (no bot login).
 */
(function () {
  var API = "https://api.warframestat.us/pc";
  var REFRESH_MS = 60 * 1000;
  var root = document.getElementById("wf-root");
  var statusEl = document.getElementById("wf-status");
  var teaserEl = document.getElementById("wf-teaser");
  var refreshBtn = document.getElementById("wf-refresh");
  var timer = null;
  var tickTimer = null;
  var lastBundle = null;

  var ICO = {
    baro: '<svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5M2 12l10 5 10-5"/></svg>',
    cycle: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
    sortie: '<svg viewBox="0 0 24 24"><path d="M14.5 17.5L3 6V3h3l11.5 11.5M13 19l6-6M16 16l4 4"/></svg>',
    archon: '<svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
    ops: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    void: '<svg viewBox="0 0 24 24"><path d="M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3z"/></svg>',
    alert: '<svg viewBox="0 0 24 24"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg>',
    invasion: '<svg viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
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

  function fetchJson(path) {
    return fetch(API + path + (path.indexOf("?") >= 0 ? "&" : "?") + "language=en", {
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
      "/cetusCycle",
      "/vallisCycle",
      "/cambionCycle",
      "/earthCycle",
      "/duviriCycle",
      "/sortie",
      "/archonHunt",
      "/steelPath",
      "/arbitration",
      "/nightwave",
      "/fissures",
      "/alerts",
      "/invasions",
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
    var mark = { cetus: "C", vallis: "V", cambion: "D", earth: "E", duviri: "U" }[kind] || "?";
    var name = {
      cetus: "Cetus",
      vallis: "Orb Vallis",
      cambion: "Cambion Drift",
      earth: "Earth",
      duviri: "Duviri",
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

  function renderBaro(vt) {
    var html = band("wf-trader", "Trader") + '<section class="wf-baro">';
    if (!vt) {
      return html + '<p class="wf-empty">Could not load Baro.</p></section></div>';
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
    if (active && inv.length) {
      html += '<div class="wf-inv-grid">';
      inv.slice(0, 16).forEach(function (item) {
        html +=
          '<div class="wf-inv-item"><span class="name">' +
          esc(item.item || item.name || "?") +
          '</span><span class="price"><em>' +
          esc(item.ducats != null ? item.ducats : "—") +
          "</em> ducats · " +
          esc(item.credits != null ? item.credits : "—") +
          " cr</span></div>";
      });
      html += "</div>";
      if (inv.length > 16) {
        html +=
          '<p class="meta" style="margin-top:12px">Showing 16 of ' +
          inv.length +
          " · full list via <code>/baro</code> in Discord</p>";
      }
    } else if (active) {
      html += '<p class="meta" style="margin-top:12px">Inventory not listed yet — check closer to arrival.</p>';
    }
    return html + "</section></div>";
  }

  function renderCycles(map) {
    var items = [
      cycleInfo(map["/cetusCycle"], "cetus"),
      cycleInfo(map["/vallisCycle"], "vallis"),
      cycleInfo(map["/cambionCycle"], "cambion"),
      cycleInfo(map["/earthCycle"], "earth"),
      cycleInfo(map["/duviriCycle"], "duviri"),
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
        (c.expiry
          ? '<div class="eta">' + etaHtml(c.expiry) + " left</div>"
          : "") +
        "</div>";
    });
    return html + "</div></section></div>";
  }

  function renderMission(title, data, ico) {
    var html = '<section class="wf-panel">' + head(title, ico);
    if (!data) {
      return html + '<p class="wf-empty">No data.</p></section>';
    }
    var missions = data.variants || data.missions || [];
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
        esc(m.node || m.missionType || "?") +
        "</strong> · " +
        esc(m.missionType || m.type || "") +
        (m.modifier ? ' <span class="meta">— ' + esc(m.modifier) + "</span>" : "") +
        "</li>";
    });
    return html + "</ul></section>";
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
    if (!cards.length) return "";
    return (
      '<section class="wf-panel">' +
      head("Daily ops", "ops") +
      '<div class="wf-mini-row">' +
      cards.join("") +
      "</div></section>"
    );
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

  function renderFissures(list) {
    var html =
      band("wf-void", "Void") +
      '<section class="wf-panel">' +
      head("Void fissures", "void");
    if (!list || !list.length) {
      return html + '<p class="wf-empty">No fissures right now.</p></section></div>';
    }
    var active = list
      .filter(function (f) {
        return !f.expired;
      })
      .slice(0, 16);
    html += '<div class="wf-chips">';
    active.forEach(function (f) {
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
        "</em></span>";
    });
    return html + "</div></section></div>";
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

  function skeleton() {
    return (
      '<div class="wf-skel-grid">' +
      '<div class="wf-skel-card tall"></div>' +
      '<div class="wf-skel-row">' +
      '<div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div><div class="wf-skel-card"></div>' +
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
    html += renderCycles(map);
    html += band("wf-missions", "Missions");
    html += '<div class="wf-grid-2">';
    html += renderMission("Sortie", map["/sortie"], "sortie");
    html += renderMission("Archon hunt", map["/archonHunt"], "archon");
    html += "</div>";
    html += renderDaily(map);
    html += "</div>";
    html += renderFissures(map["/fissures"]);
    html += renderAlerts(map["/alerts"]);
    html += renderInvasions(map["/invasions"]);
    root.innerHTML = html;
    root.removeAttribute("aria-busy");

    if (bundle.fails === 0) {
      setStatus(true, "Live · PC · updated " + new Date().toLocaleTimeString());
    } else if (bundle.fails < bundle.total) {
      setStatus(true, "Partial · " + bundle.fails + " failed · " + new Date().toLocaleTimeString());
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
          root.innerHTML = '<p class="wf-empty">Unable to load world state. Try again in a moment.</p>';
        }
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
