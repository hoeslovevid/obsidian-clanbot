/**
 * Riven grader — disposition ranges, roll quality, weekly trade averages.
 * Formula: value ≈ base × ω × configWeight × roll(0.9–1.1), scaled by rank.
 * Base tables: Warframe Wiki (community). Heuristic only.
 */
(function () {
  var API = "https://api.warframestat.us";
  var WEEKLY_URL = "https://www-static.warframe.com/repos/weeklyRivensPC.json";

  // Base values at max rank (rank 8) before disposition & config weight. Units: percent unless noted.
  // Classes: rifle, shotgun, pistol, archgun, melee
  var STATS = [
    { id: "ammo", label: "Ammo Maximum", unit: "%", bases: { rifle: 49.95, shotgun: 90, pistol: 90, archgun: 99.9 }, positiveOnly: false },
    { id: "cold", label: "Cold Damage", unit: "%", bases: { rifle: 90, shotgun: 90, pistol: 90, archgun: 119.7, melee: 90 }, positiveOnly: true },
    { id: "heat", label: "Heat Damage", unit: "%", bases: { rifle: 90, shotgun: 90, pistol: 90, archgun: 119.7, melee: 90 }, positiveOnly: true },
    { id: "elec", label: "Electricity Damage", unit: "%", bases: { rifle: 90, shotgun: 90, pistol: 90, archgun: 119.7, melee: 90 }, positiveOnly: true },
    { id: "toxin", label: "Toxin Damage", unit: "%", bases: { rifle: 90, shotgun: 90, pistol: 90, archgun: 119.7, melee: 90 }, positiveOnly: true },
    { id: "damage", label: "Damage", unit: "%", bases: { rifle: 165, shotgun: 164.7, pistol: 219.6, archgun: 99.9, melee: 164.7 }, positiveOnly: true },
    { id: "cc", label: "Critical Chance", unit: "%", bases: { rifle: 149.99, shotgun: 90, pistol: 149.99, archgun: 99.9, melee: 180 }, positiveOnly: false },
    { id: "cd", label: "Critical Damage", unit: "%", bases: { rifle: 120, shotgun: 90, pistol: 90, archgun: 80.1, melee: 90 }, positiveOnly: false },
    { id: "ms", label: "Multishot", unit: "%", bases: { rifle: 90, shotgun: 119.7, pistol: 119.7, archgun: 60.3 }, positiveOnly: false },
    { id: "sc", label: "Status Chance", unit: "%", bases: { rifle: 90, shotgun: 90, pistol: 90, archgun: 60.3, melee: 90 }, positiveOnly: false },
    { id: "sd", label: "Status Duration", unit: "%", bases: { rifle: 99.99, shotgun: 99.99, pistol: 99.99, archgun: 99.99, melee: 99.99 }, positiveOnly: false },
    { id: "fr", label: "Fire Rate / Attack Speed", unit: "%", bases: { rifle: 60.03, shotgun: 90, pistol: 74.7, archgun: 60.03, melee: 54.9 }, positiveOnly: false, bowNote: true },
    { id: "reload", label: "Reload Speed", unit: "%", bases: { rifle: 50, shotgun: 50, pistol: 50, archgun: 99.9 }, positiveOnly: false },
    { id: "mag", label: "Magazine Capacity", unit: "%", bases: { rifle: 50, shotgun: 50, pistol: 50, archgun: 60.3 }, positiveOnly: false },
    { id: "projectile", label: "Projectile Speed", unit: "%", bases: { rifle: 90, shotgun: 90, pistol: 90 }, positiveOnly: false },
    { id: "punch", label: "Punch Through", unit: "m", bases: { rifle: 2.7, shotgun: 2.7, pistol: 2.7, archgun: 2.7 }, positiveOnly: true },
    { id: "impact", label: "Impact Damage", unit: "%", bases: { rifle: 119.97, shotgun: 119.97, pistol: 119.97, archgun: 90, melee: 119.7 }, positiveOnly: false },
    { id: "puncture", label: "Puncture Damage", unit: "%", bases: { rifle: 119.97, shotgun: 119.97, pistol: 119.97, archgun: 90, melee: 119.7 }, positiveOnly: false },
    { id: "slash", label: "Slash Damage", unit: "%", bases: { rifle: 119.97, shotgun: 119.97, pistol: 119.97, archgun: 90, melee: 119.7 }, positiveOnly: false },
    { id: "recoil", label: "Weapon Recoil", unit: "%", bases: { rifle: 90, shotgun: 90, pistol: 90, archgun: 90 }, positiveOnly: false, goodNeg: true },
    { id: "zoom", label: "Zoom", unit: "%", bases: { rifle: 59.99, pistol: 80.1, archgun: 59.99 }, positiveOnly: false, goodNeg: true },
    { id: "d_corpus", label: "Damage vs Corpus", unit: "x", bases: { rifle: 0.45, shotgun: 0.45, pistol: 0.45, archgun: 0.45, melee: 0.45 }, positiveOnly: false, multiplier: true },
    { id: "d_grineer", label: "Damage vs Grineer", unit: "x", bases: { rifle: 0.45, shotgun: 0.45, pistol: 0.45, archgun: 0.45, melee: 0.45 }, positiveOnly: false, multiplier: true },
    { id: "d_infested", label: "Damage vs Infested", unit: "x", bases: { rifle: 0.45, shotgun: 0.45, pistol: 0.45, archgun: 0.45, melee: 0.45 }, positiveOnly: false, multiplier: true },
    { id: "range", label: "Range", unit: "m", bases: { melee: 1.94 }, positiveOnly: false },
    { id: "combo_dur", label: "Combo Duration", unit: "s", bases: { melee: 8.1 }, positiveOnly: false },
    { id: "initial_combo", label: "Initial Combo", unit: "", bases: { melee: 24.5 }, positiveOnly: false },
    { id: "finisher", label: "Finisher Damage", unit: "%", bases: { melee: 119.7 }, positiveOnly: false },
    { id: "slide_cc", label: "Slide Crit Chance", unit: "%", bases: { melee: 120 }, positiveOnly: false },
    { id: "heavy_eff", label: "Heavy Attack Efficiency", unit: "%", bases: { melee: 73.44 }, positiveOnly: false },
    { id: "combo_chance", label: "Combo Count Chance", unit: "%", bases: { melee: 58.77 }, positiveOnly: false },
  ];

  var WEIGHTS = {
    "2-0": { bonus: 0.99, malus: 0 },
    "2-1": { bonus: 1.2375, malus: -0.495 },
    "3-0": { bonus: 0.75, malus: 0 },
    "3-1": { bonus: 0.9375, malus: -0.75 },
  };

  var form = document.getElementById("rg-form");
  var weaponEl = document.getElementById("rg-weapon");
  var suggestEl = document.getElementById("rg-suggest");
  var metaEl = document.getElementById("rg-weapon-meta");
  var rankEl = document.getElementById("rg-rank");
  var posCountEl = document.getElementById("rg-pos-count");
  var hasNegEl = document.getElementById("rg-has-neg");
  var statsEl = document.getElementById("rg-stats");
  var statusEl = document.getElementById("rg-status");
  var resultEl = document.getElementById("rg-result");
  var clearBtn = document.getElementById("rg-clear");

  var weapons = [];
  var selected = null;
  var weekly = [];
  var suggestTimer = null;

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

  function omegaOf(w) {
    if (!w) return null;
    if (w.omegaAttenuation != null && !isNaN(w.omegaAttenuation)) return Number(w.omegaAttenuation);
    // Fallback map from 1–5 star disposition if ω missing
    var d = Number(w.disposition);
    if (!d || isNaN(d)) return null;
    var map = { 1: 0.5, 2: 0.7, 3: 0.9, 4: 1.1, 5: 1.3 };
    return map[Math.round(d)] || 1;
  }

  function rivenClass(w) {
    var t = String((w && (w.type || w.category || w.productCategory)) || "").toLowerCase();
    var n = String((w && w.name) || "").toLowerCase();
    if (/arch[- ]?gun|archgun|archwing gun/.test(t) || /archgun/.test(n)) return "archgun";
    if (/shotgun/.test(t)) return "shotgun";
    if (/pistol|secondary|kitgun/.test(t)) return "pistol";
    if (/melee|zaw|exalted/.test(t)) return "melee";
    if (/rifle|primary|sniper|bow|speargun|launcher|arm[- ]?cannon/.test(t)) return "rifle";
    if (/melee/.test(n)) return "melee";
    return "rifle";
  }

  function configKey(posCount, hasNeg) {
    return posCount + "-" + (hasNeg ? "1" : "0");
  }

  function rankScale(rank) {
    rank = Number(rank);
    if (isNaN(rank)) rank = 8;
    return (rank + 1) / 9;
  }

  function statsForClass(cls, forNeg) {
    return STATS.filter(function (s) {
      if (s.bases[cls] == null) return false;
      if (forNeg && s.positiveOnly) return false;
      return true;
    });
  }

  function rangeFor(stat, cls, omega, weight, rank, weapon) {
    var base = stat.bases[cls];
    if (base == null) return null;
    // Wiki: Fire Rate base is doubled for bows
    if (stat.bowNote && weapon) {
      var t = String(weapon.type || "").toLowerCase();
      var n = String(weapon.name || "").toLowerCase();
      if (/bow/.test(t) || /\bbow\b/.test(n)) base = base * 2;
    }
    var scale = rankScale(rank);
    var mid = base * omega * Math.abs(weight) * scale;
    return {
      min: mid * 0.9,
      max: mid * 1.1,
      mid: mid,
      unit: stat.unit,
    };
  }

  function rollFactor(value, mid) {
    if (!mid || !isFinite(mid) || mid === 0) return null;
    return Math.abs(Number(value)) / Math.abs(mid);
  }

  function gradeFromRoll(roll) {
    if (roll == null || !isFinite(roll)) return { letter: "?", pct: null, score: 0 };
    // Clamp slightly outside for user rounding
    var t = (roll - 0.9) / 0.2;
    t = Math.max(0, Math.min(1, t));
    var pct = Math.round(t * 100);
    var letter = "F";
    if (pct >= 95) letter = "S";
    else if (pct >= 85) letter = "A";
    else if (pct >= 70) letter = "B";
    else if (pct >= 50) letter = "C";
    else if (pct >= 30) letter = "D";
    return { letter: letter, pct: pct, score: t };
  }

  function letterFromAvg(scores) {
    if (!scores.length) return { letter: "?", pct: null };
    var avg = scores.reduce(function (a, b) { return a + b; }, 0) / scores.length;
    return gradeFromRoll(0.9 + avg * 0.2);
  }

  function advice(letter, hasGoodNeg, hasBadNeg) {
    if (letter === "S" || letter === "A") {
      return hasBadNeg
        ? "Strong positives — keep if the negative is tolerable; otherwise consider a safer roll."
        : "Excellent roll quality. Keep / price for trade.";
    }
    if (letter === "B") {
      return hasGoodNeg
        ? "Solid roll with a helpful negative. Keep for use or mid-tier trade."
        : "Decent — usable, but room to improve on a re-roll.";
    }
    if (letter === "C") return "Average. Fine as a budget riven; re-roll if you need endgame.";
    return "Weak roll quality. Re-roll unless the weapon is disposable.";
  }

  function parseWeekly(text) {
    try {
      return JSON.parse(text);
    } catch (_) {}
    try {
      // DE ships JS-like object literals (unquoted keys)
      // eslint-disable-next-line no-new-func
      return new Function("return (" + text + ");")();
    } catch (_) {
      return [];
    }
  }

  function weeklyFor(name) {
    if (!name || !weekly.length) return null;
    var n = String(name).toLowerCase();
    var rows = weekly.filter(function (r) {
      return r && r.compatibility && String(r.compatibility).toLowerCase() === n;
    });
    if (!rows.length) {
      rows = weekly.filter(function (r) {
        return r && r.compatibility && String(r.compatibility).toLowerCase().indexOf(n) >= 0;
      });
    }
    if (!rows.length) return null;
    var out = { unrolled: null, rerolled: null };
    rows.forEach(function (r) {
      if (r.rerolled) out.rerolled = r;
      else out.unrolled = r;
    });
    return out;
  }

  function searchWeapons(q, limit) {
    q = String(q || "").trim().toLowerCase();
    if (q.length < 2) return [];
    var scored = [];
    for (var i = 0; i < weapons.length; i++) {
      var w = weapons[i];
      var name = String(w.name || "").toLowerCase();
      var s = 0;
      if (name === q) s = 100;
      else if (name.startsWith(q)) s = 80;
      else if (name.indexOf(q) >= 0) s = 50;
      if (s > 0) scored.push({ s: s, w: w });
    }
    scored.sort(function (a, b) {
      if (b.s !== a.s) return b.s - a.s;
      return String(a.w.name).length - String(b.w.name).length;
    });
    return scored.slice(0, limit || 10).map(function (r) { return r.w; });
  }

  function hideSuggest() {
    if (!suggestEl) return;
    suggestEl.hidden = true;
    suggestEl.innerHTML = "";
  }

  function renderSuggest(list) {
    if (!suggestEl) return;
    if (!list.length) {
      hideSuggest();
      return;
    }
    suggestEl.innerHTML = list
      .map(function (w) {
        var o = omegaOf(w);
        return (
          '<li role="option" data-name="' +
          esc(w.name) +
          '"><span>' +
          esc(w.name) +
          "</span><span class=\"mk-tag\">ω " +
          (o != null ? o.toFixed(2) : "?") +
          "</span></li>"
        );
      })
      .join("");
    suggestEl.hidden = false;
  }

  function selectWeapon(w) {
    selected = w;
    hideSuggest();
    if (weaponEl) weaponEl.value = w.name || "";
    var o = omegaOf(w);
    var cls = rivenClass(w);
    if (metaEl) {
      metaEl.innerHTML =
        esc(w.type || "Weapon") +
        " · class <strong>" +
        esc(cls) +
        "</strong> · disposition " +
        esc(w.disposition != null ? w.disposition : "—") +
        " · ω <strong>" +
        (o != null ? o.toFixed(3) : "?") +
        "</strong>";
    }
    rebuildStatRows();
    try {
      var u = new URL(location.href);
      u.searchParams.set("weapon", w.name);
      history.replaceState(null, "", u.pathname + u.search);
    } catch (_) {}
  }

  function optionHtml(stats, selectedId) {
    return (
      '<option value="">Select…</option>' +
      stats
        .map(function (s) {
          return (
            '<option value="' +
            esc(s.id) +
            '"' +
            (s.id === selectedId ? " selected" : "") +
            ">" +
            esc(s.label) +
            "</option>"
          );
        })
        .join("")
    );
  }

  function rebuildStatRows() {
    if (!statsEl) return;
    var cls = selected ? rivenClass(selected) : "rifle";
    var posN = Number(posCountEl && posCountEl.value) || 3;
    var hasNeg = !!(hasNegEl && hasNegEl.checked);
    var posStats = statsForClass(cls, false);
    var negStats = statsForClass(cls, true);
    var html = "";
    for (var i = 0; i < posN; i++) {
      html +=
        '<div class="rg-row">' +
        '<label class="tool-field tool-field-grow"><span class="tool-label">Positive ' +
        (i + 1) +
        '</span><select class="tool-select rg-stat" data-role="pos" data-i="' +
        i +
        '">' +
        optionHtml(posStats) +
        "</select></label>" +
        '<label class="tool-field"><span class="tool-label">Value</span>' +
        '<input class="tool-input rg-val" data-role="pos" data-i="' +
        i +
        '" type="number" step="any" placeholder="e.g. 180.2" /></label>' +
        "</div>";
    }
    if (hasNeg) {
      html +=
        '<div class="rg-row">' +
        '<label class="tool-field tool-field-grow"><span class="tool-label">Negative</span><select class="tool-select rg-stat" data-role="neg">' +
        optionHtml(negStats) +
        "</select></label>" +
        '<label class="tool-field"><span class="tool-label">Value</span>' +
        '<input class="tool-input rg-val" data-role="neg" type="number" step="any" placeholder="e.g. -42.5" /></label>' +
        "</div>";
    }
    statsEl.innerHTML = html;
  }

  function fillSlots(parsedSlots) {
    if (!statsEl || !parsedSlots || !parsedSlots.length) return;
    var pos = parsedSlots.filter(function (s) {
      return s.polarity === "+" || (s.polarity == null && s.value >= 0);
    });
    var neg = parsedSlots.filter(function (s) {
      return s.polarity === "-" || (s.polarity == null && s.value < 0);
    });
    if (posCountEl) posCountEl.value = String(pos.length >= 3 ? 3 : 2);
    if (hasNegEl) hasNegEl.checked = neg.length > 0;
    rebuildStatRows();
    var posRows = statsEl.querySelectorAll('.rg-stat[data-role="pos"]');
    var posVals = statsEl.querySelectorAll('.rg-val[data-role="pos"]');
    pos.slice(0, posRows.length).forEach(function (slot, i) {
      if (posRows[i]) posRows[i].value = slot.id;
      if (posVals[i]) posVals[i].value = String(Math.abs(slot.value));
    });
    var negSel = statsEl.querySelector('.rg-stat[data-role="neg"]');
    var negVal = statsEl.querySelector('.rg-val[data-role="neg"]');
    if (neg.length && negSel && negVal) {
      negSel.value = neg[0].id;
      negVal.value = String(-Math.abs(neg[0].value));
    }
  }

  function findStat(id) {
    for (var i = 0; i < STATS.length; i++) if (STATS[i].id === id) return STATS[i];
    return null;
  }

  function readSlots() {
    var slots = [];
    if (!statsEl) return slots;
    statsEl.querySelectorAll(".rg-row").forEach(function (row) {
      var sel = row.querySelector(".rg-stat");
      var inp = row.querySelector(".rg-val");
      if (!sel || !inp) return;
      var id = sel.value;
      var raw = String(inp.value || "").trim();
      if (!id || !raw) return;
      var val = Number(raw);
      if (!isFinite(val)) return;
      slots.push({
        role: sel.getAttribute("data-role"),
        stat: findStat(id),
        value: val,
      });
    });
    return slots;
  }

  function formatRange(r) {
    if (!r) return "—";
    var u = r.unit || "";
    function fmt(n) {
      if (Math.abs(n) >= 10) return n.toFixed(1);
      return n.toFixed(2);
    }
    return fmt(r.min) + " – " + fmt(r.max) + (u ? " " + u : "");
  }

  function grade() {
    if (!selected) {
      setStatus(false, "Select a weapon first");
      return;
    }
    var omega = omegaOf(selected);
    if (omega == null) {
      setStatus(false, "No disposition data for this weapon");
      return;
    }
    var cls = rivenClass(selected);
    var posN = Number(posCountEl && posCountEl.value) || 3;
    var hasNeg = !!(hasNegEl && hasNegEl.checked);
    var weights = WEIGHTS[configKey(posN, hasNeg)];
    var rank = rankEl ? rankEl.value : 8;
    var slots = readSlots();
    var positives = slots.filter(function (s) { return s.role === "pos" && s.stat; });
    var negatives = slots.filter(function (s) { return s.role === "neg" && s.stat; });

    if (positives.length < 2) {
      setStatus(false, "Enter at least two positive stats with values");
      return;
    }

    var rows = [];
    var scores = [];
    var hasGoodNeg = false;
    var hasBadNeg = false;

    positives.forEach(function (slot) {
      var rng = rangeFor(slot.stat, cls, omega, weights.bonus, rank, selected);
      if (!rng) {
        rows.push({ label: slot.stat.label, note: "N/A for " + cls, grade: null });
        return;
      }
      var roll = rollFactor(slot.value, rng.mid);
      var g = gradeFromRoll(roll);
      scores.push(g.score);
      rows.push({
        label: slot.stat.label,
        value: slot.value,
        range: rng,
        roll: roll,
        grade: g,
        kind: "pos",
      });
    });

    negatives.forEach(function (slot) {
      var rng = rangeFor(slot.stat, cls, omega, weights.malus, rank, selected);
      if (!rng) return;
      var roll = rollFactor(slot.value, rng.mid);
      var g = gradeFromRoll(roll);
      if (slot.stat.goodNeg) hasGoodNeg = true;
      else hasBadNeg = true;
      rows.push({
        label: slot.stat.label + (slot.stat.goodNeg ? " (often good −)" : ""),
        value: slot.value,
        range: rng,
        roll: roll,
        grade: g,
        kind: "neg",
        goodNeg: !!slot.stat.goodNeg,
      });
    });

    var overall = letterFromAvg(scores);
    var tip = advice(overall.letter, hasGoodNeg, hasBadNeg);
    var market = weeklyFor(selected.name);

    var html =
      '<section class="tool-card rg-verdict">' +
      '<div class="rg-grade-hero">' +
      '<div class="rg-letter rg-letter-' +
      esc(overall.letter.toLowerCase()) +
      '">' +
      esc(overall.letter) +
      "</div>" +
      "<div><h2>" +
      esc(selected.name) +
      " riven</h2>" +
      '<p class="tool-meta">Overall ' +
      (overall.pct != null ? overall.pct + "% of max roll" : "—") +
      " · ω " +
      omega.toFixed(3) +
      " · " +
      esc(cls) +
      " · " +
      posN +
      "pos" +
      (hasNeg ? "+neg" : "") +
      " · rank " +
      esc(rank) +
      "</p>" +
      '<p class="tool-prose">' +
      esc(tip) +
      "</p></div></div>";

    html += '<ul class="tool-list rg-grade-list">';
    rows.forEach(function (r) {
      if (!r.grade) {
        html += "<li><strong>" + esc(r.label) + "</strong> — " + esc(r.note || "") + "</li>";
        return;
      }
      html +=
        "<li><div class=\"rg-line\"><strong>" +
        esc(r.label) +
        '</strong> <span class="rg-badge rg-letter-' +
        esc(r.grade.letter.toLowerCase()) +
        '">' +
        esc(r.grade.letter) +
        "</span></div>" +
        '<div class="tool-meta">Entered ' +
        esc(r.value) +
        (r.range.unit ? " " + esc(r.range.unit) : "") +
        " · range " +
        esc(formatRange(r.range)) +
        " · roll ×" +
        (r.roll != null ? r.roll.toFixed(3) : "?") +
        " (" +
        (r.grade.pct != null ? r.grade.pct + "%" : "?") +
        ")</div></li>";
    });
    html += "</ul>";

    if (market && (market.unrolled || market.rerolled)) {
      html += '<h3 class="tool-section-title" style="margin-top:16px;font-family:var(--font-display);font-size:1.05rem">Weekly trade snapshot (PC)</h3><ul class="tool-list">';
      if (market.unrolled) {
        html +=
          "<li><strong>Unrolled</strong> — avg " +
          esc(Math.round(market.unrolled.avg)) +
          "p · median " +
          esc(Math.round(market.unrolled.median || 0)) +
          "p · " +
          esc(market.unrolled.pop || 0) +
          " trades</li>";
      }
      if (market.rerolled) {
        html +=
          "<li><strong>Rerolled</strong> — avg " +
          esc(Math.round(market.rerolled.avg)) +
          "p · median " +
          esc(Math.round(market.rerolled.median || 0)) +
          "p · " +
          esc(market.rerolled.pop || 0) +
          " trades</li>";
      }
      html += "</ul><p class=\"tool-meta\">Source: DE weeklyRivensPC.json — averages across all rolls, not your grade.</p>";
    } else {
      html += '<p class="tool-meta" style="margin-top:12px">No weekly trade row for this weapon name (or feed unavailable).</p>';
    }

    html +=
      '<div class="tool-actions" style="margin-top:14px">' +
      '<a class="btn-secondary" href="/rivens.html">Disposition table</a>' +
      '<a class="btn-secondary" href="/market.html?q=' +
      encodeURIComponent(selected.name + " riven") +
      '">Market</a>' +
      "</div></section>";

    if (resultEl) {
      resultEl.innerHTML = html;
      resultEl.hidden = false;
      resultEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    setStatus(true, "Graded " + selected.name + " · " + overall.letter);
  }

  function loadWeapons() {
    return fetch(API + "/weapons?language=en", { cache: "no-store", headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (list) {
        weapons = (list || []).filter(function (w) {
          return w && w.name && (w.disposition != null || w.omegaAttenuation != null);
        });
      });
  }

  function loadWeekly() {
    return fetch(WEEKLY_URL, { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.text();
      })
      .then(function (t) {
        weekly = parseWeekly(t) || [];
      })
      .catch(function () {
        weekly = [];
      });
  }

  if (weaponEl) {
    weaponEl.addEventListener("input", function () {
      clearTimeout(suggestTimer);
      suggestTimer = setTimeout(function () {
        renderSuggest(searchWeapons(weaponEl.value, 10));
      }, 100);
    });
    weaponEl.addEventListener("keydown", function (e) {
      if (e.key === "Escape") hideSuggest();
      if (e.key === "Enter") {
        e.preventDefault();
        var list = searchWeapons(weaponEl.value, 1);
        if (list.length) selectWeapon(list[0]);
      }
    });
  }

  if (suggestEl) {
    suggestEl.addEventListener("click", function (e) {
      var li = e.target.closest("[data-name]");
      if (!li) return;
      var name = li.getAttribute("data-name");
      var hit = weapons.filter(function (w) { return w.name === name; })[0];
      if (hit) selectWeapon(hit);
    });
  }

  document.addEventListener("click", function (e) {
    if (!suggestEl || suggestEl.hidden) return;
    if (e.target === weaponEl || suggestEl.contains(e.target)) return;
    hideSuggest();
  });

  if (posCountEl) posCountEl.addEventListener("change", rebuildStatRows);
  if (hasNegEl) hasNegEl.addEventListener("change", rebuildStatRows);

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      grade();
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      selected = null;
      if (weaponEl) weaponEl.value = "";
      if (metaEl) metaEl.textContent = "Search a weapon to load disposition.";
      if (resultEl) {
        resultEl.hidden = true;
        resultEl.innerHTML = "";
      }
      rebuildStatRows();
      setStatus(true, weapons.length + " weapons ready");
    });
  }

  rebuildStatRows();

  // ——— Screenshot OCR (Tesseract.js, in-browser) ———
  var dropEl = document.getElementById("rg-drop");
  var fileEl = document.getElementById("rg-file");
  var previewEl = document.getElementById("rg-preview");
  var ocrBtn = document.getElementById("rg-ocr-btn");
  var ocrClearBtn = document.getElementById("rg-ocr-clear");
  var ocrRawEl = document.getElementById("rg-ocr-raw");
  var ocrImage = null;
  var ocrObjectUrl = null;
  var tesseractWorker = null;

  var STAT_ALIASES = [
    { id: "cc", re: /critical\s*chance|crit(?:ical)?\s*chance|crit\s*chance/i },
    { id: "cd", re: /critical\s*damage|crit(?:ical)?\s*damage|crit\s*damage/i },
    { id: "ms", re: /multi[\s-]*shot/i },
    { id: "sc", re: /status\s*chance/i },
    { id: "sd", re: /status\s*duration/i },
    { id: "fr", re: /fire\s*rate|attack\s*speed/i },
    { id: "d_corpus", re: /damage\s*(?:vs\.?|to)\s*corpus|(?:vs\.?|to)\s*corpus/i },
    { id: "d_grineer", re: /damage\s*(?:vs\.?|to)\s*grineer|(?:vs\.?|to)\s*grineer/i },
    { id: "d_infested", re: /damage\s*(?:vs\.?|to)\s*infested|(?:vs\.?|to)\s*infested/i },
    { id: "damage", re: /\b(?:base\s+|melee\s+)?damage\b/i },
    { id: "ammo", re: /ammo\s*maximum|maximum\s*ammo/i },
    { id: "mag", re: /magazine\s*capacity|magazine/i },
    { id: "reload", re: /reload\s*speed|reload/i },
    { id: "projectile", re: /projectile\s*speed|flight\s*speed/i },
    { id: "punch", re: /punch\s*through/i },
    { id: "recoil", re: /weapon\s*recoil|\brecoil\b/i },
    { id: "zoom", re: /\bzoom\b/i },
    { id: "cold", re: /cold\s*damage|\bcold\b/i },
    { id: "heat", re: /heat\s*damage|\bheat\b/i },
    { id: "elec", re: /electric(?:ity)?\s*damage|\belectric/i },
    { id: "toxin", re: /toxin\s*damage|\btoxin\b/i },
    { id: "impact", re: /impact\s*damage|\bimpact\b/i },
    { id: "puncture", re: /puncture\s*damage|\bpuncture\b/i },
    { id: "slash", re: /slash\s*damage|\bslash\b/i },
    { id: "range", re: /\brange\b/i },
    { id: "combo_dur", re: /combo\s*duration/i },
    { id: "initial_combo", re: /initial\s*combo/i },
    { id: "finisher", re: /finisher\s*damage/i },
    { id: "slide_cc", re: /slide\s*(?:attack\s*)?crit/i },
    { id: "heavy_eff", re: /heavy\s*attack\s*efficiency/i },
    { id: "combo_chance", re: /combo\s*count\s*chance|chance\s*to\s*gain\s*combo/i },
  ];

  function loadTesseractScript() {
    if (window.Tesseract && window.Tesseract.createWorker) {
      return Promise.resolve(window.Tesseract);
    }
    return new Promise(function (resolve, reject) {
      var existing = document.querySelector('script[data-rg-tesseract]');
      if (existing) {
        existing.addEventListener("load", function () {
          resolve(window.Tesseract);
        });
        existing.addEventListener("error", reject);
        return;
      }
      var s = document.createElement("script");
      s.src = "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js";
      s.async = true;
      s.setAttribute("data-rg-tesseract", "1");
      s.onload = function () {
        resolve(window.Tesseract);
      };
      s.onerror = function () {
        reject(new Error("Could not load OCR library"));
      };
      document.head.appendChild(s);
    });
  }

  function getOcrWorker(logger) {
    return loadTesseractScript().then(function (T) {
      if (tesseractWorker) return tesseractWorker;
      return T.createWorker("eng", 1, {
        logger: logger || function () {},
        workerPath: "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/worker.min.js",
        corePath: "https://cdn.jsdelivr.net/npm/tesseract.js-core@v5.0.0",
      }).then(function (w) {
        return w
          .setParameters({
            tessedit_pageseg_mode: "6",
            preserve_interword_spaces: "1",
          })
          .then(function () {
            tesseractWorker = w;
            return w;
          });
      });
    });
  }

  function preprocessImage(fileOrBlob) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(fileOrBlob);
      var img = new Image();
      img.onload = function () {
        try {
          // Upscale small screenshots; avoid crushing UI glyphs with hard B/W thresholds
          var scale = Math.min(3, Math.max(2, 1600 / Math.max(img.width, 1)));
          var w = Math.round(img.width * scale);
          var h = Math.round(img.height * scale);
          var canvas = document.createElement("canvas");
          canvas.width = w;
          canvas.height = h;
          var ctx = canvas.getContext("2d");
          ctx.imageSmoothingEnabled = true;
          ctx.drawImage(img, 0, 0, w, h);
          var data = ctx.getImageData(0, 0, w, h);
          var px = data.data;
          for (var i = 0; i < px.length; i += 4) {
            var g = 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
            // Gentle contrast only — hard thresholds were wiping Warframe UI text
            g = (g - 128) * 1.35 + 140;
            if (g < 0) g = 0;
            if (g > 255) g = 255;
            px[i] = px[i + 1] = px[i + 2] = g;
          }
          ctx.putImageData(data, 0, 0);
          URL.revokeObjectURL(url);
          canvas.toBlob(
            function (blob) {
              if (!blob) reject(new Error("Image preprocess failed"));
              else resolve(blob);
            },
            "image/png"
          );
        } catch (err) {
          URL.revokeObjectURL(url);
          reject(err);
        }
      };
      img.onerror = function () {
        URL.revokeObjectURL(url);
        reject(new Error("Could not read image"));
      };
      img.src = url;
    });
  }

  function matchStatLabel(line) {
    var s = String(line || "");
    for (var i = 0; i < STAT_ALIASES.length; i++) {
      if (STAT_ALIASES[i].re.test(s)) {
        if (STAT_ALIASES[i].id === "damage" && /vs\.?|to\s+(corpus|grineer|infested)/i.test(s)) continue;
        return STAT_ALIASES[i].id;
      }
    }
    return null;
  }

  function fixOcrDigits(raw) {
    return String(raw || "")
      .replace(/,/g, ".")
      .replace(/[Oo]/g, "0")
      .replace(/[Il|]/g, "1")
      .replace(/[Ss]/g, "5")
      .replace(/[^\d.\-]/g, "")
      .replace(/\.{2,}/g, ".");
  }

  function parseNumberToken(raw) {
    if (!raw) return null;
    var s = fixOcrDigits(raw);
    // "180 2" → "180.2" when OCR splits the decimal
    if (/^\d+\s+\d{1,2}$/.test(String(raw).trim())) {
      s = String(raw).trim().replace(/\s+/, ".");
    }
    var n = Number(s);
    return isFinite(n) ? n : null;
  }

  function normalizePolarity(ch) {
    if (!ch) return "+";
    ch = String(ch).charAt(0);
    if (ch === "+" || ch === "t" || ch === "T") return "+"; // OCR often reads + as t
    if (ch === "-" || ch === "−" || ch === "–" || ch === "—") return "-";
    return "+";
  }

  function addSlot(slots, seen, id, num, polarity) {
    if (!id || seen[id] || num == null || !isFinite(num)) return false;
    seen[id] = true;
    var pol = normalizePolarity(polarity);
    slots.push({
      id: id,
      value: pol === "-" ? -Math.abs(num) : Math.abs(num),
      polarity: pol,
    });
    return true;
  }

  function parseOcrText(text) {
    var raw = String(text || "")
      // Common OCR junk
      .replace(/\u00a0/g, " ")
      .replace(/[|]/g, "I");

    var lines = raw
      .split(/\r?\n/)
      .map(function (l) {
        return l.replace(/\s+/g, " ").trim();
      })
      .filter(Boolean);

    var slots = [];
    var seen = {};

    function tryLine(line) {
      if (!line) return;
      // +180.2% Critical Chance   (space after % optional)
      var a = line.match(/^([+\-−–tT])\s*(\d+[.,]?\d*|\d+\s+\d)\s*%?\s*x?\s*(.+)$/i);
      if (a) {
        var idA = matchStatLabel(a[3]) || matchStatLabel(line);
        if (idA) addSlot(slots, seen, idA, parseNumberToken(a[2]), a[1]);
        return;
      }
      // Critical Chance +180.2%
      var b = line.match(/^(.+?)\s+([+\-−–tT])\s*(\d+[.,]?\d*|\d+\s+\d)\s*%?\s*x?\s*$/i);
      if (b) {
        var idB = matchStatLabel(b[1]);
        if (idB) addSlot(slots, seen, idB, parseNumberToken(b[3]), b[2]);
        return;
      }
      // Critical Chance 180.2%  (no sign → positive)
      var c = line.match(/^(.+?)\s+([+\-−–tT])?\s*(\d+[.,]\d+|\d{2,3})\s*%\s*$/i);
      if (c) {
        var idC = matchStatLabel(c[1]);
        if (idC) addSlot(slots, seen, idC, parseNumberToken(c[3]), c[2] || "+");
        return;
      }
      // +2.7m Punch Through / +8.1s Combo Duration
      var d = line.match(/^([+\-−–tT])\s*(\d+[.,]?\d*)\s*[ms]\s+(.+)$/i);
      if (d) {
        var idD = matchStatLabel(d[3]);
        if (idD) addSlot(slots, seen, idD, parseNumberToken(d[2]), d[1]);
      }
    }

    // Pass 1: each line alone
    lines.forEach(tryLine);

    // Pass 2: pair adjacent lines when OCR splits value / label
    //   "+180.2%"  then  "Critical Chance"
    //   "Critical Chance"  then  "+180.2%"
    for (var i = 0; i < lines.length - 1; i++) {
      var cur = lines[i];
      var next = lines[i + 1];
      var numLine = cur.match(/^([+\-−–tT])?\s*(\d+[.,]?\d*|\d+\s+\d)\s*%?\s*x?\s*$/i);
      var numNext = next.match(/^([+\-−–tT])?\s*(\d+[.,]?\d*|\d+\s+\d)\s*%?\s*x?\s*$/i);
      var labelCur = matchStatLabel(cur);
      var labelNext = matchStatLabel(next);
      if (numLine && labelNext && !/\d/.test(next.replace(/%/g, ""))) {
        addSlot(slots, seen, labelNext, parseNumberToken(numLine[2]), numLine[1] || "+");
      } else if (labelCur && numNext && !/\d/.test(cur.replace(/%/g, ""))) {
        addSlot(slots, seen, labelCur, parseNumberToken(numNext[2]), numNext[1] || "+");
      }
    }

    // Pass 3: flatten text — catch stats OCR mashed onto one line or wrapped oddly
    var flat = lines.join("  ");
    var labelAlts = STAT_ALIASES.map(function (a) {
      return a.re.source;
    }).join("|");
    var globalRe = new RegExp(
      "([+\\-−–tT])\\s*(\\d+[.,]?\\d*|\\d+\\s+\\d)\\s*%?\\s*x?\\s*(" + labelAlts + ")",
      "gi"
    );
    var gm;
    while ((gm = globalRe.exec(flat)) !== null) {
      var gid = matchStatLabel(gm[3]);
      addSlot(slots, seen, gid, parseNumberToken(gm[2]), gm[1]);
    }
    // label then number on flat text
    var globalRe2 = new RegExp(
      "(" + labelAlts + ")\\s*([+\\-−–tT])\\s*(\\d+[.,]?\\d*|\\d+\\s+\\d)\\s*%?",
      "gi"
    );
    while ((gm = globalRe2.exec(flat)) !== null) {
      addSlot(slots, seen, matchStatLabel(gm[1]), parseNumberToken(gm[3]), gm[2]);
    }

    var rank = 8;
    var full = lines.join("\n");
    var rm = full.match(/\brank\s*[:=]?\s*(\d)\b/i) || full.match(/\b(\d)\s*\/\s*8\b/);
    if (rm) rank = Math.min(8, Math.max(0, Number(rm[1])));

    var weaponHit = null;
    var bestScore = 0;
    var blob = lines.join(" ").toLowerCase().replace(/[^a-z0-9\s']/g, " ");
    for (var wi = 0; wi < weapons.length; wi++) {
      var name = String(weapons[wi].name || "");
      var nl = name.toLowerCase();
      if (nl.length < 3) continue;
      if (blob.indexOf(nl) >= 0) {
        var score = nl.length + (blob.indexOf(nl) < 80 ? 15 : 0);
        if (score > bestScore) {
          bestScore = score;
          weaponHit = weapons[wi];
        }
      }
    }
    if (!weaponHit) {
      for (var li = 0; li < Math.min(8, lines.length); li++) {
        var cleaned = lines[li].replace(/riven/gi, "").replace(/mod/gi, "").trim();
        var hits = searchWeapons(cleaned, 1);
        if (hits.length && cleaned.toLowerCase().indexOf(String(hits[0].name).toLowerCase().slice(0, 4)) >= 0) {
          weaponHit = hits[0];
          break;
        }
      }
    }

    return { weapon: weaponHit, slots: slots, rank: rank, lines: lines };
  }

  function applyParsed(parsed) {
    if (!parsed) return;
    if (rankEl && parsed.rank != null) rankEl.value = String(parsed.rank);
    if (parsed.weapon) selectWeapon(parsed.weapon);
    else if (weaponEl && !selected) {
      // leave weapon empty for user
    }
    if (parsed.slots && parsed.slots.length) fillSlots(parsed.slots);
  }

  function setOcrImage(file) {
    if (!file || !/^image\//.test(file.type || "")) {
      setStatus(false, "Please drop an image file");
      return;
    }
    if (ocrObjectUrl) URL.revokeObjectURL(ocrObjectUrl);
    ocrImage = file;
    ocrObjectUrl = URL.createObjectURL(file);
    if (previewEl) {
      previewEl.src = ocrObjectUrl;
      previewEl.hidden = false;
    }
    if (dropEl) dropEl.classList.add("has-image");
    if (ocrBtn) ocrBtn.disabled = false;
    if (ocrClearBtn) ocrClearBtn.disabled = false;
    if (ocrRawEl) {
      ocrRawEl.hidden = true;
      ocrRawEl.textContent = "";
    }
    setStatus(true, "Image ready — click Read screenshot");
  }

  function clearOcrImage() {
    ocrImage = null;
    if (ocrObjectUrl) URL.revokeObjectURL(ocrObjectUrl);
    ocrObjectUrl = null;
    if (previewEl) {
      previewEl.removeAttribute("src");
      previewEl.hidden = true;
    }
    if (dropEl) dropEl.classList.remove("has-image");
    if (ocrBtn) ocrBtn.disabled = true;
    if (ocrClearBtn) ocrClearBtn.disabled = true;
    if (ocrRawEl) {
      ocrRawEl.hidden = true;
      ocrRawEl.textContent = "";
    }
    if (fileEl) fileEl.value = "";
  }

  function mergeParsed(a, b) {
    var out = {
      weapon: (a && a.weapon) || (b && b.weapon) || null,
      rank: (a && a.rank) || (b && b.rank) || 8,
      slots: [],
      lines: [].concat((a && a.lines) || [], (b && b.lines) || []),
    };
    var seen = {};
    function eat(list) {
      (list || []).forEach(function (s) {
        if (!s || !s.id || seen[s.id]) return;
        seen[s.id] = true;
        out.slots.push(s);
      });
    }
    // Prefer the pass that found more stats
    if ((a && a.slots && a.slots.length) >= (b && b.slots && b.slots.length)) {
      eat(a && a.slots);
      eat(b && b.slots);
    } else {
      eat(b && b.slots);
      eat(a && a.slots);
    }
    return out;
  }

  function runOcr() {
    if (!ocrImage) {
      setStatus(false, "Add a screenshot first");
      return;
    }
    if (!weapons.length) {
      setStatus(false, "Weapons still loading…");
      return;
    }
    setStatus(true, "Preparing image…");
    if (ocrBtn) ocrBtn.disabled = true;
    getOcrWorker(function (m) {
      if (m && m.status === "recognizing text" && m.progress != null) {
        setStatus(true, "Reading screenshot… " + Math.round(m.progress * 100) + "%");
      }
    })
      .then(function (worker) {
        setStatus(true, "Reading screenshot…");
        // Run OCR on both original and contrast-boosted copies, then merge stats
        return preprocessImage(ocrImage).then(function (pre) {
          return Promise.all([worker.recognize(ocrImage), worker.recognize(pre)]);
        });
      })
      .then(function (rets) {
        var textA = (rets[0] && rets[0].data && rets[0].data.text) || "";
        var textB = (rets[1] && rets[1].data && rets[1].data.text) || "";
        var combined = textA + "\n---\n" + textB;
        if (ocrRawEl) {
          ocrRawEl.textContent = combined || "(no text detected)";
          ocrRawEl.hidden = false;
        }
        var parsed = mergeParsed(parseOcrText(textA), parseOcrText(textB));
        applyParsed(parsed);
        var msg =
          "OCR filled " +
          (parsed.slots.length || 0) +
          " stat" +
          (parsed.slots.length === 1 ? "" : "s") +
          (parsed.weapon ? " · " + parsed.weapon.name : " · set weapon manually") +
          " — review, then Grade";
        setStatus(parsed.slots.length > 0, msg);
        if (ocrBtn) ocrBtn.disabled = false;
      })
      .catch(function (err) {
        setStatus(false, (err && err.message) || "OCR failed");
        if (ocrBtn) ocrBtn.disabled = false;
      });
  }

  if (dropEl) {
    dropEl.addEventListener("click", function () {
      if (fileEl) fileEl.click();
    });
    dropEl.addEventListener("dragover", function (e) {
      e.preventDefault();
      dropEl.classList.add("dragover");
    });
    dropEl.addEventListener("dragleave", function () {
      dropEl.classList.remove("dragover");
    });
    dropEl.addEventListener("drop", function (e) {
      e.preventDefault();
      dropEl.classList.remove("dragover");
      var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) setOcrImage(f);
    });
  }

  if (fileEl) {
    fileEl.addEventListener("change", function () {
      if (fileEl.files && fileEl.files[0]) setOcrImage(fileEl.files[0]);
    });
  }

  if (ocrBtn) ocrBtn.addEventListener("click", runOcr);
  if (ocrClearBtn) ocrClearBtn.addEventListener("click", clearOcrImage);

  document.addEventListener("paste", function (e) {
    var items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    for (var i = 0; i < items.length; i++) {
      if (items[i].type && items[i].type.indexOf("image") === 0) {
        var f = items[i].getAsFile();
        if (f) {
          e.preventDefault();
          setOcrImage(f);
        }
        break;
      }
    }
  });

  Promise.all([loadWeapons(), loadWeekly()]).then(function () {
    setStatus(true, weapons.length + " weapons" + (weekly.length ? " · weekly trades loaded" : " · weekly trades offline"));
    var q = new URLSearchParams(location.search).get("weapon");
    if (q) {
      if (weaponEl) weaponEl.value = q;
      var hits = searchWeapons(q, 1);
      if (hits.length) selectWeapon(hits[0]);
    }
  }).catch(function () {
    setStatus(false, "Could not load weapon list");
  });
})();
