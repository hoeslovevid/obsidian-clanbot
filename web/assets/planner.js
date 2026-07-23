/** Prime wish list to relic and fissure targets. */
(function () {
  var API = "https://api.warframestat.us", TIERS = ["Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia"];
  var form = document.getElementById("plan-form"), input = document.getElementById("plan-query"), wantsEl = document.getElementById("plan-wants"), statusEl = document.getElementById("plan-status"), root = document.getElementById("plan-root");
  var wants = [], timer = 0;
  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function get(path) { return fetch(API + path + (path.indexOf("?") >= 0 ? "&" : "?") + "language=en", { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }); }
  function sync() { var u = new URL(location.href); if (wants.length) u.searchParams.set("want", wants.join(",")); else u.searchParams.delete("want"); history.replaceState(null, "", u.pathname + u.search); wantsEl.innerHTML = wants.map(function (w, i) { return '<button type="button" class="tool-pill on" data-remove="' + i + '" title="Remove">' + esc(w) + " ×</button>"; }).join(""); }
  function tierOf(n) { var m = String(n || "").match(/^(Lith|Meso|Neo|Axi|Requiem|Omnia)\b/i); return m ? m[1][0].toUpperCase() + m[1].slice(1).toLowerCase() : ""; }
  function rewardNames(r) { return (r.rewards || []).map(function (x) { return String((x.item && x.item.name) || x.itemName || x.name || "").toLowerCase(); }); }
  function render(relics, fissures) {
    var by = {}; TIERS.forEach(function (t) { by[t] = []; });
    relics.forEach(function (r) { var t = tierOf(r.name); if (by[t]) by[t].push(r); });
    var html = "";
    TIERS.forEach(function (tier) {
      if (!by[tier].length) return;
      html += '<section class="tool-card"><h2>' + esc(tier) + '</h2><div class="tool-pills">';
      by[tier].sort(function (a, b) { return a.name.localeCompare(b.name); }).forEach(function (r) { var name = String(r.name).replace(/\s+Intact$/i, ""); html += '<a class="tool-pill" href="/relics.html?q=' + encodeURIComponent(name) + '">' + esc(name) + "</a>"; });
      html += '</div><h3 style="margin-top:16px">Live matching fissures</h3><ul class="tool-list">';
      var live = fissures.filter(function (f) { return String(f.tier).toLowerCase() === tier.toLowerCase(); });
      if (!live.length) html += "<li>No live " + esc(tier) + " fissures.</li>";
      live.forEach(function (f) { html += '<li><a href="/warframe.html?section=void&tiers=' + encodeURIComponent(tier) + '"><strong>' + esc(f.node || "Unknown node") + "</strong></a> · " + esc(f.missionType || "") + (f.isStorm ? " · Void Storm" : "") + "</li>"; });
      html += "</ul></section>";
    });
    root.innerHTML = html || '<div class="tool-card"><p class="tool-prose">No intact relics currently matched those names. Try the exact in-game part name.</p></div>';
    statusEl.innerHTML = '<span class="dot"></span>' + relics.length + " unique matching relic" + (relics.length === 1 ? "" : "s");
  }
  function plan() {
    clearTimeout(timer); sync(); if (!wants.length) { root.innerHTML = ""; statusEl.innerHTML = '<span class="dot"></span>Add a wanted part'; return; }
    statusEl.innerHTML = '<span class="dot"></span>Searching relic rewards…'; root.setAttribute("aria-busy", "true");
    var relicRequests = TIERS.map(function (t) { return get("/items/search/" + encodeURIComponent(t)).catch(function () { return []; }); });
    var itemRequests = wants.map(function (w) { return get("/items/search/" + encodeURIComponent(w)).catch(function () { return []; }); });
    Promise.all([Promise.all(relicRequests), Promise.all(itemRequests), get("/pc/fissures")]).then(function (all) {
      var targets = wants.map(function (x) { return x.toLowerCase(); });
      all[1].forEach(function (rows, i) { rows.forEach(function (x) { if (String(x.name || "").toLowerCase().indexOf(targets[i]) >= 0) targets.push(String(x.name).toLowerCase()); }); });
      var seen = {}, relics = [];
      [].concat.apply([], all[0]).forEach(function (r) {
        if (r.type !== "Relic" || !/\sIntact$/i.test(r.name || "")) return;
        if (!rewardNames(r).some(function (n) { return targets.some(function (t) { return n.indexOf(t) >= 0 || t.indexOf(n) >= 0; }); })) return;
        if (!seen[r.name]) { seen[r.name] = true; relics.push(r); }
      });
      render(relics, all[2] || []); root.setAttribute("aria-busy", "false");
    }).catch(function () { statusEl.className = "tool-status err"; statusEl.innerHTML = '<span class="dot"></span>Planner data unavailable'; root.setAttribute("aria-busy", "false"); });
  }
  form.addEventListener("submit", function (e) { e.preventDefault(); var q = input.value.trim(); if (q && wants.indexOf(q) < 0) wants.push(q); input.value = ""; plan(); });
  wantsEl.addEventListener("click", function (e) { var b = e.target.closest("[data-remove]"); if (!b) return; wants.splice(Number(b.getAttribute("data-remove")), 1); plan(); });
  try { var raw = new URLSearchParams(location.search).get("want"); if (raw) wants = raw.split(",").map(function (x) { return x.trim(); }).filter(Boolean).slice(0, 12); } catch (_) {}
  plan();
})();
