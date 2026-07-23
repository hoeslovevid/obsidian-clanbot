/** Steel Path weekly rotation. */
(function () {
  var root = document.getElementById("sp-root"), statusEl = document.getElementById("sp-status");
  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function rel(d) { var h = Math.max(0, Math.ceil((new Date(d).getTime() - Date.now()) / 3600000)); return h < 48 ? h + "h remaining" : Math.ceil(h / 24) + "d remaining"; }
  function rewardName(x) { return typeof x === "string" ? x : ((x && (x.name || x.item || x.reward)) || "Unknown reward"); }
  function rewardLine(x) { var n = rewardName(x), cost = x && typeof x === "object" ? x.cost : null; return "<strong>" + esc(n) + "</strong>" + (cost != null ? " · " + esc(cost) + " Steel Essence" : "") + (/riven/i.test(n) ? ' · <a href="/rivens.html">Riven tool</a>' : ""); }
  fetch("https://api.warframestat.us/pc/steelPath?language=en", { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error(); return r.json(); }).then(function (d) {
    var current = d.currentReward || {}, rotation = d.rotation || [];
    statusEl.innerHTML = '<span class="dot"></span>' + esc(rewardName(current)) + (d.expiry ? " · " + esc(rel(d.expiry)) : d.remaining ? " · " + esc(d.remaining) : "");
    var html = '<section class="tool-card"><h2>Current reward</h2><p class="tool-prose">' + rewardLine(current) + "</p></section>";
    html += '<section class="tool-card"><h2>Full rotation</h2><ol class="tool-list">';
    rotation.forEach(function (x) { var on = rewardName(x) === rewardName(current); html += "<li" + (on ? ' style="color:var(--accent-bright)"' : "") + ">" + (on ? "Current · " : "") + rewardLine(x) + "</li>"; });
    if (!rotation.length) html += "<li>No rotation data returned.</li>";
    html += "</ol></section>";
    var ever = d.evergreens || [];
    html += '<details class="tool-card"><summary><strong>Evergreen rewards</strong></summary><ul class="tool-list">';
    ever.forEach(function (x) { html += "<li>" + rewardLine(x) + "</li>"; }); if (!ever.length) html += "<li>No evergreen data returned.</li>"; html += "</ul></details>";
    var inc = d.incursions;
    if (inc) {
      var rows = Array.isArray(inc) ? inc : (inc.rewards || inc.missions || [inc]);
      html += '<section class="tool-card"><h2>Incursions</h2><ul class="tool-list">';
      rows.forEach(function (x) {
        var hasReward = typeof x === "string" || x.name || x.item || x.reward;
        html += "<li>" + (hasReward ? rewardLine(x) : "<strong>Daily Incursion window</strong>") + (x.node ? " · " + esc(x.node) : "") + (x.expiry ? " · " + esc(rel(x.expiry)) : "") + "</li>";
      });
      html += "</ul></section>";
    }
    root.innerHTML = html; root.setAttribute("aria-busy", "false");
  }).catch(function () { statusEl.className += " err"; statusEl.innerHTML = '<span class="dot"></span>Could not load Steel Path'; root.innerHTML = '<div class="tool-card">Steel Path data is unavailable.</div>'; root.setAttribute("aria-busy", "false"); });
})();
