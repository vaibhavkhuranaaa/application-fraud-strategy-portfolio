/* Application fraud screening exhibit.
   Static: the whole policy space is precomputed, so every control is a lookup.
   Charts are hand-authored SVG so nothing arrives with a chart library's defaults. */

(function () {
  "use strict";

  var DATA = null;
  var STATE = {
    model: 0, capacityIndex: 8, rules: {}, exposure: 12500, review: 17, friction: 150,
    queueOutcome: "all", queueRule: "all", queueLimit: 10, selectedCase: null
  };
  var COL = {};

  var $ = function (id) { return document.getElementById(id); };
  var SVGNS = "http://www.w3.org/2000/svg";

  /* ---------------- formatting ---------------- */

  function num(value, digits) {
    if (value === null || value === undefined || !isFinite(value)) return "n/a";
    return value.toLocaleString("en-US", { minimumFractionDigits: digits || 0, maximumFractionDigits: digits || 0 });
  }
  function pct(value, digits) {
    if (value === null || value === undefined || !isFinite(value)) return "n/a";
    return (value * 100).toFixed(digits === undefined ? 1 : digits) + "%";
  }
  function money(value) {
    if (!isFinite(value)) return "n/a";
    var sign = value < 0 ? "−" : "";
    var abs = Math.abs(value);
    if (abs >= 1e6) return sign + "$" + (abs / 1e6).toFixed(2) + "M";
    if (abs >= 1e3) return sign + "$" + Math.round(abs / 1e3) + "k";
    return sign + "$" + Math.round(abs);
  }
  function signed(value) {
    if (!value) return "No change";
    return (value > 0 ? "+" : "−") + num(Math.abs(value));
  }
  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    for (var key in attrs) { if (attrs[key] !== null) node.setAttribute(key, attrs[key]); }
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function svg(tag, attrs) {
    var node = document.createElementNS(SVGNS, tag);
    for (var key in attrs) { node.setAttribute(key, attrs[key]); }
    return node;
  }
  // Read once. getComputedStyle forces style resolution, and the chart loops used to
  // call it per gridline, per bar, per label.
  var TOKENS = {};
  function css(name) {
    if (TOKENS[name] === undefined) {
      TOKENS[name] = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }
    return TOKENS[name];
  }

  /* ---------------- policy index ----------------
     The payload ships counts only; every rate is derived here once at load, and the
     grid is indexed so a control change is a lookup rather than a scan of 1,152 rows. */

  var INDEX = null;

  function key(model, capacityIndex, mask) { return model * 100000 + capacityIndex * 100 + mask; }

  function buildIndex() {
    INDEX = new Map();
    var meta = DATA.meta;
    var caps = DATA.policies.capacities;
    // The only place that reads raw payload columns. Everything downstream uses the
    // derived objects built here.
    DATA.policies.rows.forEach(function (row) {
      var worked = row[COL.queue_size];
      var referrals = row[COL.referrals];
      var goodReviewed = row[COL.good_reviewed];
      var caught = row[COL.fraud_caught];
      var actioned = worked + referrals;
      INDEX.set(key(row[COL.model], row[COL.capacity], row[COL.rules]), {
        model: row[COL.model],
        capacity: caps[row[COL.capacity]],
        caught: caught,
        goodReviewed: goodReviewed,
        worked: worked,
        referrals: referrals,
        ceiling: row[COL.capacity_count],
        actioned: actioned,
        captureRate: caught / meta.fraud,
        insultRate: goodReviewed / meta.good,
        hitRate: actioned > 0 ? caught / actioned : 0,
        reviewRate: actioned / meta.applications
      });
    });
  }

  function ruleMask() {
    var rules = DATA.policies.rules;
    var mask = 0;
    for (var i = 0; i < rules.length; i += 1) {
      if (STATE.rules[rules[i].key]) mask |= 1 << (rules.length - 1 - i);
    }
    return mask;
  }

  function currentPolicy() {
    return INDEX.get(key(STATE.model, STATE.capacityIndex, ruleMask())) || null;
  }

  function policyAt(modelIndex, capacityIndex, mask) {
    return INDEX.get(key(modelIndex, capacityIndex, mask)) || null;
  }

  function incumbentIndex() {
    var models = DATA.policies.models;
    for (var i = 0; i < models.length; i += 1) { if (models[i].key === "incumbent_proxy") return i; }
    return models.length - 1;
  }

  // Value protected minus what the screening costs to run. Counts are observed;
  // the three unit values are the analyst's, so this whole figure is an assumption.
  function economics(policy) {
    // Two things sit between "fraud caught" and "money saved" and neither is 1.0: a review
    // does not stop every fraud it touches, and stopping one does not recover the whole
    // balance. Neither has a source that meets this project's citation bar, so the value
    // is shown as a range across their stated bounds rather than as a single number that
    // would quietly assume both are perfect.
    var bounds = (DATA.assumptions && DATA.assumptions.recovery_bounds) || { low: 1, high: 1 };
    var full = policy.caught * STATE.exposure;
    var operating = policy.worked * STATE.review + policy.goodReviewed * STATE.friction;
    return {
      protectedLow: full * bounds.low,
      protectedHigh: full * bounds.high,
      operating: operating,
      netLow: full * bounds.low - operating,
      netHigh: full * bounds.high - operating
    };
  }

  function moneyRange(low, high) {
    return low === high ? money(low) : money(low) + " to " + money(high);
  }

  /* ---------------- measures ---------------- */

  function measure(label, value, sub, options) {
    var item = el("div", { class: "measure" + (options && options.over ? " is-over" : "") });
    var term = el("dt");
    if (options && options.assumption) {
      term.appendChild(el("span", { class: "mark", "aria-hidden": "true" }, "◇"));
      term.appendChild(document.createTextNode(" " + label + " (assumption)"));
    } else {
      term.textContent = label;
    }
    var detail = el("dd");
    detail.appendChild(document.createTextNode(value));
    if (sub) detail.appendChild(el("span", { class: "sub" }, sub));
    item.appendChild(term);
    item.appendChild(detail);
    return item;
  }

  function renderMeasures(policy) {
    var host = $("measures");
    host.innerHTML = "";
    if (!policy) { host.appendChild(el("p", { class: "note" }, "No precomputed result for this combination.")); return; }

    var fraudTotal = DATA.meta.fraud;
    var missed = fraudTotal - policy.caught;
    var value = economics(policy);
    var alertRatio = policy.caught > 0 ? policy.actioned / policy.caught : NaN;
    var over = policy.referrals > 0;
    var fragment = document.createDocumentFragment();

    fragment.appendChild(measure("Fraud capture rate", pct(policy.captureRate),
      num(policy.caught) + " of " + num(fraudTotal) + " attempts routed to review"));

    fragment.appendChild(measure("Leakage", num(missed),
      pct(missed / fraudTotal) + " of attempts reached approval unchecked"));

    fragment.appendChild(measure("Investigator hit rate", num(policy.hitRate * 100, 1) + " per 100",
      "cases worked that turn out to be fraud"));

    fragment.appendChild(measure("Alert-to-fraud ratio", isFinite(alertRatio) ? num(alertRatio, 1) + " : 1" : "n/a",
      "cases worked per fraud found"));

    fragment.appendChild(measure("Capacity utilisation", pct(policy.actioned / policy.ceiling, 0),
      num(policy.actioned) + " cases against a ceiling of " + num(policy.ceiling) +
      (over ? ". " + num(policy.referrals) + " beyond capacity." : ". Fits the team."), { over: over }));

    fragment.appendChild(measure("Insult rate", pct(policy.insultRate, 2),
      num(policy.goodReviewed) + " good customers held up"));

    fragment.appendChild(measure("Value protected", moneyRange(value.protectedLow, value.protectedHigh),
      num(policy.caught) + " attempts caught, after allowing for reviews that do not stop the fraud they find and balances that would part recover",
      { assumption: true }));

    fragment.appendChild(measure("Net position", moneyRange(value.netLow, value.netHigh),
      "after " + money(value.operating) + " of review and friction cost", { assumption: true }));

    host.appendChild(fragment);
  }

  function impactItem(label, value, note, tone) {
    var item = el("div", { class: tone || "" });
    item.appendChild(el("dt", null, label));
    var detail = el("dd", null, value);
    detail.appendChild(el("span", null, note));
    item.appendChild(detail);
    return item;
  }

  function renderImpact(policy) {
    var host = $("scenario-impact-values");
    host.innerHTML = "";
    if (!policy) return;
    var baseline = policyAt(incumbentIndex(), STATE.capacityIndex, 0);
    if (!baseline) return;

    var caught = policy.caught - baseline.caught;
    var good = policy.goodReviewed - baseline.goodReviewed;
    var demand = policy.actioned - baseline.actioned;
    var value = economics(policy);
    var baselineValue = economics(baseline);
    var netLow = value.netLow - baselineValue.netLow;
    var netHigh = value.netHigh - baselineValue.netHigh;
    var netTone = netLow >= 0 ? "is-better" : netHigh < 0 ? "is-worse" : "";

    host.appendChild(impactItem("Fraud attempts caught", signed(caught),
      caught > 0 ? "More caught" : caught < 0 ? "Fewer caught" : "Same observed count",
      caught > 0 ? "is-better" : caught < 0 ? "is-worse" : ""));
    host.appendChild(impactItem("Good customers held up", signed(good),
      good < 0 ? "Fewer held up" : good > 0 ? "More held up" : "Same observed count",
      good < 0 ? "is-better" : good > 0 ? "is-worse" : ""));
    host.appendChild(impactItem("Review demand", signed(demand),
      policy.referrals ? num(policy.referrals) + " beyond capacity" : "Fits the selected team",
      demand < 0 ? "is-better" : demand > 0 ? "is-worse" : ""));
    host.appendChild(impactItem("Net change ◇ (assumption)",
      moneyRange(Math.min(netLow, netHigh), Math.max(netLow, netHigh)),
      "Assumption-led, not observed money", netTone));
    renderScenarioUncertainty();
  }

  function renderScenarioUncertainty() {
    var host = $("scenario-uncertainty");
    if (!host || !DATA.governance || !DATA.governance.uncertainty) return;
    var evidence = DATA.governance.uncertainty;
    var model = DATA.policies.models[STATE.model];
    var supported = model && model.key === evidence.approach &&
      DATA.policies.capacities[STATE.capacityIndex] === evidence.capacity && ruleMask() === 0;
    if (!supported) {
      host.textContent = "Paired uncertainty is precomputed only for the proposed approach at five-percent capacity with concentration rules off.";
      return;
    }
    var caught = evidence.fraud_caught_delta.paired_interval_95;
    var good = evidence.good_reviewed_delta.paired_interval_95;
    host.textContent = "Paired 95% interval: +" + num(caught[0]) + " to +" + num(caught[1]) +
      " labelled fraud attempts caught, and " + num(Math.abs(good[1])) + " to " +
      num(Math.abs(good[0])) + " fewer records labelled as good reviewed. The catch difference was positive in " +
      evidence.positive_temporal_folds + " of " + evidence.temporal_folds.length +
      " time-ordered folds. Decision evidence only; the refusal remains.";
  }

  /* ---------------- exhibit 1: trend ---------------- */

  function renderTrend() {
    var host = $("chart-trend");
    host.innerHTML = "";
    var rows = DATA.trend;
    var W = 980, H = 300, L = 56, R = 56, T = 16, B = 44;
    var plotW = W - L - R, plotH = H - T - B;
    var maxApps = Math.max.apply(null, rows.map(function (r) { return r.applications; }));
    var maxRate = Math.max.apply(null, rows.map(function (r) { return r.fraud_rate; }));
    var rateTop = Math.ceil(maxRate * 1000) / 1000 + 0.001;

    var node = svg("svg", { viewBox: "0 0 " + W + " " + H, width: "100%", height: H, role: "img",
      "aria-label": findingTrendText() });

    // horizontal guides
    for (var g = 0; g <= 4; g += 1) {
      var y = T + plotH - (plotH * g) / 4;
      node.appendChild(svg("line", { x1: L, x2: L + plotW, y1: y, y2: y,
        stroke: g === 0 ? css("--rule-strong") : css("--rule"), "stroke-width": 1 }));
      var label = svg("text", { x: L - 10, y: y + 4, "text-anchor": "end", "font-size": 11, fill: css("--ink-muted") });
      label.textContent = num((maxApps * g) / 4 / 1000, 0) + "k";
      node.appendChild(label);
      var right = svg("text", { x: L + plotW + 10, y: y + 4, "font-size": 11, fill: css("--accent") });
      right.textContent = ((rateTop * g) / 4 * 100).toFixed(2) + "%";
      node.appendChild(right);
    }

    var slot = plotW / rows.length;
    var barW = Math.min(46, slot * 0.52);
    var points = [];
    rows.forEach(function (r, i) {
      var cx = L + slot * i + slot / 2;
      var h = (r.applications / maxApps) * plotH;
      node.appendChild(svg("rect", { x: cx - barW / 2, y: T + plotH - h, width: barW, height: h, fill: css("--rule") }));
      points.push([cx, T + plotH - (r.fraud_rate / rateTop) * plotH]);
      var tick = svg("text", { x: cx, y: H - 24, "text-anchor": "middle", "font-size": 11, fill: css("--ink-muted") });
      tick.textContent = "M" + r.month;
      node.appendChild(tick);
    });

    node.appendChild(svg("polyline", { points: points.map(function (p) { return p.join(","); }).join(" "),
      fill: "none", stroke: css("--accent"), "stroke-width": 2.5, "stroke-linejoin": "round" }));
    points.forEach(function (p, i) {
      node.appendChild(svg("circle", { cx: p[0], cy: p[1], r: i === points.length - 1 ? 5 : 3.5,
        fill: i === points.length - 1 ? css("--accent") : css("--paper"),
        stroke: css("--accent"), "stroke-width": 2 }));
    });

    var axisLeft = svg("text", { x: 14, y: T + plotH / 2, "font-size": 11, fill: css("--ink-muted"),
      "text-anchor": "middle", transform: "rotate(-90 14 " + (T + plotH / 2) + ")" });
    axisLeft.textContent = "Applications assessed";
    node.appendChild(axisLeft);
    var axisRight = svg("text", { x: W - 12, y: T + plotH / 2, "font-size": 11, fill: css("--accent"),
      "text-anchor": "middle", transform: "rotate(90 " + (W - 12) + " " + (T + plotH / 2) + ")" });
    axisRight.textContent = "Fraud attempt rate";
    node.appendChild(axisRight);

    host.appendChild(node);
    $("finding-trend").textContent = findingTrendText();
  }

  function findingTrendText() {
    var rows = DATA.trend;
    var first = rows[0], last = rows[rows.length - 1];
    var lowest = rows.reduce(function (a, b) { return b.fraud_rate < a.fraud_rate ? b : a; });
    var change = ((last.fraud_rate - lowest.fraud_rate) / lowest.fraud_rate) * 100;
    return "Fraud pressure is rising while volume falls. The attempt rate climbed from " +
      pct(lowest.fraud_rate, 2) + " in month " + lowest.month + " to " + pct(last.fraud_rate, 2) +
      " in month " + last.month + ", a " + Math.round(change) + "% increase, while monthly applications fell from " +
      num(first.applications) + " to " + num(last.applications) + ". A stable screening approach faces a harder mix each month.";
  }

  /* ---------------- exhibit 2: capacity curve ---------------- */

  function renderCapacity() {
    var host = $("chart-capacity");
    host.innerHTML = "";
    var mask = ruleMask();
    var caps = DATA.policies.capacities;
    var inc = incumbentIndex();

    var selected = caps.map(function (_, i) { return policyAt(STATE.model, i, mask); }).filter(Boolean);
    var baseline = caps.map(function (_, i) { return policyAt(inc, i, 0); }).filter(Boolean);

    var W = 980, H = 320, L = 56, R = 24, T = 16, B = 48;
    var plotW = W - L - R, plotH = H - T - B;
    var maxX = Math.max.apply(null, selected.concat(baseline).map(function (r) { return r.reviewRate; }));
    maxX = Math.min(Math.max(maxX, 0.05), 0.6);

    var node = svg("svg", { viewBox: "0 0 " + W + " " + H, width: "100%", height: H, role: "img",
      "aria-label": findingCapacityText() });

    for (var g = 0; g <= 4; g += 1) {
      var y = T + plotH - (plotH * g) / 4;
      node.appendChild(svg("line", { x1: L, x2: L + plotW, y1: y, y2: y,
        stroke: g === 0 ? css("--rule-strong") : css("--rule") }));
      var lab = svg("text", { x: L - 10, y: y + 4, "text-anchor": "end", "font-size": 11, fill: css("--ink-muted") });
      lab.textContent = (g * 25) + "%";
      node.appendChild(lab);
    }
    for (var t = 0; t <= 4; t += 1) {
      var xv = (maxX * t) / 4;
      var x = L + (xv / maxX) * plotW;
      var tick = svg("text", { x: x, y: H - 26, "text-anchor": "middle", "font-size": 11, fill: css("--ink-muted") });
      tick.textContent = pct(xv, 0);
      node.appendChild(tick);
    }

    function path(rows, color, dash) {
      var pts = rows.map(function (r) {
        return [L + Math.min(r.reviewRate / maxX, 1) * plotW, T + plotH - r.captureRate * plotH];
      });
      node.appendChild(svg("polyline", { points: pts.map(function (p) { return p.join(","); }).join(" "),
        fill: "none", stroke: color, "stroke-width": 2.5, "stroke-dasharray": dash || "none", "stroke-linejoin": "round" }));
      return pts;
    }

    path(baseline, css("--ink-muted"), "5 4");
    path(selected, css("--accent"));

    var current = currentPolicy();
    if (current) {
      var cx = L + Math.min(current.reviewRate / maxX, 1) * plotW;
      var cy = T + plotH - current.captureRate * plotH;
      node.appendChild(svg("line", { x1: cx, x2: cx, y1: T, y2: T + plotH, stroke: css("--fail"), "stroke-width": 1, "stroke-dasharray": "3 3" }));
      node.appendChild(svg("circle", { cx: cx, cy: cy, r: 6, fill: css("--fail") }));
      var tag = svg("text", { x: cx + 10, y: cy - 10, "font-size": 12, "font-weight": 650, fill: css("--fail") });
      tag.textContent = pct(current.captureRate) + " caught";
      node.appendChild(tag);
    }

    var xLabel = svg("text", { x: L + plotW / 2, y: H - 6, "text-anchor": "middle", "font-size": 11, fill: css("--ink-muted") });
    xLabel.textContent = "Applications sent to review";
    node.appendChild(xLabel);
    var yLabel = svg("text", { x: 14, y: T + plotH / 2, "font-size": 11, fill: css("--ink-muted"),
      "text-anchor": "middle", transform: "rotate(-90 14 " + (T + plotH / 2) + ")" });
    yLabel.textContent = "Fraud attempts caught";
    node.appendChild(yLabel);

    host.appendChild(node);
    $("finding-capacity").textContent = findingCapacityText();
  }

  function findingCapacityText() {
    var current = currentPolicy();
    if (!current) return "";
    var inc = policyAt(incumbentIndex(), STATE.capacityIndex, 0);
    var name = DATA.policies.models[STATE.model].label;
    var text = "At " + pct(current.capacity, current.capacity < 0.01 ? 2 : 0) + " review capacity, " + name + " catches " +
      pct(current.captureRate) + " of fraud attempts";
    if (inc && STATE.model !== incumbentIndex()) {
      var gain = (current.captureRate - inc.captureRate) * 100;
      text += ", against " + pct(inc.captureRate) + " for the incumbent score proxy. That is a gain of " +
        gain.toFixed(1) + " percentage points";
    }
    text += ". The curve flattens as capacity grows: each additional reviewer returns less than the one before.";
    return text;
  }

  /* ---------------- exhibit 3: funnel ---------------- */

  function renderFunnel() {
    var host = $("chart-funnel");
    host.innerHTML = "";
    var policy = currentPolicy();
    if (!policy) return;
    var total = DATA.meta.applications;
    var stages = [
      { label: "Assessed", value: total, note: "every application in the period" },
      { label: "Sent to review", value: policy.actioned, note: "flagged by score or rule" },
      { label: "Worked within capacity", value: policy.worked, note: policy.referrals > 0 ? num(policy.referrals) + " referred beyond capacity" : "no overflow" },
      { label: "Confirmed fraud", value: policy.caught, note: "caught by this scenario" }
    ];

    var W = 980, rowH = 58, H = stages.length * rowH + 12;
    var L = 190, R = 150;
    var plotW = W - L - R;
    var node = svg("svg", { viewBox: "0 0 " + W + " " + H, width: "100%", height: H, role: "img",
      "aria-label": findingFunnelText() });

    stages.forEach(function (stage, i) {
      var y = i * rowH + 8;
      var w = Math.max((stage.value / total) * plotW, 2);
      node.appendChild(svg("rect", { x: L, y: y, width: w, height: 26,
        fill: i === stages.length - 1 ? css("--accent") : (i === 0 ? css("--rule") : css("--accent-soft")) }));
      var name = svg("text", { x: L - 12, y: y + 18, "text-anchor": "end", "font-size": 13, "font-weight": 600, fill: css("--ink") });
      name.textContent = stage.label;
      node.appendChild(name);
      var value = svg("text", { x: L + w + 12, y: y + 18, "font-size": 13, "font-weight": 650, fill: css("--ink") });
      value.textContent = num(stage.value);
      node.appendChild(value);
      var note = svg("text", { x: L - 12, y: y + 36, "text-anchor": "end", "font-size": 11, fill: css("--ink-muted") });
      note.textContent = stage.note;
      node.appendChild(note);
      if (i < stages.length - 1) {
        node.appendChild(svg("line", { x1: L, x2: W - R + 90, y1: y + 46, y2: y + 46, stroke: css("--rule") }));
      }
    });

    host.appendChild(node);
    $("finding-funnel").textContent = findingFunnelText();
  }

  function findingFunnelText() {
    var policy = currentPolicy();
    if (!policy) return "";
    var total = DATA.meta.applications;
    return num(total) + " applications produce " + num(policy.actioned) + " review cases (" +
      pct(policy.actioned / total, 1) + "), of which " + num(policy.caught) +
      " turn out to be fraud. The remaining " + num(policy.goodReviewed) +
      " are good customers held up. That is the cost of the policy, and it appears on no fraud report.";
  }

  /* ---------------- exhibit 5: monthly desk performance ---------------- */
  function renderKpi() {
    var section = document.querySelector("#table-kpi");
    if (!section) return;
    var kpi = DATA.kpi;
    var wrap = section.closest("section");
    // No pack, no exhibit. A desk record that has not been produced is absent, never
    // filled with a placeholder that would read as a measured period.
    if (!kpi || !kpi.periods || !kpi.periods.length) { if (wrap) wrap.hidden = true; return; }

    var body = section.querySelector("tbody");
    body.textContent = "";
    kpi.periods.forEach(function (row) {
      var tr = el("tr");
      tr.appendChild(el("th", { scope: "row" }, row.period));
      tr.appendChild(el("td", { class: "num" }, num(row.applications)));
      tr.appendChild(el("td", { class: "num" }, num(row.fraud)));
      tr.appendChild(el("td", { class: "num" }, row.rate_bps.toFixed(1) + " bps"));
      tr.appendChild(el("td", { class: "num" }, num(row.reviewed)));
      tr.appendChild(el("td", { class: "num" }, num(row.caught)));
      tr.appendChild(el("td", { class: "num" }, pct(row.catch_rate, 1)));
      var change = row.catch_change === null || row.catch_change === undefined
        ? "n/a"
        : (row.catch_change >= 0 ? "+" : "") + (row.catch_change * 100).toFixed(1) + " pp";
      tr.appendChild(el("td", { class: "num" }, change));
      tr.appendChild(el("td", { class: "num" }, pct(row.yield, 1)));
      body.appendChild(tr);
    });

    var first = kpi.periods[0];
    var last = kpi.periods[kpi.periods.length - 1];
    var lowest = kpi.periods.reduce(function (a, b) { return b.rate_bps < a.rate_bps ? b : a; });
    $("finding-kpi").textContent =
      "Fraud pressure rose from " + lowest.rate_bps.toFixed(1) + " bps in " + lowest.period.toLowerCase() +
      " to " + last.rate_bps.toFixed(1) + " bps in " + last.period.toLowerCase() +
      ", a " + Math.round((last.rate_bps / lowest.rate_bps - 1) * 100) + "% increase, while application volume fell from " +
      num(first.applications) + " to " + num(last.applications) + ". The reviewer hit rate rises with it, because " +
      "a fixed review capacity meets a richer pool of fraud, not because the ranking improved.";

    var vendor = kpi.vendor && kpi.vendor.length ? kpi.vendor[kpi.vendor.length - 1] : null;
    $("source-kpi").textContent =
      "Aggregated in the fraud database from the scores and the review queue, at " + pct(kpi.capacity, 0) +
      " review capacity." +
      (vendor ? " Against the incumbent score proxy, the proposed approach caught " + num(vendor.extra_caught) +
        " more fraud attempts in " + vendor.period.toLowerCase() + " at the same review workload." : "") +
      " Catch rate assumes review prevents the fraud it finds, so it is an upper bound. Neither approach is approved.";
  }
  /* ---------------- exhibit 4: segments ---------------- */

  function renderSegments() {
    var body = document.querySelector("#table-segments tbody");
    body.innerHTML = "";
    var maxRate = 0;
    DATA.segments.forEach(function (segment) {
      segment.groups.forEach(function (group) {
        if (group.publishable && group.fraud_rate > maxRate) maxRate = group.fraud_rate;
      });
    });

    var highest = null;
    DATA.segments.forEach(function (segment) {
      var header = el("tr");
      header.appendChild(el("th", { colspan: 5, scope: "colgroup", class: "group-row" }, segment.label));
      body.appendChild(header);

      segment.groups.forEach(function (group) {
        var tr = el("tr");
        tr.appendChild(el("th", { scope: "row" }, group.group));
        tr.appendChild(el("td", { class: "num" }, num(group.applications)));
        if (group.publishable) {
          if (!highest || group.fraud_rate > highest.fraud_rate) highest = { fraud_rate: group.fraud_rate, group: group.group, label: segment.label };
          tr.appendChild(el("td", { class: "num" }, num(group.fraud)));
          tr.appendChild(el("td", { class: "num" }, pct(group.fraud_rate, 2)));
          var share = Math.max((group.fraud_rate / maxRate) * 100, 2);
          var barCell = el("td", { class: "bar-cell" });
          var gauge = svg("svg", { width: 120, height: 8, viewBox: "0 0 100 8",
            preserveAspectRatio: "none", role: "presentation" });
          gauge.appendChild(svg("rect", { x: 0, y: 0, width: share, height: 8, fill: css("--accent") }));
          barCell.appendChild(gauge);
          tr.appendChild(barCell);
        } else {
          // The count is withheld along with the rate. Printing it left small groups
          // reading "0", which is the one thing the publication rule exists to prevent:
          // a group with six applications is not a group with no fraud.
          var withheld = el("td", { class: "withheld", colspan: 3 }, "Withheld, under 200 fraud attempts");
          tr.appendChild(withheld);
        }
        body.appendChild(tr);
      });
    });

    if (highest) {
      $("finding-segments").textContent = "The highest published fraud rate is in " + highest.label.toLowerCase() +
        " " + highest.group + ", at " + pct(highest.fraud_rate, 2) +
        ". Differences of this size are a reason to investigate, not a reason to treat a group differently: this product applies no group-specific threshold." +
        // The acceptance is a judgment someone made on a date, not an improvement in the
        // numbers. Saying so is the difference between a governance record and a green tick.
        (DATA.analyst && DATA.analyst.fairness_acceptance
          ? " Review-rate differences between these groups were examined and formally accepted on " +
            DATA.analyst.fairness_acceptance.date + "; the differences themselves are unchanged."
          : "");
    }
  }

  /* ---------------- queue ---------------- */

  function filteredCases() {
    return DATA.cases.filter(function (item) {
      var outcomeMatches = STATE.queueOutcome === "all" ||
        (STATE.queueOutcome === "fraud" && item.confirmed_fraud) ||
        (STATE.queueOutcome === "good" && !item.confirmed_fraud);
      var ruleMatches = STATE.queueRule === "all" ||
        (STATE.queueRule === "fired" && item.rules_fired.length) ||
        (STATE.queueRule === "none" && !item.rules_fired.length);
      return outcomeMatches && ruleMatches;
    });
  }

  function renderCaseDetail(item) {
    var panel = $("case-detail");
    if (!item) { panel.hidden = true; return; }
    STATE.selectedCase = item.id;
    panel.hidden = false;
    $("case-detail-heading").textContent = "Case " + item.id;

    var policy = currentPolicy();
    var facts = $("case-facts");
    facts.innerHTML = "";
    [
      ["Queue rank", num(item.rank)],
      ["Ranking score", pct(item.score, 1)],
      ["Simulated action", policy && item.rank <= policy.ceiling ? "Manual review" : "Governance referral"],
      ["Rules fired", num(item.rules_fired.length)],
      ["Retrospective result", item.confirmed_fraud ? "Confirmed fraud" : "Good customer"]
    ].forEach(function (fact) {
      var row = el("div");
      row.appendChild(el("dt", null, fact[0]));
      row.appendChild(el("dd", null, fact[1]));
      facts.appendChild(row);
    });

    var drivers = $("case-drivers");
    drivers.innerHTML = "";
    (item.drivers.length ? item.drivers : ["No score drivers recorded"]).forEach(function (driver) {
      drivers.appendChild(el("li", null, driver));
    });
    var rules = $("case-rules");
    rules.innerHTML = "";
    (item.rules_fired.length ? item.rules_fired : ["No concentration rule fired"]).forEach(function (rule) {
      rules.appendChild(el("li", null, rule));
    });
  }

  function renderQueue() {
    var body = document.querySelector("#table-queue tbody");
    body.innerHTML = "";
    var policy = currentPolicy();
    var ceiling = policy ? policy.ceiling : 0;
    var cases = filteredCases();
    var visible = cases.slice(0, STATE.queueLimit);

    visible.forEach(function (item) {
      var tr = el("tr");
      tr.appendChild(el("th", { scope: "row", class: "num" }, String(item.rank)));
      var caseCell = el("td");
      var caseButton = el("button", { type: "button", class: "case-link", "data-case": item.id }, item.id);
      caseButton.addEventListener("click", function () { renderCaseDetail(item); });
      caseCell.appendChild(caseButton);
      tr.appendChild(caseCell);
      tr.appendChild(el("td", { class: "num" }, pct(item.score, 1)));
      tr.appendChild(el("td", { class: "queue-secondary" }, item.rank <= ceiling ? "Manual review" : "Governance referral"));
      tr.appendChild(el("td", { class: "queue-secondary" }, item.rules_fired.length ? item.rules_fired.length + " fired" : "None"));
      var outcome = el("td", null, item.confirmed_fraud ? "Fraud" : "Good customer");
      outcome.className = item.confirmed_fraud ? "status-fail" : "";
      tr.appendChild(outcome);
      body.appendChild(tr);
    });

    $("queue-count").textContent = "Showing " + num(visible.length) + " of " + num(cases.length) + " sampled cases";
    $("queue-empty").hidden = cases.length > 0;
    document.querySelector("#table-queue").hidden = cases.length === 0;
    var more = $("queue-more");
    more.hidden = visible.length >= cases.length;
    more.textContent = "Show " + num(Math.min(10, cases.length - visible.length)) + " more";
    if (STATE.selectedCase) {
      renderCaseDetail(DATA.cases.find(function (item) { return item.id === STATE.selectedCase; }) || null);
    }

    $("queue-note").textContent = "Ranked by model score under " + DATA.policies.models[STATE.model].label +
      ". Select a case to inspect its score drivers and any concentration rules. Every action is simulated and non-binding. " +
      "Retrospective outcomes are shown only to judge queue quality.";
  }

  /* ---------------- decision ---------------- */

  function renderDecision() {
    var decision = DATA.decision;
    var word = $("verdict-word");
    word.textContent = decision.headline;
    word.className = "verdict-word " + (decision.status === "refused" ? "is-fail" : "is-pass");

    var tally = $("verdict-tally");
    tally.innerHTML = "";
    tally.appendChild(el("b", null, decision.checks_passed + " of " + decision.checks_total));
    tally.appendChild(document.createTextNode(" pre-agreed checks passed"));

    $("verdict-line").textContent = decision.status === "refused"
      ? "The proposed approach ranks fraud far better than the incumbent score proxy, and it still cannot be adopted. " +
        num(decision.checks_total - decision.checks_passed) +
        " checks agreed before any result was seen did not pass. The incumbent proxy remains only as a temporary ranking baseline, not an approved probability model."
      : "Every pre-agreed check passed. The proposed approach may go to governance for adoption.";

    var failures = $("failures");
    failures.innerHTML = "";
    decision.checks.filter(function (check) { return !check.passed; }).forEach(function (check) {
      var item = el("li");
      item.appendChild(el("span", { class: "flag" }, "DID NOT PASS"));
      var body = el("div");
      body.appendChild(el("div", { class: "what" }, check.label));
      if (check.consequence) body.appendChild(el("div", { class: "why" }, check.consequence));
      item.appendChild(body);
      failures.appendChild(item);
    });
  }

  function renderRiskDisposition() {
    if (!DATA.governance) return;
    var disposition = DATA.governance.incumbent_disposition;
    $("risk-current").textContent = "Do not adopt the challenger. The recorded answer is no robust recommendation.";
    $("risk-baseline").textContent = disposition.status + ". " + disposition.approval_state + ".";
    $("risk-permitted").textContent = disposition.permitted_use[0] + ". No automatic applicant decision.";
    $("risk-reopen").textContent = DATA.governance.reopen_decision_when[0] + ".";
  }

  function renderRiskControls() {
    var host = $("control-register");
    var reopen = $("reopen-conditions");
    host.innerHTML = "";
    reopen.innerHTML = "";
    var controls = DATA.governance && DATA.governance.monitoring_controls;
    if (!controls || !controls.length) {
      host.appendChild(el("li", { class: "control-empty" }, "Control register unavailable from reviewed evidence."));
      return;
    }
    controls.forEach(function (control) {
      var item = el("li");
      var heading = el("div", { class: "control-register-heading" });
      heading.appendChild(el("h3", null, control.label));
      heading.appendChild(el("span", { class: "control-state" }, control.availability));
      item.appendChild(heading);
      var facts = el("dl");
      [
        ["Owner", control.owner_role],
        ["Cadence", control.cadence],
        ["Trigger", control.trigger],
        ["Required action", control.action],
        ["Threshold basis", control.threshold_basis],
        ["Evidence boundary", control.evidence_source + ". " + control.limitation]
      ].forEach(function (pair) {
        var row = el("div");
        row.appendChild(el("dt", null, pair[0]));
        row.appendChild(el("dd", null, pair[1]));
        facts.appendChild(row);
      });
      item.appendChild(facts);
      host.appendChild(item);
    });
    DATA.governance.reopen_decision_when.forEach(function (condition) {
      reopen.appendChild(el("li", null, condition));
    });
  }

  /* ---------------- analyst detail ---------------- */

  function renderAnalyst() {
    var analyst = DATA.analyst;

    var lift = analyst.lift || {};
    if (lift.observed !== undefined) {
      $("lift-note").textContent = "Paired ranking lift over the incumbent score proxy was " +
        lift.observed.toFixed(4) + ", with a 95% interval of " + lift.lower_95.toFixed(4) + " to " +
        lift.upper_95.toFixed(4) + " from " + num(lift.resamples) + " fixed-seed resamples. The interval " +
        "excludes zero, so the ranking gain is not sampling noise. The refusal therefore rests on " +
        "calibration, stability, and segment review rather than on discrimination.";
    }

    var recorded = $("recorded-reasons");
    (DATA.decision.reasons || []).forEach(function (reason) {
      recorded.appendChild(el("li", null, reason));
    });

    var comparators = document.querySelector("#table-comparators tbody");
    analyst.comparators.forEach(function (item) {
      var tr = el("tr");
      tr.appendChild(el("th", { scope: "row" }, item.label));
      tr.appendChild(el("td", { class: "num" }, item.metrics.pr_auc.toFixed(4)));
      tr.appendChild(el("td", { class: "num" }, item.metrics.auroc.toFixed(4)));
      var intercept = el("td", { class: "num" }, item.metrics.calibration_intercept.toFixed(3));
      if (Math.abs(item.metrics.calibration_intercept) > 0.1) intercept.className = "num status-fail";
      tr.appendChild(intercept);
      comparators.appendChild(tr);
    });

    $("drift-note").textContent = num(analyst.drift.blocks) + " of " + num(analyst.drift.checks) +
      " feature-month checks moved past the level that blocks automatic adoption, measured against " +
      analyst.drift.reference + ", the whole period the model learned from. This is what the rising fraud rate looks like in the inputs.";
    var drift = document.querySelector("#table-drift tbody");
    analyst.drift.top_features.forEach(function (pair) {
      var tr = el("tr");
      tr.appendChild(el("th", { scope: "row" }, pair[0].replace(/_/g, " ")));
      tr.appendChild(el("td", { class: "num" }, String(pair[1])));
      drift.appendChild(tr);
    });

    var variants = document.querySelector("#table-variants tbody");
    analyst.variants.forEach(function (item) {
      var tr = el("tr");
      tr.appendChild(el("th", { scope: "row" }, item.source.replace(/_/g, " ").replace("baf ", "BAF ")));
      tr.appendChild(el("td", { class: "num" }, item.pr_auc.toFixed(4)));
      tr.appendChild(el("td", { class: "num" }, item.auroc.toFixed(4)));
      variants.appendChild(tr);
    });

    $("linking-note").textContent = analyst.linking.limitation;
    var linking = document.querySelector("#table-linking tbody");
    Object.keys(analyst.linking.summary).sort().forEach(function (key) {
      var entry = analyst.linking.summary[key];
      var tr = el("tr");
      tr.appendChild(el("th", { scope: "row" }, pct(parseFloat(key), 0)));
      tr.appendChild(el("td", { class: "num" }, entry.pairwise_f1_min.toFixed(3)));
      tr.appendChild(el("td", { class: "num" }, pct(entry.false_merge_rate_max, 1)));
      linking.appendChild(tr);
    });

    var provenance = document.querySelector("#table-provenance tbody");
    analyst.provenance.files.forEach(function (file) {
      var tr = el("tr");
      tr.appendChild(el("th", { scope: "row" }, file.name));
      tr.appendChild(el("td", { class: "num" }, num(file.rows)));
      tr.appendChild(el("td", { class: "num" }, pct(file.fraud_rate, 3)));
      tr.appendChild(el("td", null, file.sha256 + "…"));
      provenance.appendChild(tr);
    });
  }

  /* ---------------- controls ---------------- */

  function loadStateFromUrl() {
    var params = new URLSearchParams(window.location.search);
    var modelKey = params.get("model");
    var modelIndex = DATA.policies.models.findIndex(function (model) { return model.key === modelKey; });
    if (modelIndex >= 0) STATE.model = modelIndex;
    var capacity = parseFloat(params.get("capacity"));
    var capacityIndex = DATA.policies.capacities.indexOf(capacity);
    if (capacityIndex >= 0) STATE.capacityIndex = capacityIndex;
    (params.get("rules") || "").split(",").filter(Boolean).forEach(function (key) {
      if (DATA.policies.rules.some(function (rule) { return rule.key === key; })) STATE.rules[key] = true;
    });
    [["exposure", "fraud_exposure"], ["review", "review_cost"], ["friction", "friction_cost"]].forEach(function (pair) {
      var value = parseFloat(params.get(pair[0]));
      var config = DATA.assumptions[pair[1]];
      if (isFinite(value) && value >= config.min && value <= config.max) STATE[pair[0]] = value;
    });
  }

  function updateUrl() {
    var params = new URLSearchParams();
    params.set("model", DATA.policies.models[STATE.model].key);
    params.set("capacity", String(DATA.policies.capacities[STATE.capacityIndex]));
    var rules = DATA.policies.rules.filter(function (rule) { return STATE.rules[rule.key]; })
      .map(function (rule) { return rule.key; });
    if (rules.length) params.set("rules", rules.join(","));
    params.set("exposure", String(STATE.exposure));
    params.set("review", String(STATE.review));
    params.set("friction", String(STATE.friction));
    history.replaceState(null, "", window.location.pathname + "?" + params.toString() + window.location.hash);
  }

  function syncControls() {
    $("c-model").value = String(STATE.model);
    $("c-capacity").value = String(STATE.capacityIndex);
    document.querySelectorAll("#c-rules input").forEach(function (input) {
      input.checked = Boolean(STATE.rules[input.getAttribute("data-rule")]);
    });
    [["exposure", money], ["review", function (v) { return "$" + v; }], ["friction", function (v) { return "$" + v; }]].forEach(function (pair) {
      $("c-" + pair[0]).value = STATE[pair[0]];
      $("o-" + pair[0]).textContent = pair[1](STATE[pair[0]]);
    });
  }

  function setPreset(name) {
    STATE.model = name === "incumbent" ? incumbentIndex() : 0;
    STATE.capacityIndex = DATA.policies.capacities.indexOf(name === "tight" ? 0.03 : 0.05);
    DATA.policies.rules.forEach(function (rule) { STATE.rules[rule.key] = false; });
    syncControls();
    refresh();
  }

  function resetScenario() {
    STATE.model = 0;
    STATE.capacityIndex = DATA.policies.capacities.indexOf(0.05);
    STATE.exposure = DATA.assumptions.fraud_exposure.default;
    STATE.review = DATA.assumptions.review_cost.default;
    STATE.friction = DATA.assumptions.friction_cost.default;
    DATA.policies.rules.forEach(function (rule) { STATE.rules[rule.key] = false; });
    syncControls();
    refresh();
  }

  function buildControls() {
    var models = $("c-model");
    DATA.policies.models.forEach(function (model, index) {
      models.appendChild(el("option", { value: String(index) }, model.label));
    });
    models.value = String(STATE.model);
    models.addEventListener("change", function () { STATE.model = parseInt(models.value, 10); refresh(); });

    var caps = $("c-capacity");
    DATA.policies.capacities.forEach(function (value, index) {
      caps.appendChild(el("option", { value: String(index) },
        pct(value, value < 0.01 ? 2 : (value * 100) % 1 ? 1 : 0) + " of applications"));
    });
    caps.value = String(STATE.capacityIndex);
    caps.addEventListener("change", function () { STATE.capacityIndex = parseInt(caps.value, 10); refresh(); });

    var rules = $("c-rules");
    DATA.policies.rules.forEach(function (rule) {
      var label = el("label");
      var input = el("input", { type: "checkbox", "data-rule": rule.key });
      input.addEventListener("change", function () { STATE.rules[rule.key] = input.checked; refresh(); });
      label.appendChild(input);
      var text = el("span");
      text.appendChild(document.createTextNode(rule.label + " "));
      var decision = (DATA.governance.rule_dispositions || []).find(function (row) { return row.key === rule.key; });
      if (decision) {
        text.appendChild(el("strong", { class: "rule-disposition" },
          decision.disposition === "refer" ? "Refer for validation" : decision.disposition));
        text.appendChild(el("span", { class: "rule-reason" }, decision.rationale));
      }
      label.appendChild(text);
      rules.appendChild(label);
    });

    $("assumption-note").textContent = DATA.assumptions.note;
    slider("c-exposure", "o-exposure", DATA.assumptions.fraud_exposure, "exposure", money);
    slider("c-review", "o-review", DATA.assumptions.review_cost, "review", function (v) { return "$" + v; });
    slider("c-friction", "o-friction", DATA.assumptions.friction_cost, "friction", function (v) { return "$" + v; });

    document.querySelectorAll("[data-preset]").forEach(function (button) {
      button.addEventListener("click", function () { setPreset(button.getAttribute("data-preset")); });
    });
    $("scenario-reset").addEventListener("click", resetScenario);
    $("c-outcome").addEventListener("change", function () {
      STATE.queueOutcome = this.value; STATE.queueLimit = 10; renderQueue();
    });
    $("c-case-rule").addEventListener("change", function () {
      STATE.queueRule = this.value; STATE.queueLimit = 10; renderQueue();
    });
    $("queue-more").addEventListener("click", function () { STATE.queueLimit += 10; renderQueue(); });
    $("case-close").addEventListener("click", function () { STATE.selectedCase = null; renderCaseDetail(null); });
    syncControls();
  }

  function slider(inputId, outputId, config, key, format) {
    var input = $(inputId), output = $(outputId);
    input.min = config.min; input.max = config.max; input.step = config.step; input.value = STATE[key];
    output.textContent = format(STATE[key]);
    input.addEventListener("input", function () {
      STATE[key] = parseFloat(input.value);
      output.textContent = format(STATE[key]);
      renderMeasures(currentPolicy());
      renderImpact(currentPolicy());
      updateUrl();
    });
  }

  /* ---------------- boot ---------------- */

  function refresh() {
    renderMeasures(currentPolicy());
    renderImpact(currentPolicy());
    renderCapacity();
    renderFunnel();
    renderQueue();
    updateUrl();
  }

  function renderMeta() {
    $("meta-period").textContent = DATA.meta.period_label;
    $("meta-apps").textContent = num(DATA.meta.applications);
    $("meta-fraud").textContent = num(DATA.meta.fraud);
    $("meta-rate").textContent = pct(DATA.meta.fraud_rate, 2);
    $("meta-nature").textContent = DATA.meta.period_note;
    $("colophon-data").textContent = DATA.meta.data_nature +
      " Dataset " + DATA.meta.dataset_version + ", evidence revision " + DATA.meta.evidence_revision + ".";
    $("colophon-attribution").textContent =
      "Source: Bank Account Fraud suite (Jesus et al., NeurIPS 2022, Feedzai), used under CC BY-NC-SA 4.0. " +
      "Derived results share that licence. Non-commercial use only.";
  }

  function fail(message) {
    $("load-status").textContent = "Evidence unavailable";
    var main = $("main");
    main.innerHTML = "";
    var band = el("section", { class: "band" });
    band.appendChild(el("p", { class: "verdict-word is-fail" }, "Data unavailable"));
    band.appendChild(el("p", { class: "verdict-line" }, message));
    band.appendChild(el("p", { class: "note" },
      "Rebuild it with: PYTHONPATH=src uv run python scripts/build_dashboard_data.py"));
    var retry = el("button", { type: "button" }, "Retry loading evidence");
    retry.addEventListener("click", function () { window.location.reload(); });
    band.appendChild(retry);
    main.appendChild(band);
  }

  function applyPayload(payload) {
    DATA = payload;
    DATA.policies.columns.forEach(function (name, index) { COL[name] = index; });
    buildIndex();
    DATA.policies.rules.forEach(function (rule) { STATE.rules[rule.key] = false; });
    loadStateFromUrl();
    renderMeta();
    renderDecision();
    renderRiskDisposition();
    renderRiskControls();
    buildControls();
    renderTrend();
    renderKpi();
    renderSegments();
    renderAnalyst();
    refresh();
    $("load-status").hidden = true;
  }

  // Paint the decision from the critical block before the complete payload is read.
  var early = document.getElementById("critical");
  if (early) {
    try {
      var seed = JSON.parse(early.textContent);
      DATA = { meta: seed.meta, decision: seed.decision };
      renderMeta();
      renderDecision();
      renderRiskDisposition();
      renderMeasures(seed.policy);
    } catch (error) {
      /* The payload below is the authority; a bad seed must not block it. */
    }
  }

  // The complete reviewed evidence travels with the HTML so the dashboard also works
  // when opened directly from disk. The JSON file remains a fallback for an older or
  // partially generated page. The test-only flag exercises that recovery path.
  var embedded = document.getElementById("dashboard-data");
  if (embedded && !window.__FORCE_DATA_ERROR__) {
    try {
      applyPayload(JSON.parse(embedded.textContent));
      return;
    } catch (error) {
      /* Fall through to the separately versioned JSON file. */
    }
  }

  fetch("data/dashboard.json")
    .then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    })
    .then(applyPayload)
    .catch(function (error) {
      fail("Neither the embedded evidence nor its fallback file could be read (" + error.message + "). " +
        "No estimated figure is shown in its place.");
    });
})();
