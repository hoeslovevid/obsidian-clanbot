/**
 * Public Warframe world-state page — fetches api.warframestat.us (no bot login).
 */
(function () {
  var API = "https://api.warframestat.us/pc";
  var REFRESH_MS = 60 * 1000;
  var root = document.getElementById("wf-root");
  var statusEl = document.getElementById("wf-status");
  var refreshBtn = document.getElementById("wf-refresh");
  var timer = null;

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
    return m + "m";
  }

  function isActiveWindow(activation, expiry) {
    var a = parseTime(activation);
    var e = parseTime(expiry);
    var now = Date.now();
    if (a != null && e != null) return now >= a && now < e;
    if (e != null) return now < e;
    return false;
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
          function (err) {
            return { path: p, data: null, ok: false, err: err };
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

  function cycleLabel(c, kind) {
    if (!c) return { state: "—", name: kind };
    if (kind === "vallis") {
      return {
        state: c.isWarm ? "Warm" : "Cold",
        name: "Orb Vallis",
        expiry: c.expiry,
      };
    }
    if (kind === "cambion") {
      return {
        state: c.state || "—",
        name: "Cambion Drift",
        expiry: c.expiry,
      };
    }
    if (kind === "duviri") {
      return {
        state: c.state || "—",
        name: "Duviri",
        expiry: c.expiry,
      };
    }
    if (kind === "earth") {
      return {
        state: c.isDay ? "Day" : "Night",
        name: "Earth",
        expiry: c.expiry,
      };
    }
    return {
      state: c.isDay ? "Day" : "Night",
      name: "Cetus",
      expiry: c.expiry,
    };
  }

  function renderBaro(vt) {
    var html = '<section class="wf-panel"><h2>Baro Ki\'Teer</h2>';
    if (!vt) {
      return html + '<p class="wf-empty">Could not load Baro.</p></section>';
    }
    var active = isActiveWindow(vt.activation, vt.expiry);
    var loc = vt.location || "Unknown relay";
    if (active) {
      html +=
        '<p class="meta"><strong>' +
        esc(loc) +
        "</strong> · Leaves in " +
        esc(timeUntil(vt.expiry)) +
        "</p>";
      var inv = vt.inventory || [];
      if (inv.length) {
        html +=
          '<div class="wf-table-wrap"><table class="wf-table"><thead><tr><th>Item</th><th>Ducats</th><th>Credits</th></tr></thead><tbody>';
        inv.slice(0, 16).forEach(function (item) {
          html +=
            "<tr><td>" +
            esc(item.item || item.name || "?") +
            "</td><td>" +
            esc(item.ducats != null ? item.ducats : "—") +
            "</td><td>" +
            esc(item.credits != null ? item.credits : "—") +
            "</td></tr>";
        });
        html += "</tbody></table></div>";
        if (inv.length > 16) {
          html +=
            '<p class="meta" style="margin-top:8px">Showing 16 of ' +
            inv.length +
            " · full list in Discord via <code>/baro</code></p>";
        }
      } else {
        html += '<p class="meta" style="margin-top:8px">Inventory not listed yet — check again closer to arrival.</p>';
      }
    } else {
      html +=
        '<p class="meta">Not at a relay right now.' +
        (vt.activation ? " Next visit in <strong>" + esc(timeUntil(vt.activation)) + "</strong> · " + esc(loc) : "") +
        "</p>";
    }
    return html + "</section>";
  }

  function renderCycles(map) {
    var items = [
      cycleLabel(map["/cetusCycle"], "cetus"),
      cycleLabel(map["/vallisCycle"], "vallis"),
      cycleLabel(map["/cambionCycle"], "cambion"),
      cycleLabel(map["/earthCycle"], "earth"),
      cycleLabel(map["/duviriCycle"], "duviri"),
    ];
    var html =
      '<section class="wf-panel"><h2>Open-world cycles</h2><div class="wf-cycle-grid">';
    items.forEach(function (c) {
      html +=
        '<div class="wf-cycle-card"><div class="state">' +
        esc(c.state) +
        '</div><div class="name">' +
        esc(c.name) +
        "</div>" +
        (c.expiry ? '<div class="eta">' + esc(timeUntil(c.expiry)) + " left</div>" : "") +
        "</div>";
    });
    return html + "</div></section>";
  }

  function renderMission(title, data) {
    var html = '<section class="wf-panel"><h2>' + esc(title) + "</h2>";
    if (!data) {
      return html + '<p class="wf-empty">No data.</p></section>';
    }
    var missions = data.variants || data.missions || [];
    html +=
      '<p class="meta">' +
      esc(data.boss || "") +
      (data.faction ? " · " + esc(data.faction) : "") +
      (data.expiry ? " · resets in " + esc(timeUntil(data.expiry)) : "") +
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
          '</span><span class="meta">' +
          esc(timeUntil(sp.expiry)) +
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
          '</span><span class="meta">' +
          esc(arb.enemy || "") +
          (arb.expiry ? " · " + esc(timeUntil(arb.expiry)) : "") +
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
          ' active</span><span class="meta">' +
          (nw.expiry ? esc(timeUntil(nw.expiry)) + " left" : "") +
          "</span></div>"
      );
    }
    if (!cards.length) return "";
    return (
      '<section class="wf-panel"><h2>Daily ops</h2><div class="wf-mini-row">' +
      cards.join("") +
      "</div></section>"
    );
  }

  function renderFissures(list) {
    var html = '<section class="wf-panel"><h2>Void fissures</h2>';
    if (!list || !list.length) {
      return html + '<p class="wf-empty">No fissures right now.</p></section>';
    }
    var active = list
      .filter(function (f) {
        return !f.expired;
      })
      .slice(0, 14);
    html += '<div class="wf-chips">';
    active.forEach(function (f) {
      html +=
        '<span class="wf-chip">' +
        esc(f.tier || f.tierNum || "?") +
        " · " +
        esc(f.node || "?") +
        "<em>" +
        esc(f.missionType || "") +
        (f.isStorm ? " · Storm" : "") +
        (f.isHard ? " · SP" : "") +
        "</em></span>";
    });
    return html + "</div></section>";
  }

  function renderInvasions(list) {
    var html = '<section class="wf-panel"><h2>Invasions</h2>';
    if (!list || !list.length) {
      return html + '<p class="wf-empty">No invasions.</p></section>';
    }
    var open = list
      .filter(function (i) {
        return !i.completed;
      })
      .slice(0, 8);
    if (!open.length) {
      return html + '<p class="wf-empty">No active invasions.</p></section>';
    }
    html += '<ul class="wf-mission-list">';
    open.forEach(function (i) {
      var prog =
        i.completion != null ? Math.round(Number(i.completion)) + "%" : "";
      html +=
        "<li><strong>" +
        esc(i.node || "?") +
        "</strong> · " +
        esc(i.desc || "") +
        (prog ? ' <span class="meta">— ' + prog + "</span>" : "") +
        "</li>";
    });
    return html + "</ul></section>";
  }

  function renderAlerts(list) {
    if (!list || !list.length) return "";
    var html = '<section class="wf-panel"><h2>Alerts</h2><ul class="wf-mission-list">';
    list.slice(0, 8).forEach(function (a) {
      var mission = a.mission || {};
      html +=
        "<li><strong>" +
        esc(mission.node || a.tag || "Alert") +
        "</strong> · " +
        esc(mission.type || "") +
        (a.expiry ? ' <span class="meta">— ' + esc(timeUntil(a.expiry)) + "</span>" : "") +
        "</li>";
    });
    return html + "</ul></section>";
  }

  function render(bundle) {
    if (!root) return;
    var map = bundle.map;
    var html = "";
    html += renderBaro(map["/voidTrader"]);
    html += renderCycles(map);
    html += '<div class="wf-grid-2">';
    html += renderMission("Sortie", map["/sortie"]);
    html += renderMission("Archon hunt", map["/archonHunt"]);
    html += "</div>";
    html += renderDaily(map);
    html += renderFissures(map["/fissures"]);
    html += renderAlerts(map["/alerts"]);
    html += renderInvasions(map["/invasions"]);
    root.innerHTML = html;

    if (bundle.fails === 0) {
      setStatus(true, "Live · PC · updated " + new Date().toLocaleTimeString());
    } else if (bundle.fails < bundle.total) {
      setStatus(true, "Partial · " + bundle.fails + " sources failed · " + new Date().toLocaleTimeString());
    } else {
      setStatus(false, "Could not reach Warframe world-state API");
    }
  }

  function refresh() {
    if (statusEl) setStatus(true, "Refreshing…");
    if (root && !root.dataset.ready) {
      root.innerHTML = '<div class="wf-skeleton"></div><div class="wf-skeleton" style="margin-top:12px"></div>';
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

  if (refreshBtn) {
    refreshBtn.addEventListener("click", function () {
      refresh();
    });
  }

  refresh();
  timer = setInterval(refresh, REFRESH_MS);
  window.addEventListener("beforeunload", function () {
    if (timer) clearInterval(timer);
  });
})();
