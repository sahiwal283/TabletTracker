/**
 * Pill packing command center — server bootstrap JSON + polling snapshot API.
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

  /** KPI header monochrome icons (compact SVG — matches instrument-tile aesthetic) */
  var IK = {
    play:
      '<svg class="ops-kpi-ic" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M8 5v14l11-7z"/></svg>',
    pause:
      '<svg class="ops-kpi-ic" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>',
    idle:
      '<svg class="ops-kpi-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="12" cy="12" r="9"/></svg>',
    down:
      '<svg class="ops-kpi-ic" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>',
    chart:
      '<svg class="ops-kpi-ic" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V5h14v14zM7 10h2v7H7zm4-3h2v10h-2zm4 6h2v4h-2z"/></svg>',
    trend:
      '<svg class="ops-kpi-ic" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M16 6l2.29 2.29-4.88 4.88-4-4L2 16.59 3.41 18l6-6 4 4 6.3-6.29L22 12V6z"/></svg>',
    clock:
      '<svg class="ops-kpi-ic" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"/></svg>',
  };

  /** Matches ops-command-center-wall.css electric cyan */
  var ACCENT = "#00f2ff";
  var ACCENT_SOFT = "rgba(0, 242, 255, 0.14)";
  var ACCENT_FILL = "rgba(0, 242, 255, 0.09)";
  var GRID_LINE = "rgba(0, 242, 255, 0.09)";

  var POLL_MS = 8000;
  var root = document.getElementById("ops-root");
  if (!root) return;

  var url = root.getAttribute("data-snapshot-url");
  var cardsEl = document.getElementById("ops-cards");
  var feedEl = document.getElementById("ops-feed-list");
  var highlightsEl = document.getElementById("ops-highlights");
  var headEl = document.getElementById("ops-head");
  var clockEl = document.getElementById("ops-clock");
  var lastRefreshEl = document.getElementById("ops-last-refresh");

  var charts = {
    line: null,
    multi: null,
  };

  var chartCommon = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 450, easing: "easeOutQuart" },
    plugins: {
      legend: {
        display: true,
        labels: { color: "#cbd5e1", font: { size: 12, family: "'Inter', sans-serif" }, boxWidth: 14 },
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
          '</div><div class="ops-flow-delay-peak">Delay peak ' +
          Math.round(Number(dm)) +
          "m</div>";
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

    function lbl(ic, words) {
      return '<div class="ops-kpi-label-row">' + ic + '<span class="ops-kpi-label">' + words + "</span></div>";
    }
    headEl.innerHTML =
      '<div class="ops-kpi' +
      (down > 0 ? " ops-kpi--alert" : "") +
      '">' +
      lbl(IK.play, "Active") +
      '<div class="ops-kpi-value ops-kpi-value--run">' +
      (k.active_machines != null ? k.active_machines : "—") +
      "</div></div>" +
      '<div class="ops-kpi">' +
      lbl(IK.pause, "Paused") +
      '<div class="ops-kpi-value ops-kpi-value--idle">' +
      paused +
      "</div></div>" +
      '<div class="ops-kpi">' +
      lbl(IK.idle, "Idle") +
      '<div class="ops-kpi-value ops-kpi-value--idle">' +
      (k.idle_machines != null ? k.idle_machines : "—") +
      "</div></div>" +
      '<div class="ops-kpi' +
      (down > 0 ? " ops-kpi--alert" : "") +
      '">' +
      lbl(IK.down, "Down") +
      '<div class="ops-kpi-value ops-kpi-value--down">' +
      down +
      "</div>" +
      (down > 0 ? '<div class="ops-kpi-sub">Check stations</div>' : "") +
      "</div>" +
      '<div class="ops-kpi">' +
      lbl(IK.chart, "Displays today") +
      '<div class="ops-kpi-value ops-kpi-value--accent">' +
      displays.toLocaleString() +
      "</div>" +
      '<div class="ops-kpi-sub">final packaging submits</div></div>' +
      '<div class="ops-kpi' +
      tpClass +
      '">' +
      lbl(IK.trend, "Today vs 30d avg") +
      '<div class="ops-kpi-value ops-kpi-value--accent">' +
      (avg30 > 0.5 ? vs30 + "%" : "—") +
      "</div>" +
      '<div class="ops-kpi-sub">' +
      (avg30 > 0.5 ? "typical day " + avg30.toLocaleString() + " displays" : "building baseline") +
      "</div></div>" +
      '<div class="ops-kpi">' +
      lbl(IK.clock, "Avg cycle") +
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

  function renderHighlights(data) {
    if (!highlightsEl) return;
    var h = (data && data.highlights) || {};
    var best = h.best_station ? String(h.best_station) : "";
    var worst = h.lowest_output_station ? String(h.lowest_output_station) : "";
    highlightsEl.classList.add("occ-highlights-visible");
    var chunks = [];
    chunks.push(
      '<span class="occ-hl-chip occ-hl--best"><span class="occ-hl-lab">Highest throughput • shift</span> <strong>' +
        (best ? best.replace(/</g, "&lt;") : "—") +
        "</strong></span>",
    );
    chunks.push(
      '<span class="occ-hl-chip occ-hl--low"><span class="occ-hl-lab">Lowest throughput • coach</span> <strong>' +
        (worst ? worst.replace(/</g, "&lt;") : "—") +
        "</strong></span>",
    );
    highlightsEl.innerHTML = '<div class="occ-highlights-inner">' + chunks.join("") + "</div>";
  }

  function fmtEventEt(ms) {
    if (!ms) return "—";
    try {
      return new Date(ms).toLocaleTimeString("en-US", {
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
        hour12: true,
        timeZone: "America/New_York",
      });
    } catch (e) {
      return fmtFeedTime(ms);
    }
  }

  function renderActivityTable(activity) {
    var tbody = document.getElementById("ops-activity-body");
    if (!tbody) return;
    var rows = ((activity || []).slice().sort(function (a, b) {
      return (b.at_ms || 0) - (a.at_ms || 0);
    })).slice(0, 24);

    if (!rows.length) {
      tbody.innerHTML =
        '<tr><td colspan="3" class="occ-td-empty">No workflow events recorded for this refresh window.</td></tr>';
      return;
    }

    tbody.innerHTML = rows
      .map(function (it) {
        var sev = (it.severity || "info").toLowerCase();
        var msg = stripEmoji(it.message || "").replace(/</g, "&lt;");
        return (
          '<tr class="occ-row">' +
          '<td class="occ-td-time">' +
          fmtEventEt(it.at_ms) +
          "</td>" +
          '<td class="occ-td-class"><span class="occ-tag occ-tag--' +
          sev +
          '">' +
          sev.toUpperCase() +
          "</span></td>" +
          '<td class="occ-td-msg">' +
          msg +
          "</td></tr>"
        );
      })
      .join("");
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

    var tickFont = { size: 13, family: "'IBM Plex Mono', ui-monospace, monospace" };
    var darkScales = {
      x: {
        ticks: {
          color: "#cbd5e1",
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: 8,
          font: tickFont,
        },
        grid: { color: GRID_LINE },
      },
      y: {
        ticks: { color: "#cbd5e1", font: tickFont },
        grid: { color: GRID_LINE },
      },
    };

    var darkScalesBarTop = {
      x: Object.assign({}, darkScales.x, {
        ticks: Object.assign({}, darkScales.x.ticks, {
          maxRotation: 55,
          minRotation: 35,
          autoSkip: false,
        }),
      }),
      y: Object.assign({}, darkScales.y, { beginAtZero: true }),
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
                labels: { color: "#cbd5e1", font: { size: 12, family: "'Inter', sans-serif" }, boxWidth: 14 },
              },
            },
          }),
        });
    }
    if (!charts.multi) {
      var el2 = document.getElementById("c-chart-multi");
      if (el2)
        charts.multi = new Chart(el2, {
          type: "bar",
          data: { labels: [], datasets: [] },
          options: Object.assign({}, chartCommon, {
            scales: darkScalesBarTop,
            plugins: {
              legend: {
                display: false,
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
          tension: 0.22,
          borderWidth: 2.75,
          pointRadius: function (ctx) {
            var pts = ctx.dataset.data || [];
            var n = pts.length;
            if (n <= 2) return 4;
            return ctx.dataIndex % Math.max(1, Math.ceil(n / 16)) === 0 ? 4 : 0;
          },
          pointStyle: "rect",
          pointBackgroundColor: ACCENT,
          pointBorderColor: "#020508",
          pointBorderWidth: 1,
          pointHoverRadius: 7,
        },
        {
          label: "30d avg pace",
          data: data.chart_target_cumulative || [],
          borderColor: "rgba(251, 191, 36, 0.75)",
          borderDash: [6, 4],
          fill: false,
          tension: 0,
          pointRadius: 0,
          borderWidth: 2.5,
        },
      ];
      charts.line.update();
    }

    if (charts.multi) {
      var pkg = (data.machines || []).filter(function (m) {
        return String(m.station_kind || "").toLowerCase() === "packaging";
      });
      pkg.sort(function (a, b) {
        var da = a.displays_today != null ? a.displays_today : a.output_today || 0;
        var db = b.displays_today != null ? b.displays_today : b.output_today || 0;
        return db - da;
      });
      var top = pkg.slice(0, 10);
      if (!top.length) {
        charts.multi.data.labels = ["—"];
        charts.multi.data.datasets = [
          {
            label: "Displays today",
            data: [0],
            backgroundColor: "rgba(148,163,184,0.35)",
            borderColor: ACCENT,
            borderWidth: 1,
          },
        ];
      } else {
        charts.multi.data.labels = top.map(function (m) {
          return stripEmoji(m.display_name || "Station");
        });
        charts.multi.data.datasets = [
          {
            label: "Displays today",
            data: top.map(function (m) {
              return m.displays_today != null ? m.displays_today : m.output_today || 0;
            }),
            backgroundColor: top.map(function (_, j) {
              return palette[j % palette.length];
            }),
            borderColor: "rgba(0, 242, 255, 0.45)",
            borderWidth: 1,
          },
        ];
      }
      charts.multi.update();
    }
  }

  function apply(data) {
    if (!data || data.error) return;
    renderHeader(data);
    renderHighlights(data);
    renderFlow(data.flow);
    renderCards(data.machines);
    renderFeed(data.activity);
    renderActivityTable(data.activity);
    updateCharts(data);
    if (lastRefreshEl) {
      lastRefreshEl.textContent =
        "Snapshot " +
        new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
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

  (function bootstrapFromPage() {
    var node = document.getElementById("ops-tv-initial-data");
    if (!node || !node.textContent) return;
    var raw = node.textContent.trim();
    if (!raw || raw === "{}") return;
    try {
      var payload = JSON.parse(raw);
      if (payload && !payload.error) apply(payload);
    } catch (e) {}
  })();

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
