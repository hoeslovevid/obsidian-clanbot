/** Baro Ki'Teer shopping list. */
(function () {
  var API = "https://api.warframestat.us", KEY = "oo_baro_list_v1";
  var root = document.getElementById("baro-root"), statusEl = document.getElementById("baro-status"), share = document.getElementById("baro-share");
  var state = { arrival: "", items: {} };
  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function rel(d) { var ms = new Date(d).getTime() - Date.now(), h = Math.max(0, Math.ceil(Math.abs(ms) / 3600000)); return (ms >= 0 ? "in " : "") + (h < 48 ? h + "h" : Math.ceil(h / 24) + "d") + (ms < 0 ? " ago" : ""); }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) {} }
  function load(identity) {
    try { var x = JSON.parse(localStorage.getItem(KEY) || "{}"); state = x.arrival === identity && x.items ? x : { arrival: identity, items: {} }; } catch (_) { state = { arrival: identity, items: {} }; }
    try { var list = new URLSearchParams(location.search).get("list"); if (list) list.split(",").forEach(function (n) { if (n.trim()) state.items[n.trim()] = true; }); } catch (_) {}
    save();
  }
  function skeletonHtml() {
    if (window.ObsidianSite && typeof window.ObsidianSite.skeletonCards === "function") {
      return window.ObsidianSite.skeletonCards(2);
    }
    return '<div class="tool-skeleton" aria-hidden="true"><div class="tool-card tool-skel-card"><div class="skel skel-title"></div><div class="skel skel-line"></div><div class="skel skel-line short"></div></div><div class="tool-card tool-skel-card"><div class="skel skel-title"></div><div class="skel skel-line"></div><div class="skel skel-line short"></div></div></div>';
  }
  function paint(html) {
    root.innerHTML = '<div class="tool-content-enter">' + html + "</div>";
    root.setAttribute("aria-busy", "false");
  }
  function render(d) {
    var inv = d.inventory || [];
    var active = d.active != null ? d.active : (Date.now() >= new Date(d.activation).getTime() && Date.now() < new Date(d.expiry).getTime());
    var html = '<section class="tool-card"><h2>' + esc(d.location || "Unknown relay") + '</h2><p class="tool-meta">' + (active ? "Baro is here" : "Baro is away") + " · " + (active ? "leaves " + rel(d.expiry) : "arrives " + rel(d.activation)) + '</p></section>';
    html += '<section class="tool-card"><h2>Inventory</h2><ul class="tool-list">';
    if (!inv.length) html += "<li>Inventory appears when Baro arrives.</li>";
    inv.forEach(function (it) {
      var name = it.item || it.name || "Unknown item";
      html += '<li><label class="tool-toggle"><input type="checkbox" data-name="' + esc(name) + '"' + (state.items[name] ? " checked" : "") + " /><span><strong>" + esc(name) + "</strong> · " + esc(it.ducats || 0) + " ducats · " + Number(it.credits || 0).toLocaleString("en-US") + ' credits</span></label><div class="tool-actions"><a href="/market.html?q=' + encodeURIComponent(name) + '">Market</a><a href="/worth.html?q=' + encodeURIComponent(name) + '">Ducat or plat?</a></div></li>';
    });
    paint(html + "</ul></section>");
  }
  root.innerHTML = skeletonHtml();
  fetch(API + "/pc/voidTrader?language=en", { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error(); return r.json(); }).then(function (d) {
    var identity = String(d.activation || "") + "|" + String(d.expiry || "");
    var active = d.active != null ? d.active : (Date.now() >= new Date(d.activation).getTime() && Date.now() < new Date(d.expiry).getTime());
    load(identity); statusEl.innerHTML = '<span class="dot"></span>' + esc(active ? "Active" : "Away") + " · " + esc(d.location || "Unknown") + " · " + esc(active ? "leaves " + rel(d.expiry) : "arrives " + rel(d.activation)); render(d);
  }).catch(function () { statusEl.className += " err"; statusEl.innerHTML = '<span class="dot"></span>Could not load Baro'; paint('<div class="tool-card">Void Trader data is unavailable.</div>'); });
  root.addEventListener("change", function (e) { var n = e.target.getAttribute("data-name"); if (!n) return; if (e.target.checked) state.items[n] = true; else delete state.items[n]; save(); });
  share.addEventListener("click", function () { var u = new URL(location.href); u.searchParams.set("list", Object.keys(state.items).filter(function (n) { return state.items[n]; }).join(",")); var text = u.toString(); if (navigator.clipboard) navigator.clipboard.writeText(text); share.textContent = "Copied"; setTimeout(function () { share.textContent = "Copy share URL"; }, 1500); });
})();
