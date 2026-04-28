/**
 * Pill packing command center — React + htm, self-hosted vendors only.
 */
(function () {
  var React = window.React;
  var ReactDOM = window.ReactDOM;
  var htmVendor = window.htm;
  if (!React || !ReactDOM || !htmVendor) {
    var miss = document.getElementById("mes-root");
    if (miss) {
      miss.innerHTML =
        '<p style="color:#fecaca;padding:1.25rem;font:13px system-ui,sans-serif">MES libraries missing from /static/js/mes/vendor/</p>';
    }
    return;
  }
  var html = htmVendor.bind(React.createElement);
  var useState = React.useState;
  var useEffect = React.useEffect;
  var useMemo = React.useMemo;

  var NAV_DEFAULT = [
    { label: "Overview", tab: "overview", icon: "◇" },
    { label: "Blister Line", tab: "blister", icon: "▭" },
    { label: "Bottle Line", tab: "bottle", icon: "▭" },
    { label: "Card Line", tab: "card", icon: "▭" },
    { label: "Machines", tab: "machines", icon: "⚙" },
    { label: "Bags / Inventory", href: "/receiving", external: true, icon: "▣" },
    { label: "Staging", tab: "staging", icon: "▤" },
    { label: "Alerts", tab: "alerts", icon: "!" },
    { label: "Reports", href: "/reports", external: true, icon: "▦" },
    { label: "Analytics", href: "/reports", external: true, icon: "▧" },
    { label: "Users", href: "/admin/employees", external: true, icon: "◎" },
    { label: "Settings", href: "/admin/config", external: true, icon: "☰" },
  ];

  function normalizeNavEntry(item) {
    if (!item) return { label: "?", tab: "overview", icon: "◇" };
    if (item.tab) return item;
    if (item.external && item.href) return item;
    if (item.href) {
      var h = String(item.href);
      if (h.indexOf("receiving") >= 0)
        return { label: item.label, icon: item.icon, href: item.href, external: true };
      if (h.indexOf("/reports") >= 0 || h.indexOf("reports_view") >= 0)
        return { label: item.label, icon: item.icon, href: item.href, external: true };
      if (h.indexOf("employees") >= 0)
        return { label: item.label, icon: item.icon, href: item.href, external: true };
      if (h.indexOf("config") >= 0 || h.indexOf("product_config") >= 0)
        return { label: item.label, icon: item.icon, href: item.href, external: true };
      if (h.indexOf("#blister") >= 0) return { label: item.label, icon: item.icon, tab: "blister" };
      if (h.indexOf("#bottle") >= 0) return { label: item.label, icon: item.icon, tab: "bottle" };
      if (h.indexOf("#card") >= 0) return { label: item.label, icon: item.icon, tab: "card" };
      if (h.indexOf("#staging") >= 0) return { label: item.label, icon: item.icon, tab: "staging" };
      if (h.indexOf("#alerts") >= 0) return { label: item.label, icon: item.icon, tab: "alerts" };
      if (h.indexOf("ops-tv") >= 0) return { label: item.label, icon: item.icon, tab: "overview" };
      if (h.indexOf("/command-center") >= 0) return { label: item.label, icon: item.icon, tab: "machines" };
    }
    return { label: item.label, icon: item.icon, tab: "overview" };
  }

  function readNavBoot() {
    var exit = null;
    try {
      var n = document.getElementById("mes-nav-boot");
      if (n && n.textContent) {
        var o = JSON.parse(n.textContent.trim());
        if (o && o.exit && o.exit.href) exit = o.exit;
        if (o && o.nav && o.nav.length) {
          return { nav: o.nav.map(normalizeNavEntry), exit: exit };
        }
      }
    } catch (e) {}
    return { nav: NAV_DEFAULT.map(normalizeNavEntry), exit: exit };
  }

  function Sparkline({ vals, stroke }) {
    if (!vals || vals.length < 2) return null;
    var w = 96;
    var h = 14;
    var mn = Math.min.apply(null, vals);
    var mx = Math.max.apply(null, vals);
    var rg = mx - mn || 1;
    var pts = vals
      .map(function (v, i) {
        var x = (i / (vals.length - 1)) * (w - 4) + 2;
        var y = h - 1 - ((v - mn) / rg) * (h - 4);
        return x.toFixed(1) + "," + y.toFixed(1);
      })
      .join(" ");
    var fillPts = "0," + h + " " + pts + " " + w + "," + h;
    return html`<svg className="mes-spark" width=${w} height=${h} viewBox=${"0 0 " + w + " " + h}>
      <polygon fill=${stroke + "33"} stroke="none" points=${fillPts} />
      <polyline fill="none" stroke=${stroke} stroke-width="1.2" points=${pts} />
    </svg>`;
  }

  function fmtKpiVal(row) {
    var rid = row.id;
    if (row.value != null && typeof row.value === "string") return row.value;
    if (rid === "bags" || rid === "units" || rid === "cycles") {
      if (row.value == null) return "—";
      return typeof row.value === "number" ? Number(row.value).toLocaleString() : String(row.value);
    }
    if (rid === "avg_cycle") return row.value != null ? String(row.value) : "—";
    if (rid === "on_time" || rid === "rework" || rid === "oee") {
      if (row.value_pct == null && row.value == null) return "—";
      var n = row.value_pct != null ? row.value_pct : row.value;
      return typeof n === "number" ? n.toFixed(rid === "rework" ? 2 : 1) + "%" : String(n);
    }
    return "—";
  }

  function DeltaLine({ row }) {
    var t = "";
    if (row.delta_pct != null) t = (row.delta_pct >= 0 ? "↑ " : "↓ ") + Math.abs(row.delta_pct).toFixed(1) + "%";
    else if (row.delta_min != null) t = "Δ " + row.delta_min + "m";
    if (row.subtitle) t += (t ? " · " : "") + row.subtitle;
    var pos =
      row.delta_pct != null ? row.delta_pct >= 0 : row.delta_min != null ? row.delta_min <= 0 : true;
    return html`<div className=${"mes-kpi-delta " + (pos ? "mes-pos" : "mes-neg")}>${t}</div>`;
  }

  function KpiCard({ row, accent }) {
    var ttl = row.display_label || row.label;
    var fn = row.formula_note
      ? html`<div className="mes-kpi-formula" title=${row.formula_note}>${row.formula_note}</div>`
      : null;
    return html`
      <div className="mes-kpi-card">
        <div className="mes-kpi-title">${ttl}</div>
        <div className="mes-kpi-val">${fmtKpiVal(row)}</div>
        <${Sparkline} vals=${row.sparkline || []} stroke=${accent} />
        <${DeltaLine} row=${row} />
        ${fn}
      </div>
    `;
  }

  function shortDwell(d) {
    if (d == null || d === "") return "—";
    var s = String(d);
    return s.length > 14 ? s.slice(0, 13) + "…" : s;
  }

  function renderFlowMiniIllustration(st) {
    var Ill = window.MesMachineIllustrations;
    if (!Ill) return null;
    var key = String(st.key || "");
    var wip = Number(st.wip || 0) + Number(st.queue_depth || st.bags || 0);
    var run = wip > 0;
    var wrap = function (inner) {
      return React.createElement("div", { className: "mes-fn-mini-svg" }, inner);
    };
    if (key === "m1") return wrap(React.createElement(Ill.DPP115BlisterMachine, { running: run }));
    if (key === "m2") return wrap(React.createElement(Ill.HeatPressMachine, { running: run, variant: "M2" }));
    if (key === "m3") return wrap(React.createElement(Ill.HeatPressMachine, { running: run, variant: "M3" }));
    if (key === "m4") return wrap(React.createElement(Ill.StickeringMachine, { running: run }));
    if (key === "m5")
      return wrap(
        React.createElement(Ill.BottleSealingMachine, {
          running: run,
          dimmed: !st.bottleSealIntegrated,
        }),
      );
    if (key === "pkg" || key === "cpk") return wrap(React.createElement(Ill.PackagingStation, { running: run }));
    return null;
  }

  function FlowNode({ st }) {
    var sl = st.status_level || (st.alert === "crit" ? "crit" : st.alert === "warn" ? "warn" : "ok");
    var cp = st.congestion_pulse != null ? Number(st.congestion_pulse) : null;
    var cg =
      cp != null ? html`<div className="mes-fn-cong" style=${{ opacity: 0.12 + cp * 0.78 }} />` : null;
    var mini = renderFlowMiniIllustration(st);
    return html`
      <div className=${"mes-fn mes-fn-" + sl + (cp != null ? " mes-fn-live" : "")}>
        ${cg}
        ${mini}
        <div className="mes-fn-t">${st.title}</div>
        <div className="mes-fn-r">
          <span>WIP</span><span>${st.wip != null ? st.wip : "—"}</span>
          <span>Bags</span><span>${st.bags != null ? st.bags : "—"}</span>
          <span>Queue</span><span>${st.queue_depth != null ? st.queue_depth : "—"}</span>
          <span>Dwell</span><span>${shortDwell(st.dwell)}</span>
        </div>
      </div>
    `;
  }

  function FlowFork({ left, right }) {
    return html`
      <div className="mes-fn-split">
        <${FlowNode} st=${left} />
        <div className="mes-fn-or">OR</div>
        <${FlowNode} st=${right} />
      </div>
    `;
  }

  function flowChunks(lane) {
    var stages = lane.stages || [];
    var r = [];
    var i = 0;
    if (lane.id === "lane_blister") {
      while (i < stages.length) {
        if (
          stages[i].key === "m2" &&
          stages[i + 1] &&
          stages[i + 1].key === "m3"
        ) {
          r.push({ kind: "fork", left: stages[i], right: stages[i + 1] });
          i += 2;
        } else {
          r.push({ kind: "node", st: stages[i] });
          i++;
        }
      }
    } else {
      stages.forEach(function (st) {
        r.push({ kind: "node", st: st });
      });
    }
    return r;
  }

  function FlowLaneRow({ lane }) {
    var chunks = flowChunks(lane);
    var maxCong = 0;
    (lane.stages || []).forEach(function (st) {
      var c = st.congestion_pulse != null ? Number(st.congestion_pulse) : 0;
      if (c > maxCong) maxCong = c;
    });
    var arCls = "mes-fn-ar" + (maxCong > 0.32 ? " mes-fn-ar--pulse" : "");
    var parts = [];
    chunks.forEach(function (c, i) {
      if (i)
        parts.push(html`<div className=${arCls}>→</div>`);
      if (c.kind === "fork")
        parts.push(html`<${FlowFork} left=${c.left} right=${c.right} />`);
      else parts.push(html`<${FlowNode} st=${c.st} />`);
    });
    return html`
      <div className="mes-flow-lane">
        <div className="mes-flow-lane-h">
          ${lane.title}<span>SKU ${lane.sku || "—"}</span>
        </div>
        <div className="mes-flow-track">${parts}</div>
      </div>
    `;
  }

  function AlertsRail({ items }) {
    var rank = { alert: 0, warn: 1, info: 2 };
    var xs = (items || [])
      .slice()
      .sort(function (a, b) {
        return (rank[a.severity] ?? 2) - (rank[b.severity] ?? 2);
      });
    xs = xs.slice(0, 24);
    return html`
      <aside className="mes-alert-rail" id="mes-alerts" aria-label="Active alerts">
        <div className="mes-alert-rail-h">Alerts · priority</div>
        <div className="mes-alert-rail-list">
          ${xs.length
            ? xs.map(function (a, i) {
                var cls =
                  a.severity === "alert" ? "mes-ar-a" : a.severity === "warn" ? "mes-ar-w" : "";
                var t = a.at_ms != null ? new Date(Number(a.at_ms)).toLocaleTimeString([], {
                  hour: "numeric",
                  minute: "2-digit",
                }) : "—";
                return html`<div key=${i} className={"mes-ar-item " + cls}>
                  <span className="mes-num mes-muted">${t}</span>
                  ${a.message || ""}</div
                >`;
              })
            : html`<div className="mes-muted" style=${{ fontSize: "9px" }}>None.</div>`}
        </div>
      </aside>
    `;
  }

  function fmtTimerMs(ms) {
    if (ms == null) return "—";
    var sec = Math.max(0, Math.floor((Date.now() - Number(ms)) / 1000));
    var mm = Math.floor(sec / 60);
    var s2 = sec % 60;
    return mm + ":" + (s2 < 10 ? "0" : "") + s2;
  }

  function renderMachineIllustration(slot, running, notIntegrated) {
    var Ill = window.MesMachineIllustrations;
    var s = Number(slot || 1);
    if (!Ill) return null;
    if (s === 1) return React.createElement(Ill.DPP115BlisterMachine, { running: !!running });
    if (s === 2) return React.createElement(Ill.HeatPressMachine, { running: !!running, variant: "M2" });
    if (s === 3) return React.createElement(Ill.HeatPressMachine, { running: !!running, variant: "M3" });
    if (s === 4) return React.createElement(Ill.StickeringMachine, { running: !!running });
    return React.createElement(Ill.BottleSealingMachine, { running: !!running, dimmed: !!notIntegrated });
  }

  function ScadaTwinCard({ m }) {
    var light = String(m.statusLight || m.status_light || "idle").toLowerCase();
    var dot =
      light === "run"
        ? "mes-scada-dot-run"
        : light === "wait"
          ? "mes-scada-dot-wait"
          : light === "fault"
            ? "mes-scada-dot-fault"
            : "mes-scada-dot-idle";
    var rawStatus = String(m.rawStatus || m.raw_status || "idle").toLowerCase();
    var idleUi = rawStatus === "idle" || String(m.statusUi || m.status || "").indexOf("NOT") >= 0;
    var ds = String(m.dataSourceStatus || m.data_source_status || "");
    var blocked = ds === "NOT_INTEGRATED";
    var slo = Number(m.slot || m.twin_slot || 1);
    var runFx = String(m.statusUi || m.status || "").toUpperCase() === "RUNNING";
    var stTxt = m.statusUi != null ? m.statusUi : m.status != null ? m.status : "—";
    var stCls = /WAIT/.test(stTxt) ? "mes-wait" : /RUN|ING/.test(stTxt) ? "mes-run" : "mes-idle";
    var bag = m.bagId != null ? String(m.bagId) : m.bag_id != null ? String(m.bag_id) : "—";
    var ctr = m.counterDisplay != null ? String(m.counterDisplay) : m.counter_current != null ? String(m.counter_current) : "—";
    var thru = m.throughputUh != null ? String(m.throughputUh) : m.throughput_uh != null ? Number(m.throughput_uh).toFixed(1) : "—";
    var util = m.utilizationPct != null ? String(m.utilizationPct) : m.utilization_pct != null ? m.utilization_pct + "%" : "—";
    var oees = m.oeePct != null ? String(m.oeePct) : m.oee_pct != null ? m.oee_pct + "%" : "—";
    var opLab = m.operatorLabel != null ? String(m.operatorLabel) : m.operator != null ? String(m.operator) : "—";
    var cyc =
      m.cycleElapsedMin != null
        ? String(m.cycleElapsedMin)
        : m.cycle_elapsed_min != null
          ? m.cycle_elapsed_min + "m"
          : "—";
    var ls = m.lastScan != null ? String(m.lastScan) : m.last_scan_ms ? new Date(m.last_scan_ms).toLocaleTimeString() : "—";
    var tms = m.timerMs != null ? m.timerMs : m.timer_ms;
    return html`
      <div className=${"mes-scada mes-scada-twin" + (idleUi ? " mes-scada-idle" : "") + (blocked ? " mes-scada-locked" : "")}>
        <div className="mes-twin-shell mes-mac-stage">
          <div aria-hidden>${renderMachineIllustration(slo, runFx && !blocked, blocked)}</div>
          <div className="mes-twin-overlay mes-twin-overlay--narrow">
            <span className="mes-twin-beacon"
              ><span className=${"mes-scada-dot sm " + dot} title="Beacon"></span>${stTxt}</span
            >
            <span className="mes-twin-ovl"
              ><span className="mes-muted">Data</span> ${String(m.dataSourceLine || "")}</span
            >
            ${m.integrationMessage
              ? html`<span className="mes-twin-note">${String(m.integrationMessage)}</span>`
              : null}
          </div>
          <span className="mes-twin-corner-dot ${dot}" title=${String(m.dataSourceStatus || "")} />
        </div>
        <div className="mes-scada-top mes-twin-caption">
          <span className={"mes-scada-dot md " + dot} title="status" />
          <div style=${{ minWidth: 0 }}>
            <div className="mes-scada-name">${m.short_label || m.shortLabel || m.canonical}</div>
            <div className="mes-scada-can">${m.label}</div>
          </div>
          <div className=${"mes-scada-st " + stCls}>${stTxt}</div>
        </div>
        <div className="mes-scada-grid2">
          <span className="mes-muted">Timer</span><span className="mes-num rt">${blocked ? "N/A" : fmtTimerMs(tms)}</span>
          <span className="mes-muted">Bag</span><span className="mes-num rt">${blocked ? "N/A" : bag}</span>
          <span className="mes-muted">Counter</span><span className="mes-num rt">${ctr}</span>
          <span className="mes-muted">Thru · u/h</span><span className="mes-num rt mes-c-util">${thru}</span>
          <span className="mes-muted">Util%</span><span className="mes-num rt mes-c-util">${util}</span>
          <span className="mes-muted">OEE</span><span className="mes-num rt mes-c-oee">${oees}</span>
          <span className="mes-muted">Operator</span><span className="mes-ell rt">${opLab}</span>
          <span className="mes-muted">Cycle</span><span className="mes-num rt">${blocked ? "N/A" : cyc}</span>
          <span className="mes-muted">Last scan</span><span className="mes-num rt">${blocked ? "N/A" : ls}</span>
          <span className="mes-muted">Source</span><span className="mes-ell rt mes-num">${String(ds)}</span>
        </div>
      </div>
    `;
  }

  function MetricsNotesStrip({ notes }) {
    var n = notes || [];
    if (!n.length) return null;
    return html`<div className="mes-pharma-strip mes-metrics-notes">${n.join(" · ")}</div>`;
  }

  function BagGenealogyLive({ metricInputs }) {
    var qi = useState("");
    var q = qi[0];
    var setQ = qi[1];
    var inp = metricInputs || {};
    var Mes = window.MesMetrics;
    var defBid = inp.genealogySelectedBagId;
    var eb = parseInt(String(q || "").trim(), 10);
    var bagId = !isNaN(eb) ? eb : defBid || null;
    var geo =
      Mes && Mes.deriveBagGenealogy && inp.events && inp.bags && bagId != null
        ? Mes.deriveBagGenealogy(bagId, inp.events, inp.bags)
        : { traceLines: [], sku: "—", receivedQtyDisplay: "—", totals: { message: "Insufficient data" } };
    var steps = geo.traceLines || [];
    var hdr =
      geo.bagId != null ? "Lot trace · Bag " + String(geo.bagId) + " · " + (geo.sku || "") : "Live bag genealogy";
    return html`<div className="mes-panel mes-gene">
      <div className="mes-panel-h">${hdr}</div>
      <div className="mes-gene-trace">
        <label className="mes-muted" for="mes-trace-q">Trace bag ID</label>
        <input
          id="mes-trace-q"
          className="mes-gene-inp"
          type="search"
          value=${q}
          placeholder=${defBid ? String(defBid) : "Enter bag"}
          aria-label="Trace bag id"
          onInput=${function (ev) {
            setQ(ev.target.value);
          }}
        />
      </div>
      <div className="mes-gene-sum">
        <span>SKU <strong>${geo.sku}</strong></span><span>Rcvd qty <strong>${geo.receivedQtyDisplay}</strong></span
        ><span>Elapsed <strong>${geo.totals && geo.totals.elapsedMinutes != null ? geo.totals.elapsedMinutes.toFixed(1) + "m" : "—"}</strong></span
        ><span>Dwell Δ <strong>${geo.totals && geo.totals.dwellMinutes != null ? geo.totals.dwellMinutes.toFixed(1) + "m" : "—"}</strong></span>
      </div>
      <div className="mes-gene-scroll">
        ${steps.length
          ? steps.map(function (st, ix) {
              var tm = st.pending || !st.atMs ? "" : new Date(st.atMs).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
              var dw = st.dwellFromPrevMinutes != null ? st.dwellFromPrevMinutes.toFixed(1) + "m Δ" : "—";
              var pend = !!st.pending;
              return html`<div key=${ix} className=${"mes-gene-row" + (pend ? " mes-gene-row--pending" : "")}>
                <span className="mes-gene-dot">${pend ? "○" : "●"}</span>
                <span className="mes-gene-time">${tm || "—"}</span>
                <span className="mes-gene-main">
                  ${st.label}${st.machineLabel ? " · " + st.machineLabel : ""}
                  ${st.counterReading
                    ? html`<span className="mes-gene-ctr"> · ctr ${String(st.counterReading)}</span>`
                    : null}
                  <span className="mes-gene-sub"
                    >${st.operatorLabel ? " · op " + st.operatorLabel : ""} · dwell ${dw}
                    · <span className="mes-gene-badge">${st.statusBadge || ""}</span></span
                  >
                </span>
              </div>`;
            })
          : html`<div className="mes-muted" style=${{ fontSize: "10px", padding: "0.35rem" }}>${(geo.totals && geo.totals.message) || "No lineage rows"}</div>`}
        <div className="mes-gene-foot mes-muted">Electronic batch-record mode (future): tie exceptions · release signatures here.</div>
      </div>
    </div>`;
  }

  function SvgLine({ labels, series }) {
    var W = 400;
    var H = 100;
    var keys = Object.keys(series || {});
    if (!keys.length)
      return html`<div className="mes-muted" style=${{ fontSize: "10px", padding: "0.25rem" }}>—</div>`;
    var all = keys.flatMap(function (k) {
      return series[k] || [];
    });
    var mx = Math.max.apply(null, all.concat([1]));
    var palette = ["#22d3ee", "#4ade80", "#a78bfa"];
    return html`
      <svg style=${{ width: "100%", height: "auto", maxHeight: "90px" }} viewBox=${"0 0 " + W + " " + H}>
        ${keys.map(function (k, ki) {
          var pts = (series[k] || []).map(function (v, ix) {
            var x = (ix / Math.max(1, (labels || []).length - 1)) * (W - 20) + 10;
            var y = H - 8 - (v / mx) * (H - 16);
            return x.toFixed(1) + "," + y.toFixed(1);
          });
          return html`<polyline
            key=${k}
            fill="none"
            stroke=${palette[ki % palette.length]}
            stroke-width="2"
            points=${pts.join(" ")}
          />`;
        })}
      </svg>
      <div className="mes-tr">
        ${keys.map(function (k, ki) {
          return html`<span key=${k}><span style=${{ color: palette[ki % palette.length] }}>■</span> ${k}</span>`;
        })}
      </div>
    `;
  }

  function SvgBars({ labels, today, yesterday }) {
    var W = 400;
    var H = 90;
    var n = Math.max((labels || []).length, 1);
    var all = (today || []).concat(yesterday || []);
    var mx = Math.max.apply(null, all.concat([1]));
    var bw = (W - 40) / n / 2.2;
    return html`
      <svg style=${{ width: "100%", height: "auto", maxHeight: "88px" }} viewBox=${"0 0 " + W + " " + H}>
        ${(labels || []).map(function (lab, i) {
          var x0 = 20 + (i * (W - 40)) / n;
          var h1 = ((today[i] || 0) / mx) * (H - 24);
          var h2 = ((yesterday[i] || 0) / mx) * (H - 24);
          return html`<g key=${lab}>
            <rect x=${x0} y=${H - 8 - h1} width=${bw} height=${h1} fill="#22d3ee" opacity="0.85" />
            <rect
              x=${x0 + bw + 2}
              y=${H - 8 - h2}
              width=${bw}
              height=${h2}
              fill="#64748b"
              opacity="0.75"
            />
          </g>`;
        })}
      </svg>
      <div className="mes-legend"><span style=${{ color: "#22d3ee" }}>■</span>T <span style=${{ color: "#64748b" }}>■</span>Y</div>
    `;
  }

  function SvgDonut({ oee }) {
    var o = oee || {};
    function rowDn(label, primary, fallback, color) {
      var src = primary != null && primary !== "" ? primary : fallback;
      var vn = donutTotalNum(src);
      var txt = !isNaN(vn)
        ? vn.toFixed(2) + "%"
        : src != null
          ? String(src)
          : "—";
      if (/insufficient/i.test(String(txt).toLowerCase())) txt = "Insufficient data";
      return html`<div key=${label} style=${{ display: "flex", justifyContent: "space-between" }}
        ><span style=${{ color: color }}>${label}</span
        ><span>${txt}</span></div
      >`;
    }
    var totSrc = o.total_raw != null && o.total_raw !== "" ? o.total_raw : o.total != null ? o.total : NaN;
    var totDn = donutTotalNum(totSrc);
    var totalTop = !isNaN(totDn) ? totDn.toFixed(2) + "%" : totSrc !== undefined && totSrc !== null ? String(totSrc) : "—";
    return html`
      <div style=${{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "0.25rem",
        flex: 1,
        minHeight: 0,
      }}>
        <div style=${{ fontSize: "1.12rem", fontWeight: 900, color: "#e0f2fe", textAlign: "center" }}>${totalTop}</div>
        <div className="mes-muted" style=${{ fontSize: "8px", textTransform: "uppercase", letterSpacing: "0.1em" }}>
          OEE
        </div>
        <div
          style=${{
            marginTop: "0.35rem",
            width: "100%",
            fontSize: "9px",
            display: "flex",
            flexDirection: "column",
            gap: "0.12rem",
          }}
        >
          ${rowDn("Avail", o.avail_raw, o.availability, "#22d3ee")}
          ${rowDn("Perf", o.perf_raw, o.performance, "#fb923c")}
          ${rowDn("Qual", o.qual_raw, o.quality, "#4ade80")}
        </div>
      </div>
    `;
  }

  function fmtSnapTime(ms) {
    if (ms == null) return null;
    try {
      return new Date(Number(ms)).toLocaleTimeString();
    } catch (e) {
      return null;
    }
  }

  function donutTotalNum(raw) {
    if (typeof raw === "number" && !isNaN(raw)) return Math.min(100, Math.max(0, raw));
    if (typeof raw === "string" && /^insufficient/i.test(raw.trim())) return NaN;
    var m = /([0-9]+(?:\.[0-9]+)?)/.exec(String(raw || ""));
    return m ? Math.min(100, Math.max(0, parseFloat(m[1]))) : NaN;
  }

  function App({ snapshotUrl }) {
    var _snapState = useState(null);
    var snap = _snapState[0];
    var setSnap = _snapState[1];
    var _errState = useState(null);
    var err = _errState[0];
    var setErr = _errState[1];
    var _tickState = useState(0);
    var tick = _tickState[0];
    var setTick = _tickState[1];

    var navBoot = useMemo(function () {
      return readNavBoot();
    }, []);
    var nav = navBoot.nav;
    var navExit = navBoot.exit;

    var _navTabSt = useState("overview");
    var mesNavTab = _navTabSt[0];
    var setMesNavTab = _navTabSt[1];

    var exitHref = navExit && navExit.href ? navExit.href : null;
    if (!exitHref) {
      try {
        var rootEl = document.getElementById("mes-root");
        if (rootEl && rootEl.dataset && rootEl.dataset.commandCenterUrl) {
          exitHref = rootEl.dataset.commandCenterUrl;
        }
      } catch (e) {}
    }

    useEffect(
      function () {
        var id =
          mesNavTab === "overview"
            ? "mes-anchor-top"
            : mesNavTab === "blister" || mesNavTab === "bottle" || mesNavTab === "card"
              ? "mes-anchor-process"
              : mesNavTab === "machines"
                ? "mes-anchor-scada"
                : mesNavTab === "staging"
                  ? "mes-anchor-staging"
                  : mesNavTab === "alerts"
                    ? "mes-alerts"
                    : "mes-anchor-top";
        var el = document.getElementById(id);
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      },
      [mesNavTab]
    );

    useEffect(function () {
      var node = document.getElementById("ops-tv-initial-data");
      if (node && node.textContent) {
        try {
          var raw = node.textContent.trim();
          if (raw && raw !== "{}") {
            var p = JSON.parse(raw);
            if (p && !p.error) setSnap(p);
          }
        } catch (e) {}
      }
      function load() {
        fetch(snapshotUrl, { credentials: "same-origin" })
          .then(function (r) {
            return r.json();
          })
          .then(function (d) {
            if (d.error) throw new Error(d.error);
            setSnap(d);
            setErr(null);
          })
          .catch(function (e) {
            setErr(String(e));
          });
      }
      load();
      var id = setInterval(load, 10000);
      var t2 = setInterval(function () {
        setTick(function (t) {
          return t + 1;
        });
      }, 1000);
      return function () {
        clearInterval(id);
        clearInterval(t2);
      };
    }, [snapshotUrl]);

    var mes = (snap && snap.mes) || {};
    void tick;
    var derived =
      typeof window.MesMetrics !== "undefined" && mes.metrics_inputs
        ? window.MesMetrics.deriveDashboardMetrics(mes.metrics_inputs)
        : null;
    var kpis = mes.kpis || [];
    if (derived && derived.kpis) {
      var bydk = {};
      for (var di = 0; di < derived.kpis.length; di++) bydk[derived.kpis[di].id] = derived.kpis[di];
      kpis = kpis.map(function (row) {
        var dk = bydk[row.id];
        if (!dk) return row;
        var o = Object.assign({}, row);
        if (dk.value !== undefined && dk.value !== null) o.value = dk.value;
        if (dk.valuePct != null) o.value_pct = dk.valuePct;
        if (dk.formulaNote) o.formula_note = dk.formulaNote;
        if (dk.displayLabel) o.display_label = dk.displayLabel;
        if (dk.sparkline !== undefined) o.sparkline = dk.sparkline;
        return o;
      });
    }
    var lanes = mes.lanes || [];
    var alerts = mes.alerts || (snap && snap.activity) || [];
    var mergedAlerts = alerts;
    var scada =
      derived && derived.machines && derived.machines.length ? derived.machines : mes.scada_machines || [];
    var trend = mes.trend || {};
    var cyc = mes.cycle_analysis || {};
    var donut = derived ? derived.oeeDonut || {} : mes.oee_donut || {};
    var oee =
      derived && donut
        ? {
            total_raw: donut.total,
            avail_raw: donut.availability,
            perf_raw: donut.performance,
            qual_raw: donut.quality,
            total_num: donutTotalNum(donut.total),
            avail_num: donutTotalNum(donut.availability),
            perf_num: donutTotalNum(donut.performance),
            qual_num: donutTotalNum(donut.quality),
          }
        : mes.oee_donut || {};
    var inv = mes.inventory || [];
    var skuT = mes.sku_table || [];
    var stg = mes.staging || [];
    var tl = mes.timeline || [];
    var team = mes.team || [];
    var down = mes.downtime || [];
    var accents = ["#22d3ee", "#4ade80", "#fbbf24", "#a78bfa", "#f472b6", "#38bdf8", "#94a3b8"];
    var genAt = mes.generated_at_ms != null ? mes.generated_at_ms : snap != null ? snap.generated_at_ms : null;
    var lastUp = fmtSnapTime(genAt) || (snap ? new Date().toLocaleTimeString() : "—");

    return html`
      <div className="mes-app" data-wall-tick=${tick}>
        <aside className="mes-aside">
          ${exitHref
            ? html`<a className="mes-exit-cc" href=${exitHref}
                >${navExit && navExit.label ? navExit.label : "Exit to Command Center"}</a
              >`
            : null}
          ${nav.map(function (item, i) {
            if (item.href && item.external) {
              return html`<a
                key=${item.label + String(i)}
                href=${item.href}
                target="_blank"
                rel="noopener noreferrer"
                className="mes-nav-a mes-nav-a--ext"
                ><span className="mes-nav-ic">${item.icon}</span>${item.label}</a
              >`;
            }
            var tab = item.tab || "overview";
            var active = mesNavTab === tab;
            return html`<button
              type="button"
              key=${item.label + String(i)}
              className=${"mes-nav-a" + (active ? " mes-active" : "")}
              onClick=${function () {
                setMesNavTab(tab);
              }}
              ><span className="mes-nav-ic">${item.icon}</span>${item.label}</button
            >`;
          })}
        </aside>
        <div className="mes-main">
          ${err ? html`<div className="mes-banner-err">${err}</div>` : null}
          <header className="mes-header" id="mes-anchor-top">
            <div>
              <h1 className="mes-h1">Pill Packing Command Center</h1>
              <p className="mes-sub">Real-time production monitoring — LIVE</p>
            </div>
            <div className="mes-header-right">
              <span id="mes-clock" className="mes-clock"></span>
              <select className="mes-select"><option>All Lines</option></select>
              <select className="mes-select"><option>All SKUs</option></select>
            </div>
          </header>

          <div className="mes-cc-stack">
            <div className="mes-b1">
              <div className="mes-kpi-strip">
                ${kpis.map(function (row, idx) {
                  return html`<${KpiCard} key=${row.id || idx} row=${row} accent=${accents[idx % accents.length]} />`;
                })}
              </div>
            </div>

            <div className="mes-b2">
              <div className="mes-b2-inner">
                <section className="mes-process-map" id="mes-anchor-process" aria-label="Production map">
                  <div className="mes-pm-h">Production control map</div>
                  ${lanes.map(function (lane, i) {
                    return html`<${FlowLaneRow} key=${lane.id || i} lane=${lane} />`;
                  })}
                </section>
                <${AlertsRail} items=${mergedAlerts} />
              </div>
            </div>

            <div className="mes-b3" id="mes-anchor-scada">
              <div className="mes-b3-h">Machine command grid</div>
              <section className="mes-scada-row">${scada.map(function (m, i) {
                return html`<${ScadaTwinCard} key=${m.slot || i} m=${m} />`;
              })}</section>
            </div>

            <div className="mes-b4">
              <div className="mes-b4-row mes-b4-row-a">
                <div className="mes-panel">
                  <div className="mes-panel-h">Bag inventory · in stock</div>
                  <div className="mes-scroll">
                    <table className="mes-table">
                      <thead>
                        <tr><th>SKU</th><th>Bag ID</th><th>U</th><th>Qty</th><th>Sts</th></tr>
                      </thead>
                      <tbody>
                        ${(
                          inv.length
                            ? inv
                            : [{ sku: "—", bag_id: "—", units: "—", qty: "—", status: "—" }]
                        ).map(function (r, ii) {
                          return html`<tr key=${ii}
                            ><td>${r.sku}</td><td className="mes-num">${r.bag_id}</td
                            ><td>${r.units}</td><td>${r.qty}</td
                            ><td className="mes-inv-st">${r.status}</td></tr
                          >`;
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
                <div className="mes-panel">
                  <div className="mes-panel-h">Production trend · units</div>
                  <div className="mes-scroll" style=${{ overflow: "hidden" }}>
                    ${trend.series_valid === false
                      ? html`<div className="mes-muted" style=${{ fontSize: "10px", padding: "0.35rem" }}
                          >Insufficient data · no plotted production series yet today.</div
                        >`
                      : html`<${SvgLine} labels=${trend.labels} series=${{
                          Blister: trend.blister,
                          Bottle: trend.bottle,
                          Card: trend.card,
                        }} />`}
                  </div>
                </div>
                <div className="mes-panel">
                  <div className="mes-panel-h">Cycle analysis · avg</div>
                  <div className="mes-scroll" style=${{ overflow: "hidden" }}>
                    <${SvgBars} labels=${cyc.labels} today=${cyc.today} yesterday=${cyc.yesterday} />
                  </div>
                </div>
                <div className="mes-panel">
                  <div className="mes-panel-h">Top SKUs · today</div>
                  <div className="mes-scroll">
                    <table className="mes-table">
                      <thead><tr><th>SKU</th><th>Line</th><th>U</th><th>B</th><th>Cy</th></tr></thead>
                      <tbody>
                        ${(
                          skuT.length
                            ? skuT
                            : [{ sku: "—", line: "—", units: "—", bags: "—", cycles: "—" }]
                        ).map(function (r, ii) {
                          return html`<tr key=${ii}
                            ><td>${r.sku}</td><td>${r.line}</td><td>${r.units}</td><td>${r.bags}</td><td
                              >${r.cycles}</td
                            ></tr
                          >`;
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
                <div className="mes-panel" id="mes-anchor-staging">
                  <div className="mes-panel-h">Staging status</div>
                  <div className="mes-scroll">
                    <table className="mes-table">
                      <thead>
                        <tr><th>Line</th><th>Area</th><th>Bags</th><th>Oldest</th><th>T</th></tr>
                      </thead>
                      <tbody>
                        ${(
                          stg.length
                            ? stg
                            : [{ line: "—", area_name: "—", bags: "—", oldest_bag: "—", minutes: "—" }]
                        ).map(function (r, ii) {
                          return html`<tr key=${ii}
                            ><td>${r.line}</td><td>${r.area_name}</td><td>${r.bags}</td><td
                              >${r.oldest_bag}</td
                            ><td>${r.minutes}</td></tr
                          >`;
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
              <div className="mes-b4-row mes-b4-row-b">
                <div className="mes-panel">
                  <div className="mes-panel-h">Production timeline</div>
                  <div className="mes-scroll">
                    <table className="mes-table">
                      <thead>
                        <tr><th>T</th><th>Ln</th><th>Mc</th><th>Ev</th><th>Bag</th><th>SKU</th><th>Emp</th></tr>
                      </thead>
                      <tbody>
                        ${tl.map(function (r, ii) {
                          return html`<tr key=${ii} className=${r.alert ? "row-al" : ""}
                            ><td>${r.at_ms ? new Date(r.at_ms).toLocaleTimeString() : "—"}</td
                            ><td>${r.line}</td><td>${r.machine}</td><td>${r.event}</td><td>${r.bag_id}</td
                            ><td>${r.sku}</td><td>${r.employee}</td></tr
                          >`;
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
                <div className="mes-panel">
                  <div className="mes-panel-h">OEE · overall</div>
                  <${SvgDonut} oee=${oee} />
                </div>
                <div className="mes-panel">
                  <div className="mes-panel-h">Downtime · today</div>
                  <div className="mes-scroll">
                    ${down.length
                      ? html`<table className="mes-table">
                          <thead><tr><th>Line</th><th>Dt</th><th>Why</th><th>Imp</th></tr></thead>
                          <tbody>
                            ${down.map(function (r, ii) {
                              if (typeof r === "string" || typeof r === "number")
                                return html`<tr key=${ii}><td colspan="4" className="mes-muted">${String(r)}</td></tr>`;
                              return html`<tr key=${ii}
                                ><td>${r.line != null ? r.line : "—"}</td
                                ><td>${r.downtime != null ? r.downtime : r.minutes != null ? r.minutes : "—"}</td
                                ><td>${r.reason != null ? r.reason : "—"}</td
                                ><td>${r.impact != null ? r.impact : "—"}</td></tr
                              >`;
                            })}
                          </tbody>
                        </table>`
                      : html`<div className="mes-muted" style=${{ fontSize: "10px" }}>—</div>`}
                  </div>
                </div>
                <div className="mes-panel">
                  <div className="mes-panel-h">Team performance · today</div>
                  <div className="mes-scroll">
                    <table className="mes-table">
                      <thead><tr><th>Team</th><th>Ln</th><th>Cy</th><th>U</th></tr></thead>
                      <tbody>
                        ${team.map(function (r, ii) {
                          return html`<tr key=${ii}
                            ><td>${r.team}</td><td>${r.line}</td><td>${r.cycles}</td><td>${r.units}</td></tr
                          >`;
                        })}
                      </tbody>
                    </table>
                    ${team.length === 0
                      ? html`<div className="mes-muted" style=${{ fontSize: "10px", marginTop: "0.25rem" }}>—</div>`
                      : null}
                  </div>
                </div>
              </div>
              <div className="mes-pharma-wrap">
                <${MetricsNotesStrip} notes=${derived ? derived.notes : []} />
              </div>
              <div className="mes-b4-row mes-b4-row-d">
                <${BagGenealogyLive} metricInputs=${mes.metrics_inputs || {}} />
              </div>
            </div>
          </div>

          <footer className="mes-footer">
            <span>Live polling · refreshed automatically.</span>
            <span style=${{ display: "flex", alignItems: "center" }}
              ><span className="mes-pulse"></span> ${lastUp}</span
            >
          </footer>
        </div>
      </div>
    `;
  }

  function tickClock() {
    var el = document.getElementById("mes-clock");
    if (el)
      el.textContent = new Date().toLocaleString([], {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
  }

  tickClock();
  setInterval(tickClock, 1000);

  var rootEl = document.getElementById("mes-root");
  if (rootEl && window.React && window.ReactDOM) {
    var u = rootEl.getAttribute("data-snapshot-url") || "";
    window.ReactDOM.createRoot(rootEl).render(html`<${App} snapshotUrl=${u} />`);
  }
})();
