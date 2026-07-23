/**
 * Slash command reference — loads /assets/commands.json
 */
(function () {
  var allCommands = [];
  var filterEl;
  var listEl;
  var countEl;

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function renderDiscovery(items) {
    var el = document.getElementById("cmd-discovery");
    if (!el || !items || !items.length) return;
    el.innerHTML = items
      .map(function (item) {
        var path = item.path || "";
        var cmd = path.indexOf(" ") >= 0 ? "/" + path : "/" + path;
        return (
          '<a href="#cmd-' +
          esc(path.replace(/\s+/g, "-")) +
          '">' +
          "<code>" +
          esc(cmd) +
          "</code>" +
          "<span>" +
          esc(item.blurb || "") +
          "</span></a>"
        );
      })
      .join("");
  }

  function renderGroups(groups) {
    var el = document.getElementById("cmd-groups");
    if (!el || !groups || !groups.length) return;
    el.innerHTML = groups
      .map(function (g) {
        return (
          '<div class="cmd-group">' +
          "<strong>/" +
          esc(g.path || "") +
          "</strong>" +
          esc(g.description || "") +
          "</div>"
        );
      })
      .join("");
  }

  function renderCommands(query) {
    if (!listEl) return;
    query = (query || "").toLowerCase().trim();
    var filtered = allCommands;
    if (query) {
      filtered = allCommands.filter(function (c) {
        var name = (c.name || "").toLowerCase();
        var desc = (c.description || "").toLowerCase();
        return name.indexOf(query) >= 0 || desc.indexOf(query) >= 0;
      });
    }
    if (countEl) {
      countEl.textContent =
        filtered.length === allCommands.length
          ? allCommands.length + " commands"
          : filtered.length + " of " + allCommands.length;
    }
    if (!filtered.length) {
      listEl.innerHTML = '<li class="cmd-empty">No commands match your search.</li>';
      return;
    }
    listEl.innerHTML = filtered
      .map(function (c) {
        return (
          '<li id="cmd-' +
          esc((c.name || "").replace(/\s+/g, "-")) +
          '"><code>/' +
          esc(c.name || "") +
          "</code> — " +
          esc(c.description || "") +
          "</li>"
        );
      })
      .join("");
  }

  function onFilter() {
    renderCommands(filterEl ? filterEl.value : "");
  }

  function showError(msg) {
    var el = document.getElementById("cmd-error");
    if (el) {
      el.textContent = msg;
      el.hidden = false;
    }
  }

  function init() {
    filterEl = document.getElementById("cmd-filter");
    listEl = document.getElementById("cmd-list");
    countEl = document.getElementById("cmd-count");
    if (filterEl) {
      filterEl.addEventListener("input", onFilter);
    }
    fetch("/assets/commands.json", { cache: "no-cache" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        allCommands = data.commands || [];
        allCommands.sort(function (a, b) {
          return (a.name || "").localeCompare(b.name || "");
        });
        renderDiscovery(data.discovery || []);
        renderGroups(data.groups || []);
        renderCommands("");
      })
      .catch(function () {
        showError("Could not load command list. Try again later.");
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
