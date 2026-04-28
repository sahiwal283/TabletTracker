/**
 * TV operations board — polls snapshot API, renders tiles + Chart.js (no tables).
 */
(function () {
  /** Remove emoji / pictographs from API strings (chart labels, SKU names, feed). */
  function stripEmoji(input) {
    if (input == null || input === "") return typeof input === "string" ? input : "";
    var s = String(input);
    try {
      return s
        .replace(/\p{Extended_Pictographic}/gu, "")
        .replace(/\ufe0f/g, "")
        .replace(/\s+/g, " ")
        .trim();
    } catch (e) {
      return s;
    }
  }

  /** Matches html.ops-tv-wall / wall screen (#00e5ff accent) */
  var ACCENT = "#00e5ff";
  var ACCENT_SOFT = "rgba(0, 229, 255, 0.12)";
  var ACCENT_FILL = "rgba(0, 229, 255, 0.08)";
  var GRID_LINE = "rgba(0, 229, 255, 0.07)";

  var POLL_MS = 8000;
  var root = document.getElementById("ops-root");
  if (!root) return;

  var url = root.getAttribute("data-snapshot-url");
  var cardsEl = document.getElementById("ops-cards");
  var feedEl = document.getElementById("ops-feed-list");
  var headEl = document.getElementById("ops-head");
  var clockEl = document.getElementById("ops-clock");
  var lastRefreshEl = document.getElementById("ops-last-refresh");

  var charts = {
    line: null,
    multi: null,
    bar: null,
    idle: null,
    donut: null,
  };

  var chartCommon = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 450, easing: "easeOutQuart" },
    plugins: {
      legend: {
        display: true,
        labels: { color: "#cbd5e1", font: { size: 11, family: "'Inter', sans-serif" }, boxWidth: 14 },
      },
    },
    scales: {},
  };

  function fmtTime(ms) {
    if (!ms) return "--:--:--";
    var total = Math.max(0, Math.floor((Date.now() - ms) / 1000));
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
  }

  function fmtFeedTime(ms) {
    var d = new Date(ms);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function drawSpark(canvas, values) {
    if (!canvas || !values || !values.length) return;
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.offsetWidth;
    var H = canvas.offsetHeight;
    if (W < 2 || H < 2) return;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    var max = Math.max.apply(null, values.concat([1]));
    ctx.beginPath();
    ctx.strokeStyle = ACCENT;
    ctx.lineWidth = 2;
    values.forEach(function (v, i) {
      var x = (i / (values.length - 1 || 1)) * (W - 4) + 2;
      var y = H - 4 - (v / max) * (H - 8);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.lineTo(W - 2, H - 2);
    ctx.lineTo(2, H - 2);
    ctx.fillStyle = ACCENT_SOFT;
    ctx.fill();
  }

  function statusOrder(s) {
    if (s === "running") return 0;
    if (s === "paused") return 1;
    return 2;
  }

  function renderFlow(flow) {
    var el = document.getElementById("ops-flow");
    var bn = document.getElementById("ops-bottleneck");
    if (!el) return;
    if (!flow || !flow.pipeline || !flow.pipeline.length) {
      el.innerHTML = "";
      if (bn) bn.innerHTML = "";
      return;
    }
    var parts = [];
    flow.pipeline.forEach(function (node, i) {
      if (i > 0) {
        parts.push('<span class="ops-flow-arrow" aria-hidden="true">→</span>');
      }
      var al = node.alert || "ok";
      var mod = al === "warn" || al === "crit" ? " ops-flow-node--" + al : "";
      var dm = node.max_delay_min;
      var av = node.avg_delay_min;
      var delayTxt = "";
      if (dm != null) {
        delayTxt =
          '<div class="ops-flow-delay">max ' +
          dm +
          "m · avg " +
          (av != null ? av + "m" : "—") +
          "</div>";
      }
      var tr = node.delay_trend || "flat";
      var insightHtml = "";
      if (node.perf_insight) {
        insightHtml =
          '<div class="ops-flow-insight">' +
          String(node.perf_insight).replace(/</g, "&lt;") +
          "</div>";
      }
      if (tr === "up" || tr === "down") {
        var trClass = tr === "up" ? "ops-flow-trend--up" : "ops-flow-trend--down";
        var trLab = tr === "up" ? "Delay rising (36h)" : "Delay easing (36h)";
        insightHtml +=
          '<div class="ops-flow-insight"><span class="ops-flow-trend ' +
          trClass +
          '">' +
          trLab +
          "</span></div>";
      }
      parts.push(
        '<div class="ops-flow-node' +
        mod +
        '" data-stage="' +
        String(node.id || "").replace(/"/g, "") +
        '">' +
        '<div class="ops-flow-label">' +
        String(node.label || "").replace(/</g, "&lt;") +
        "</div>" +
        '<div class="ops-flow-wip">' +
        (node.wip != null ? node.wip : "—") +
        "</div>" +
        '<div class="ops-flow-sub">' +
        String(node.subtitle || "").replace(/</g, "&lt;") +
        "</div>" +
        delayTxt +
        insightHtml +
        "</div>"
      );
    });
    el.innerHTML = parts.join("");
    if (bn && flow.bottleneck) {
      var b = flow.bottleneck;
      bn.innerHTML =
        '<div class="ops-bn-title">Bottleneck</div>' +
        '<div class="ops-bn-reason">' +
        String(b.reason || "").replace(/</g, "&lt;") +
        "</div>" +
        '<div class="ops-bn-hint">' +
        String(b.hint || "").replace(/</g, "&lt;") +
        "</div>";
    }
  }

  function renderHeader(data) {
    if (!headEl) return;
    var k = data.kpis || {};
    var down = k.down_machines || 0;
    var displays = k.displays_today != null ? k.displays_today : 0;
    var avg30 = k.displays_30d_avg_per_day != null ? k.displays_30d_avg_per_day : 0;
    var vs30 = k.displays_vs_30d_pct != null ? k.displays_vs_30d_pct : 0;
    var cycle = k.avg_cycle_time_min;
    var cycleStr = cycle != null ? cycle + " min" : "—";
    var paused = k.paused_machines != null ? k.paused_machines : 0;
    var tpClass = "";
    if (avg30 > 0.5 && vs30 < 85) tpClass = " ops-kpi--behind";
    else if (avg30 > 0.5 && vs30 >= 110) tpClass = " ops-kpi--ahead";

    headEl.innerHTML =
      '<div class="ops-kpi' +
      (down > 0 ? " ops-kpi--alert" : "") +
      '">' +
      '<div class="ops-kpi-label">Active</div>' +
      '<div class="ops-kpi-value ops-kpi-value--run">' +
      (k.active_machines != null ? k.active_machines : "—") +
      "</div></div>" +
      '<div class="ops-kpi">' +
      '<div class="ops-kpi-label">Paused</div>' +
      '<div class="ops-kpi-value ops-kpi-value--idle">' +
      paused +
      "</div></div>" +
      '<div class="ops-kpi">' +
      '<div class="ops-kpi-label">Idle</div>' +
      '<div class="ops-kpi-value ops-kpi-value--idle">' +
      (k.idle_machines != null ? k.idle_machines : "—") +
      "</div></div>" +
      '<div class="ops-kpi' +
      (down > 0 ? " ops-kpi--alert" : "") +
      '">' +
      '<div class="ops-kpi-label">Down</div>' +
      '<div class="ops-kpi-value ops-kpi-value--down">' +
      down +
      "</div>" +
      (down > 0 ? '<div class="ops-kpi-sub">Check stations</div>' : "") +
      "</div>" +
      '<div class="ops-kpi">' +
      '<div class="ops-kpi-label">Displays today</div>' +
      '<div class="ops-kpi-value ops-kpi-value--accent">' +
      displays.toLocaleString() +
      "</div>" +
      '<div class="ops-kpi-sub">final packaging submits</div></div>' +
      '<div class="ops-kpi' +
      tpClass +
      '">' +
      '<div class="ops-kpi-label">Today vs 30d avg</div>' +
      '<div class="ops-kpi-value ops-kpi-value--accent">' +
      (avg30 > 0.5 ? vs30 + "%" : "—") +
      "</div>" +
      '<div class="ops-kpi-sub">' +
      (avg30 > 0.5 ? "typical day " + avg30.toLocaleString() + " displays" : "building baseline") +
      "</div></div>" +
      '<div class="ops-kpi">' +
      '<div class="ops-kpi-label">Avg cycle</div>' +
      '<div class="ops-kpi-value">' +
      cycleStr +
      "</div>" +
      '<div class="ops-kpi-sub">claim → finalized (median)</div></div>';
  }

  function renderCards(machines) {
    if (!cardsEl) return;
    var sorted = (machines || []).slice().sort(function (a, b) {
      var d = statusOrder(a.status) - statusOrder(b.status);
      if (d !== 0) return d;
      return (b.output_today || 0) - (a.output_today || 0);
    });
    cardsEl.innerHTML = sorted
      .map(function (m) {
        var st = m.status || "idle";
        var timerStart =
          st === "paused" && m.paused_at_ms
            ? m.paused_at_ms
            : m.occupancy_started_at_ms;
        var timer =
          st !== "idle" && timerStart
            ? '<div class="ops-card-timer" data-start-ms="' +
              timerStart +
              '">' +
              fmtTime(timerStart) +
              "</div>"
            : '<div class="ops-card-timer">—</div>';
        var tier = m.perf_tier || "inline";
        var rs = m.rate_session_uh;
        var rh = m.rate_hist_uh;
        var rt = m.rate_today_uh;
        var rateLine =
          rs != null && st === "running"
            ? "Run " + rs + "/hr · 7d avg " + (rh != null ? rh : "—") + "/hr"
            : "Today " + (rt != null ? rt : "—") + "/hr · 7d " + (rh != null ? rh : "—") + "/hr";
        var cyc = m.cycle_session_min;
        if (cyc != null && st === "running") {
          rateLine += " · " + cyc + "m cycle";
        }
        var hint = (m.perf_hint || "").replace(/</g, "&lt;");
        var prodLine = stripEmoji(m.product || "");
        var perfBlock =
          '<div class="ops-card-perf ops-card-perf--' +
          tier +
          '"><div class="ops-card-perf-rate">' +
          rateLine +
          "</div>" +
          (hint ? '<div class="ops-card-perf-hint">' + hint + "</div>" : "") +
          "</div>";
        var outUnit = m.output_unit || (m.station_kind === "packaging" ? "displays" : "tablets");
        var outLabel = outUnit === "displays" ? "Displays today" : "Tablets today";
        var outVal =
          m.output_today != null
            ? m.output_today
            : outUnit === "displays" && m.displays_today != null
              ? m.displays_today
              : m.tablets_today != null
                ? m.tablets_today
                : 0;
        return (
          '<article class="ops-card ops-card--' +
          st +
          '">' +
          '<div class="ops-card-name">' +
          (m.display_name || "Station") +
          "</div>" +
          '<div class="ops-card-kind">' +
          (m.station_kind || "") +
          "</div>" +
          '<div class="ops-card-status ops-card-status--' +
          st +
          '">' +
          st +
          "</div>" +
          '<div class="ops-card-product" title="' +
          prodLine.replace(/"/g, "&quot;") +
          '">' +
          (prodLine || "—") +
          "</div>" +
          timer +
          '<div class="ops-card-out">' +
          outLabel +
          " · " +
          Number(outVal).toLocaleString() +
          "</div>" +
          perfBlock +
          '<canvas class="ops-card-spark" width="200" height="36" data-spark="' +
          encodeURIComponent(JSON.stringify(m.sparkline || [])) +
          '"></canvas>' +
          "</article>"
        );
      })
      .join("");

    cardsEl.querySelectorAll("canvas.ops-card-spark").forEach(function (cnv) {
      try {
        var raw = decodeURIComponent(cnv.getAttribute("data-spark") || "[]");
        drawSpark(cnv, JSON.parse(raw));
      } catch (e) {}
    });
  }

  function tickTimers() {
    document.querySelectorAll(".ops-card-timer[data-start-ms]").forEach(function (el) {
      var ms = parseInt(el.getAttribute("data-start-ms"), 10);
      if (ms) el.textContent = fmtTime(ms);
    });
  }

  function renderFeed(items) {
    if (!feedEl) return;
    var rank = { alert: 0, warn: 1, info: 2 };
    var sorted = (items || []).slice().sort(function (a, b) {
      var ra = rank[a.severity] != null ? rank[a.severity] : 2;
      var rb = rank[b.severity] != null ? rank[b.severity] : 2;
      if (ra !== rb) return ra - rb;
      return (b.at_ms || 0) - (a.at_ms || 0);
    });
    feedEl.innerHTML = sorted
      .slice(0, 40)
      .map(function (it) {
        var sev = it.severity || "info";
        return (
          '<div class="ops-feed-item ops-feed-item--' +
          sev +
          '"><span class="ops-feed-time">' +
          fmtFeedTime(it.at_ms) +
          "</span>" +
          stripEmoji(it.message || "").replace(/</g, "&lt;") +
          "</div>"
        );
      })
      .join("");
  }

  function ensureCharts(labels) {
    if (typeof Chart === "undefined") return;

    var tickFont = { size: 12, family: "'IBM Plex Mono', ui-monospace, monospace" };
    var darkScales = {
      x: {
        ticks: {
          color: "#94a3b8",
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: 8,
          font: tickFont,
        },
        grid: { color: GRID_LINE },
      },
      y: {
        ticks: { color: "#94a3b8", font: tickFont },
        grid: { color: GRID_LINE },
      },
    };

    if (!charts.line) {
      var el = document.getElementById("c-chart-line");
      if (el)
        charts.line = new Chart(el, {
          type: "line",
          data: { labels: labels, datasets: [] },
          options: Object.assign({}, chartCommon, {
            scales: darkScales,
            plugins: {
              legend: {
                labels: { color: "#cbd5e1", font: { size: 11, family: "'Inter', sans-serif" }, boxWidth: 14 },
              },
            },
          }),
        });
    }
    if (!charts.multi) {
      var el2 = document.getElementById("c-chart-multi");
      if (el2)
        charts.multi = new Chart(el2, {
          type: "line",
          data: { labels: labels, datasets: [] },
          options: Object.assign({}, chartCommon, {
            scales: darkScales,
            plugins: {
              legend: {
                display: true,
                position: "bottom",
                labels: { color: "#cbd5e1", font: { size: 10, family: "'Inter', sans-serif" }, boxWidth: 12 },
              },
            },
          }),
        });
    }
    if (!charts.bar) {
      var el3 = document.getElementById("c-chart-bar");
      if (el3)
        charts.bar = new Chart(el3, {
          type: "bar",
          data: { labels: [], datasets: [] },
          options: Object.assign({}, chartCommon, {
            indexAxis: "y",
            scales: {
              x: {
                ticks: { color: "#94a3b8", font: tickFont },
                grid: { color: GRID_LINE },
              },
              y: {
                ticks: { color: "#cbd5e1", font: tickFont },
                grid: { display: false },
              },
            },
            plugins: { legend: { display: false } },
          }),
        });
    }
    if (!charts.idle) {
      var el4 = document.getElementById("c-chart-idle");
      if (el4)
        charts.idle = new Chart(el4, {
          type: "bar",
          data: { labels: [], datasets: [] },
          options: Object.assign({}, chartCommon, {
            indexAxis: "y",
            scales: {
              x: {
                stacked: true,
                max: 100,
                ticks: {
                  color: "#94a3b8",
                  font: tickFont,
                  callback: function (v) { return v + "%"; },
                },
                grid: { color: GRID_LINE },
              },
              y: {
                stacked: true,
                ticks: { color: "#cbd5e1", font: tickFont },
                grid: { display: false },
              },
            },
            plugins: {
              legend: {
                labels: { color: "#cbd5e1", font: { size: 10, family: "'Inter', sans-serif" }, boxWidth: 12 },
              },
            },
          }),
        });
    }
    if (!charts.donut) {
      var el5 = document.getElementById("c-chart-donut");
      if (el5)
        charts.donut = new Chart(el5, {
          type: "doughnut",
          data: { labels: [], datasets: [{ data: [], backgroundColor: [] }] },
          options: Object.assign({}, chartCommon, {
            cutout: "58%",
            plugins: {
              legend: {
                position: "bottom",
                labels: { color: "#cbd5e1", font: { size: 10, family: "'Inter', sans-serif" }, boxWidth: 12 },
              },
            },
          }),
        });
    }
  }

  var palette = [
    ACCENT,
    "#34d399",
    "#fbbf24",
    "#fb923c",
    "#a78bfa",
    "#f472b6",
    "#fde68a",
    "#38bdf8",
  ];

  function updateCharts(data) {
    if (typeof Chart === "undefined") return;
    var labels = data.hour_labels || [];
    ensureCharts(labels);

    if (charts.line) {
      charts.line.data.labels = labels;
      charts.line.data.datasets = [
        {
          label: "Cumulative displays",
          data: data.chart_cumulative_output || [],
          borderColor: ACCENT,
          backgroundColor: ACCENT_FILL,
          fill: true,
          tension: 0.25,
          borderWidth: 3,
        },
        {
          label: "30d avg pace",
          data: data.chart_target_cumulative || [],
          borderColor: "rgba(251, 191, 36, 0.65)",
          borderDash: [6, 4],
          fill: false,
          tension: 0,
          pointRadius: 0,
          borderWidth: 3,
        },
      ];
      charts.line.update();
    }

    if (charts.multi) {
      charts.multi.data.labels = labels;
      var series = data.chart_station_series || {};
      var names = data.chart_station_names || {};
      var ds = [];
      var i = 0;
      Object.keys(series).forEach(function (sid) {
        ds.push({
          label: names[sid] || "St " + sid,
          data: series[sid],
          borderColor: palette[i % palette.length],
          backgroundColor: "transparent",
          tension: 0.2,
          borderWidth: 3,
          pointRadius: 0,
        });
        i++;
      });
      if (!ds.length) {
        ds.push({
          label: "—",
          data: labels.map(function () { return 0; }),
          borderColor: "rgba(148,163,184,0.45)",
          borderWidth: 2,
          pointRadius: 0,
        });
      }
      charts.multi.data.datasets = ds;
      charts.multi.update();
    }

    if (charts.bar) {
      var bars = data.bar_by_station || [];
      if (!bars.length) {
        charts.bar.data.labels = ["—"];
        charts.bar.data.datasets = [
          { label: "Output", data: [0], backgroundColor: ["rgba(148,163,184,0.4)"] },
        ];
      } else {
        charts.bar.data.labels = bars.map(function (b) { return stripEmoji(b.name || ""); });
        charts.bar.data.datasets = [
          {
            label: "Output (packaging = displays · blister/seal = tablets)",
            data: bars.map(function (b) { return b.output; }),
            backgroundColor: bars.map(function (_, j) {
              return palette[j % palette.length];
            }),
          },
        ];
      }
      charts.bar.update();
    }

    if (charts.idle) {
      var idles = data.idle_pct_by_station || [];
      if (!idles.length) {
        charts.idle.data.labels = ["—"];
        charts.idle.data.datasets = [
          { label: "Engaged", data: [0], backgroundColor: "rgba(52, 211, 153, 0.4)" },
          { label: "Idle / wait", data: [100], backgroundColor: "rgba(251, 191, 36, 0.4)" },
        ];
      } else {
        charts.idle.data.labels = idles.map(function (r) { return stripEmoji(r.name || ""); });
        charts.idle.data.datasets = [
          {
            label: "Engaged",
            data: idles.map(function (r) { return r.load_pct; }),
            backgroundColor: "rgba(52, 211, 153, 0.75)",
          },
          {
            label: "Idle / wait",
            data: idles.map(function (r) { return r.pct; }),
            backgroundColor: "rgba(251, 191, 36, 0.55)",
          },
        ];
      }
      charts.idle.update();
    }

    if (charts.donut) {
      var fb = data.flavor_breakdown || [];
      if (!fb.length) {
        charts.donut.data.labels = ["No mix yet"];
        charts.donut.data.datasets = [
          { data: [1], backgroundColor: ["rgba(148,163,184,0.4)"] },
        ];
      } else {
        charts.donut.data.labels = fb.map(function (f) { return stripEmoji(f.label || ""); });
        charts.donut.data.datasets = [
          {
            data: fb.map(function (f) { return f.value; }),
            backgroundColor: fb.map(function (_, j) {
              return palette[j % palette.length];
            }),
          },
        ];
      }
      charts.donut.update();
    }
  }

  function apply(data) {
    if (!data || data.error) return;
    renderHeader(data);
    renderFlow(data.flow);
    renderCards(data.machines);
    renderFeed(data.activity);
    updateCharts(data);
    if (lastRefreshEl) {
      lastRefreshEl.textContent =
        "Snapshot · " +
        new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    }
    var footerStrip = document.getElementById("ops-footer-strip");
    if (footerStrip) {
      footerStrip.textContent =
        "Last updated " +
        new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    }
  }

  function poll() {
    fetch(url, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(apply)
      .catch(function () {});
  }

  poll();
  setInterval(poll, POLL_MS);
  setInterval(tickTimers, 1000);

  if (clockEl) {
    function tickClock() {
      clockEl.textContent = new Date().toLocaleString([], {
        weekday: "short",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    }
    tickClock();
    setInterval(tickClock, 1000);
  }

  window.addEventListener("resize", function () {
    document.querySelectorAll("canvas.ops-card-spark").forEach(function (cnv) {
      try {
        var raw = decodeURIComponent(cnv.getAttribute("data-spark") || "[]");
        drawSpark(cnv, JSON.parse(raw));
      } catch (e) {}
    });
  });
})();
