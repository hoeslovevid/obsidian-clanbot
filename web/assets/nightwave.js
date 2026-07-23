/** Live Nightwave checklist. */
(function () {
  var API = "https://api.warframestat.us", KEY = "oo_nw_done_v1";
  var root = document.getElementById("nw-root"), statusEl = document.getElementById("nw-status"), clearBtn = document.getElementById("nw-clear");
  var state = { season: "", done: {} };
  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function relative(date) {
    var ms = new Date(date).getTime() - Date.now(), n = Math.max(0, Math.ceil(Math.abs(ms) / 3600000));
    if (n < 24) return (ms >= 0 ? "ends in " : "ended ") + n + "h" + (ms < 0 ? " ago" : "");
    var d = Math.ceil(n / 24); return (ms >= 0 ? "ends in " : "ended ") + d + "d" + (ms < 0 ? " ago" : "");
  }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) {} }
  function load(season) {
    try { var x = JSON.parse(localStorage.getItem(KEY) || "{}"); if (x.season === season && x.done) state = x; else state = { season: season, done: {} }; }
    catch (_) { state = { season: season, done: {} }; }
    save();
  }
  function idOf(a, i) { return String(a.id || a.uniqueName || a.title || ("act-" + i)); }
  function groupOf(a) {
    if (a.isDaily) return "Daily";
    if (a.isElite) return "Elite";
    return "Weekly";
  }
  function render(data) {
    var acts = data.activeChallenges || data.activeChallenges || [];
    var groups = { Daily: [], Weekly: [], Elite: [] };
    acts.forEach(function (a) { groups[groupOf(a)].push(a); });
    var html = "";
    ["Daily", "Weekly", "Elite"].forEach(function (label) {
      html += '<section class="tool-card"><h2>' + label + '</h2><ul class="tool-list">';
      if (!groups[label].length) html += "<li>No active " + label.toLowerCase() + " challenges.</li>";
      groups[label].forEach(function (a, i) {
        var id = idOf(a, i), checked = !!state.done[id];
        html += '<li><label class="tool-toggle"><input type="checkbox" data-id="' + esc(id) + '"' + (checked ? " checked" : "") + " /> <span><strong>" + esc(a.title || a.desc || "Challenge") + "</strong>";
        if (a.title && a.desc) html += "<br>" + esc(a.desc);
        html += " · " + esc(a.reputation || 0) + " standing";
        if (a.expiry) html += " · " + esc(relative(a.expiry));
        html += "</span></label></li>";
      });
      html += "</ul></section>";
    });
    root.innerHTML = html; root.setAttribute("aria-busy", "false");
  }
  fetch(API + "/pc/nightwave?language=en", { cache: "no-store", headers: { Accept: "application/json" } })
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(function (data) {
      var season = String(data.id || data.season || data.tag || data.params || data.activation || "nightwave");
      load(season);
      var phase = data.phase != null ? data.phase : (data.rewardTypes ? "Current season" : "Active");
      statusEl.innerHTML = '<span class="dot" aria-hidden="true"></span>Season ' + esc(data.season != null ? data.season : (data.tag || "Nightwave")) + " · Phase " + esc(phase) + (data.expiry ? " · " + esc(relative(data.expiry)) : "");
      render(data);
    })
    .catch(function () { statusEl.className += " err"; statusEl.innerHTML = '<span class="dot"></span>Could not load Nightwave'; root.innerHTML = '<div class="tool-card"><p class="tool-prose">The world-state API is unavailable. Try again shortly.</p></div>'; root.setAttribute("aria-busy", "false"); });
  root.addEventListener("change", function (e) { var id = e.target.getAttribute("data-id"); if (!id) return; if (e.target.checked) state.done[id] = true; else delete state.done[id]; save(); });
  clearBtn.addEventListener("click", function () { state.done = {}; save(); root.querySelectorAll('input[type="checkbox"]').forEach(function (x) { x.checked = false; }); });
})();
