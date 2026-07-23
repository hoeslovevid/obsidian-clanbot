/**
 * Weapon Riven disposition table — api.warframestat.us /weapons
 */
(function () {
  var API = "https://api.warframestat.us";

  var queryEl = document.getElementById("rv-query");
  var typeEl = document.getElementById("rv-type");
  var bodyEl = document.getElementById("rv-body");
  var statusEl = document.getElementById("rv-status");
  var tableEl = document.getElementById("rv-table");

  var weapons = [];
  var sortKey = "disposition";
  var sortDir = -1;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setStatus(ok, text) {
    if (!statusEl) return;
    statusEl.className = "tool-status" + (ok ? "" : " err");
    statusEl.innerHTML = '<span class="dot" aria-hidden="true"></span>' + esc(text);
  }

  function fetchJson(path) {
    return fetch(API + path + (path.indexOf("?") >= 0 ? "&" : "?") + "language=en", {
      cache: "no-store",
      headers: { Accept: "application/json" },
    }).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    });
  }

  function marketUrl(name) {
    return "/market.html?q=" + encodeURIComponent(name || "");
  }

  function dispositionText(w) {
    var parts = [];
    if (w.disposition != null && !isNaN(w.disposition)) {
      parts.push("Disp " + w.disposition);
    }
    if (w.omegaAttenuation != null && !isNaN(w.omegaAttenuation)) {
      parts.push("\u03c9 " + Number(w.omegaAttenuation).toFixed(2));
    }
    return parts.length ? parts.join(" \u00b7 ") : "—";
  }

  function dispositionSort(w) {
    if (w.disposition != null && !isNaN(w.disposition)) return Number(w.disposition);
    if (w.omegaAttenuation != null && !isNaN(w.omegaAttenuation)) return Number(w.omegaAttenuation);
    return -1;
  }

  function filtered() {
    var q = queryEl ? (queryEl.value || "").trim().toLowerCase() : "";
    var type = typeEl ? typeEl.value : "";
    return weapons.filter(function (w) {
      if (type && (w.type || "") !== type) return false;
      if (q && String(w.name || "").toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
  }

  function sorted(list) {
    var key = sortKey;
    var dir = sortDir;
    return list.slice().sort(function (a, b) {
      var av;
      var bv;
      if (key === "name") {
        av = String(a.name || "");
        bv = String(b.name || "");
        return dir * av.localeCompare(bv);
      }
      if (key === "type") {
        av = String(a.type || "");
        bv = String(b.type || "");
        return dir * av.localeCompare(bv);
      }
      av = dispositionSort(a);
      bv = dispositionSort(b);
      return dir * (av - bv) || String(a.name || "").localeCompare(String(b.name || ""));
    });
  }

  function syncSortHeaders() {
    if (!tableEl) return;
    var ths = tableEl.querySelectorAll("th[data-sort]");
    ths.forEach(function (th) {
      var k = th.getAttribute("data-sort");
      if (k === sortKey) {
        th.setAttribute("aria-sort", sortDir < 0 ? "descending" : "ascending");
      } else {
        th.setAttribute("aria-sort", "none");
      }
    });
  }

  function render() {
    if (!bodyEl) return;
    var list = sorted(filtered());
    if (!list.length) {
      bodyEl.innerHTML = '<tr><td colspan="4" class="tool-meta" style="padding:14px">No weapons match.</td></tr>';
      setStatus(true, "0 weapons shown");
      syncSortHeaders();
      return;
    }
    var html = "";
    list.forEach(function (w) {
      html +=
        "<tr><td>" +
        esc(w.name) +
        '</td><td class="tool-meta">' +
        esc(w.type || w.category || "") +
        "</td><td>" +
        esc(dispositionText(w)) +
        '</td><td><a href="' +
        esc(marketUrl(w.name)) +
        '">Market</a> · <a href="/riven-grade.html?weapon=' +
        encodeURIComponent(w.name) +
        '">Grade</a></td></tr>';
    });
    bodyEl.innerHTML = html;
    setStatus(true, list.length + " of " + weapons.length + " weapons");
    syncSortHeaders();
  }

  function populateTypes() {
    if (!typeEl) return;
    var types = {};
    weapons.forEach(function (w) {
      if (w.type) types[w.type] = 1;
    });
    var keys = Object.keys(types).sort();
    keys.forEach(function (t) {
      var opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      typeEl.appendChild(opt);
    });
  }

  function load() {
    setStatus(true, "Loading weapons…");
    fetchJson("/weapons")
      .then(function (list) {
        weapons = list || [];
        weapons = weapons.filter(function (w) {
          return w.disposition != null || w.omegaAttenuation != null;
        });
        populateTypes();
        render();
      })
      .catch(function () {
        setStatus(false, "Could not load weapons.");
        if (bodyEl) {
          bodyEl.innerHTML =
            '<tr><td colspan="4" class="tool-meta" style="padding:14px">API request failed.</td></tr>';
        }
      });
  }

  if (queryEl) {
    queryEl.addEventListener("input", render);
  }

  if (typeEl) {
    typeEl.addEventListener("change", render);
  }

  if (tableEl) {
    tableEl.addEventListener("click", function (e) {
      var th = e.target.closest("th[data-sort]");
      if (!th) return;
      var key = th.getAttribute("data-sort");
      if (sortKey === key) sortDir = -sortDir;
      else {
        sortKey = key;
        sortDir = key === "name" || key === "type" ? 1 : -1;
      }
      render();
    });
  }

  load();
})();
