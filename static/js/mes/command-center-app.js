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
    { label: "Overview", href: "/command-center/ops-tv", icon: "◇" },
    { label: "Blister Line", href: "/command-center#blister", icon: "▭" },
    { label: "Bottle Line", href: "/command-center#bottle", icon: "▭" },
    { label: "Card Line", href: "/command-center#card", icon: "▭" },
    { label: "Machines", href: "/command-center", icon: "⚙" },
    { label: "Bags / Inventory", href: "/receiving", icon: "▣" },
    { label: "Staging", href: "/command-center#staging", icon: "▤" },
    { label: "Alerts", href: "/command-center/ops-tv#alerts", icon: "!" },
    { label: "Reports", href: "/reports", icon: "▦" },
    { label: "Analytics", href: "/reports", icon: "▧" },
    { label: "Users", href: "/admin/employees", icon: "◎" },
    { label: "Settings", href: "/admin/config", icon: "☰" },
  ];

  function readNavBoot() {
    try {
      var n = document.getElementById("mes-nav-boot");
      if (n && n.textContent) {
        var o = JSON.parse(n.textContent.trim());
        if (o && o.nav && o.nav.length) return o.nav;
      }
    } catch (e) {}
    return NAV_DEFAULT;
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
    if (rid === "bags" || rid === "units" || rid === "cycles")
      return row.value != null ? Number(row.value).toLocaleString() : "—";
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

  function FlowNode({ st }) {
    var sl = st.status_level || (st.alert === "crit" ? "crit" : st.alert === "warn" ? "warn" : "ok");
    var cp = st.congestion_pulse != null ? Number(st.congestion_pulse) : null;
    var cg =
      cp != null ? html`<div className="mes-fn-cong" style=${{ opacity: 0.12 + cp * 0.78 }} />` : null;
    return html`
      <div className=${"mes-fn mes-fn-" + sl + (cp != null ? " mes-fn-live" : "")}>
        ${cg}
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

  function twinVisualClass(light) {
    if (light === "run") return "mes-twin-svg mes-twin-svg--run";
    if (light === "wait") return "mes-twin-svg mes-twin-svg--wait";
    if (light === "fault") return "mes-twin-svg mes-twin-svg--fault";
    return "mes-twin-svg mes-twin-svg--idle";
  }

  function MachineTwinGraphic({ slot, light }) {
    var vc = twinVisualClass(light);
    var s = Number(slot || 1);
    if (s === 1) {
      return html`<svg className=${vc} viewBox="0 0 128 44" aria-hidden="true">
        <rect x="4" y="16" width="92" height="12" rx="1" fill="none" stroke="#38bdf8" stroke-width="0.9" />
        <circle className="mes-twin-roll" cx="22" cy="22" r="5" fill="none" stroke="#67e8f9" stroke-width="1" />
        <circle className="mes-twin-roll" cx="40" cy="22" r="5" fill="none" stroke="#67e8f9" stroke-width="1" />
        <path d="M 56 26 L118 26" stroke="#22d3ee" stroke-width="0.9" stroke-dasharray="3 2" />
        <text x="8" y="11" fill="#64748b" font-size="7" font-family="system-ui">DPP115 · blister form</text>
      </svg>`;
    }
    if (s === 2 || s === 3) {
      return html`<svg className=${vc} viewBox="0 0 128 44" aria-hidden="true">
        <rect x="18" y="10" width="92" height="18" rx="2" fill="none" stroke="#38bdf8" stroke-width="0.9" />
        <path d="M 28 28 L100 28" stroke="#fb923c" stroke-width="1.2" />
        <path d="M 64 10 L64 46" stroke="#22d3ee" stroke-width="0.75" opacity="0.65" />
        <text x="8" y="11" fill="#64748b" font-size="7" font-family="system-ui">${s === 2 ? "M2 seal" : "M3 seal"}</text>
      </svg>`;
    }
    if (s === 4) {
      return html`<svg className=${vc} viewBox="0 0 128 44" aria-hidden="true">
        <circle cx="64" cy="22" r="14" fill="none" stroke="#67e8f9" stroke-width="0.9" />
        <rect x="50" y="18" width="28" height="8" rx="1" fill="none" stroke="#a78bfa" stroke-width="0.85" />
        <path d="M 30 36 L98 36" stroke="#475569" stroke-width="0.8" opacity="0.7" />
        <text x="8" y="11" fill="#64748b" font-size="7" font-family="system-ui">Card / sticker</text>
      </svg>`;
    }
    return html`<svg className=${vc} viewBox="0 0 128 44" aria-hidden="true">
      <ellipse cx="64" cy="22" rx="28" ry="14" fill="none" stroke="#67e8f9" stroke-width="0.9" />
      <rect x="70" y="12" width="12" height="20" rx="1" fill="none" stroke="#94a3b8" stroke-width="0.8" />
      <text x="8" y="11" fill="#64748b" font-size="7" font-family="system-ui">Bottle seal</text>
    </svg>`;
  }

  function ScadaTwinCard({ m }) {
    var light = m.status_light || "idle";
    var dot =
      light === "run"
        ? "mes-scada-dot-run"
        : light === "wait"
          ? "mes-scada-dot-wait"
          : light === "fault"
            ? "mes-scada-dot-fault"
            : "mes-scada-dot-idle";
    var idle = m.raw_status === "idle";
    var stCls =
      m.status === "RUNNING" ? "mes-run" : m.status === "WAITING" ? "mes-wait" : "mes-idle";
    var slo = Number(m.slot || m.twin_slot || 1);
    var bag = m.bag_id != null ? String(m.bag_id) : "—";
    var ctr = m.counter_current != null ? String(m.counter_current) : "—";
    var th = m.throughput_uh != null ? Number(m.throughput_uh).toFixed(1) : "—";
    return html`
      <div className=${"mes-scada mes-scada-twin" + (idle ? " mes-scada-idle" : "")}>
        <div className="mes-twin-shell">
          <${MachineTwinGraphic} slot=${slo} light=${light} />
          <div className="mes-twin-overlay">
            <span className="mes-twin-beacon"><span className=${"mes-scada-dot sm " + dot}></span>${m.status}</span>
            <span className="mes-twin-ovl">Bag <strong>${bag}</strong></span>
            <span className="mes-twin-ovl">Tmr ${fmtTimerMs(m.timer_ms)}</span>
            <span className="mes-twin-ovl">Ctr ${ctr}</span>
            <span className="mes-twin-ovl">Out ${th} u/h</span>
          </div>
        </div>
        <div className="mes-scada-top mes-twin-caption">
          <span className={"mes-scada-dot md " + dot} title="status" />
          <div style=${{ minWidth: 0 }}>
            <div className="mes-scada-name">${m.short_label || m.canonical}</div>
            <div className="mes-scada-can">${m.label}</div>
          </div>
          <div className=${"mes-scada-st " + stCls}>${m.status}</div>
        </div>
        <div className="mes-scada-grid2">
          <span className="mes-muted">Timer</span><span className="mes-num rt">${fmtTimerMs(m.timer_ms)}</span>
          <span className="mes-muted">Bag</span><span className="mes-num rt">${bag}</span>
          <span className="mes-muted">Counter</span
          ><span className="mes-num rt">${ctr}</span>
          <span className="mes-muted">Thru · u/h</span
          ><span className="mes-num rt mes-c-util">${th}</span>
          <span className="mes-muted">Util%</span><span className="mes-num rt mes-c-util">${m.utilization_pct}%</span>
          <span className="mes-muted">OEE</span><span className="mes-num rt mes-c-oee">${m.oee_pct}%</span>
          <span className="mes-muted">Operator</span><span className="mes-ell rt">${m.operator || "—"}</span>
          <span className="mes-muted">Cycle</span
          ><span className="mes-num rt">${m.cycle_elapsed_min != null ? m.cycle_elapsed_min + "m" : "—"}</span>
          <span className="mes-muted">Scan</span
          ><span className="mes-num rt">${m.last_scan_ms ? new Date(m.last_scan_ms).toLocaleTimeString() : "—"}</span>
        </div>
      </div>
    `;
  }

  function BagGenealogyPanel({ geo }) {
    geo = geo || {};
    var steps = geo.steps || [];
    var hdr = geo.bag_id ? "Bag " + String(geo.bag_id) + " · " + (geo.sku || "") : "Bag trace · live";
    var ph = geo.bag_id ? String(geo.bag_id) : "";
    return html`<div className="mes-panel mes-gene">
      <div className="mes-panel-h">Genealogy · lot trace (${hdr})</div>
      <div className="mes-gene-trace">
        <span className="mes-muted">Trace any bag</span>
        <input className="mes-gene-inp" type="search" placeholder=${ph || "Bag id"} aria-label="Trace bag id" />
      </div>
      <div className="mes-gene-scroll">
        ${steps.length
          ? steps.map(function (st, ix) {
              var tm = st.at_ms ? new Date(st.at_ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—";
              var dw = st.dwell_from_prev_min != null ? st.dwell_from_prev_min + "m Δ" : "—";
              return html`<div key=${ix} className="mes-gene-row">
                <span className="mes-gene-dot">●</span>
                <span className="mes-gene-time">${tm}</span>
                <span className="mes-gene-main">
                  ${st.label} · ${st.station_label}
                  ${st.counter != null ? html`<span className="mes-gene-ctr"> ctr ${String(st.counter)}</span>` : null}
                  <span className="mes-gene-sub"> · ${st.operator || "?"} · dwell ${dw}</span>
                </span>
              </div>`;
            })
          : html`<div className="mes-muted" style=${{ fontSize: "10px", padding: "0.35rem" }}>No lineage rows yet.</div>`}
        <div className="mes-gene-foot">${geo.ebr_hint || ""}</div>
      </div>
    </div>`;
  }

  function BottleneckHeat({ hm }) {
    hm = hm || {};
    var zs = hm.stages || [];
    return html`<div className="mes-panel mes-hm">
      <div className="mes-panel-h">Constraint heatmap</div>
      <div className="mes-hm-grid">
        ${zs.map(function (z, ix) {
          var hx = Math.round((z.heat || 0) * 230);
          var bg = "rgba(" + hx + "," + Math.max(80, 210 - hx) + ",72,0.55)";
          var mk = z.is_constraint ? " mes-hm-cell--hot" : "";
          return html`<div
            key=${ix}
            title=${hm.hint || ""}
            style=${{ background: bg }}
            className=${"mes-hm-cell" + mk}
          >
            ${z.label}
          </div>`;
        })}
      </div>
    </div>`;
  }

  function QueueAgingHeat({ q }) {
    q = q || {};
    var zs = q.zones || [];
    var pal = q.palette || { ok: "#22c55e", warn: "#eab308", crit: "#ef4444" };
    return html`<div className="mes-panel mes-qage">
      <div className="mes-panel-h">Staging queue aging</div>
      <div className="mes-q-list">
        ${zs.map(function (z, ix) {
          var bg = pal[z.tier] || "#475569";
          var w = Math.round((z.heat || 0) * 100);
          var lab = [z.line, z.area].filter(Boolean).join(" · ") || "staging";
          return html`<div key=${ix} className="mes-q-row">
            <span>${lab}</span>
            <span className="mes-q-bar-wrap"
              ><span className="mes-q-bar" style=${{ width: w + "%", background: bg }}
                >${String(z.age_minutes)}m</span
              ></span
            >
          </div>`;
        })}
      </div>
    </div>`;
  }

  function PharmaIntelStrip({ phi }) {
    phi = phi || {};
    var f = phi.intel_footer || {};
    var qc = f.quality_reconcile || {};
    var sh = f.shift_eta || {};
    var eta = sh.predicted_finish_ms ? new Date(sh.predicted_finish_ms).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "—";
    var gu = typeof phi.gauge_util_pct === "number" ? phi.gauge_util_pct + "%" : "—";
    return html`<div className="mes-pharma-strip">
      <span
        ><strong>OEE</strong>
        ${typeof phi.oee_pct === "number"
          ? phi.oee_pct.toFixed(1)
          : "—"}% (${typeof phi.availability_pct === "number" ? phi.availability_pct.toFixed(0) : "?"} A ×
        ${typeof phi.performance_pct === "number" ? phi.performance_pct.toFixed(0) : "?"} P ×
        ${typeof phi.quality_pct === "number" ? phi.quality_pct.toFixed(1) : "?"} Q)</span
      >
      <span><strong>Thru</strong> ${typeof phi.throughput_units_hr === "number" ? phi.throughput_units_hr.toFixed(1) : "—"} u/h</span>
      <span
        ><strong>Takt / median cycle</strong>
        ${phi.takt_target_min != null ? phi.takt_target_min + "m tgt" : "—"}
        ${phi.median_cycle_claim_to_finish_min != null
          ? " · " + phi.median_cycle_claim_to_finish_min + "m observed"
          : ""}</span
      >
      <span
        ><strong>Yield</strong>
        ${qc.yield_pct != null
          ? qc.yield_pct.toFixed(2) + "%"
          : typeof phi.quality_pct === "number"
            ? phi.quality_pct.toFixed(2) + "%"
            : "—"}</span
      >
      <span><strong>Reject</strong> ~${qc.reject_approx_pct != null ? qc.reject_approx_pct.toFixed(2) + "%" : "?"}</span>
      <span><strong>Pred end</strong> ${eta}</span>
      <span><strong>Util tgt</strong> ${gu}</span>
      <span className="mes-pharma-ebr">${f.ebr_future || ""}</span>
    </div>`;
  }

  function AlarmPriorityBoard({ footer }) {
    footer = footer || {};
    var al = footer.alarm_priority || [];
    return html`<div className="mes-panel mes-alprio">
      <div className="mes-panel-h">Alarm priority board</div>
      <div className="mes-alprio-list">
        ${al.length
          ? al.map(function (a, i) {
              return html`<div key=${i} className=${"mes-alprio-row " + (a.sev === "warn" ? "mes-alprio-row--w" : "")}
                >${a.txt || ""}</div
              >`;
            })
          : html`<div className="mes-muted" style=${{ fontSize: "9px" }}>Flow nominal</div>`}
      </div>
    </div>`;
  }

  function UtilizationGaugePanel({ pct }) {
    var p = typeof pct === "number" ? Math.min(100, Math.max(0, pct)) : null;
    return html`<div className="mes-panel mes-ugauge">
      <div className="mes-panel-h">Fleet utilization gauge</div>
      <div className="mes-ug-track">${p != null ? html`<div className="mes-ug-fill" style=${{ width: p + "%" }} />` : null}<span className="mes-ug-lbl">${p != null ? p.toFixed(1) + "%" : "—"}</span></div>
    </div>`;
  }

  function QualityReconcileMini({ qc }) {
    qc = qc || {};
    return html`<div className="mes-panel mes-qcrec">
      <div className="mes-panel-h">Quality · yield reconcile</div>
      <div className="mes-qcrec-body">
        <div>
          <span className="mes-muted">Yield</span> <strong>${qc.yield_pct != null ? qc.yield_pct.toFixed(3) + "%" : "—"}</strong>
        </div>
        <div>
          <span className="mes-muted">Reject est.</span>
          ${qc.reject_approx_pct != null ? "~" + qc.reject_approx_pct.toFixed(2) + "%" : "—"}
        </div>
        ${qc.formula_text ? html`<div className="mes-qcrec-formula" title=${qc.formula_text}>${qc.formula_text}</div>` : null}
      </div>
    </div>`;
  }

  function ShiftEtaPanel({ eta, pharma }) {
    eta = eta || {};
    var fin = eta.predicted_finish_ms
      ? new Date(Number(eta.predicted_finish_ms)).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      : "—";
    var bk = pharma && pharma.bottleneck_station ? String(pharma.bottleneck_station) : "—";
    return html`<div className="mes-panel mes-shift-eta">
      <div className="mes-panel-h">Predicted shift completion</div>
      <div className="mes-shift-eta-val">${fin}</div>
      <div className="mes-shift-eta-sub mes-muted">${eta.method || ""}</div>
      <div className="mes-shift-eta-bot">Constraint · <strong>${bk}</strong></div>
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
    var parts = [
      { k: "Avail", v: o.availability || 0, c: "#22d3ee" },
      { k: "Perf", v: o.performance || 0, c: "#fb923c" },
      { k: "Qual", v: o.quality || 0, c: "#4ade80" },
    ];
    var tot = o.total || 0;
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
        <div style=${{ fontSize: "1.35rem", fontWeight: 900, color: "#e0f2fe" }}>
          ${tot.toFixed ? tot.toFixed(1) : tot}%
        </div>
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
          ${parts.map(function (p) {
            return html`<div key=${p.k} style=${{ display: "flex", justifyContent: "space-between" }}
              ><span style=${{ color: p.c }}>${p.k}</span><span>${p.v}%</span></div
            >`;
          })}
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

    var nav = useMemo(function () {
      return readNavBoot();
    }, []);

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
    var kpis = mes.kpis || [];
    var lanes = mes.lanes || [];
    var alerts = mes.alerts || (snap && snap.activity) || [];
    var scada = mes.scada_machines || [];
    var trend = mes.trend || {};
    var cyc = mes.cycle_analysis || {};
    var oee = mes.oee_donut || {};
    var inv = mes.inventory || [];
    var skuT = mes.sku_table || [];
    var stg = mes.staging || [];
    var tl = mes.timeline || [];
    var team = mes.team || [];
    var down = mes.downtime || [];
    var pharma = mes.pharma_intel || {};
    var intelAl = [];
    try {
      var ap = pharma.intel_footer && pharma.intel_footer.alarm_priority;
      if (ap && ap.length)
        intelAl = ap.map(function (a) {
          return {
            at_ms: a.until_ms,
            severity: a.sev === "warn" ? "warn" : "info",
            message: (a.txt || "").trim(),
          };
        });
    } catch (e2) {}
    var mergedAlerts = intelAl.concat(Array.isArray(alerts) ? alerts : []);
    var accents = ["#22d3ee", "#4ade80", "#fbbf24", "#a78bfa", "#f472b6", "#38bdf8", "#94a3b8"];
    var genAt = mes.generated_at_ms != null ? mes.generated_at_ms : snap != null ? snap.generated_at_ms : null;
    var lastUp = fmtSnapTime(genAt) || (snap ? new Date().toLocaleTimeString() : "—");

    return html`
      <div className="mes-app" data-wall-tick=${tick}>
        <aside className="mes-aside">
          ${nav.map(function (item, i) {
            var active = item.href.indexOf("ops-tv") >= 0;
            return html`<a
              key=${item.label + String(i)}
              href=${item.href}
              className=${"mes-nav-a" + (active ? " mes-active" : "")}
              ><span className="mes-nav-ic">${item.icon}</span>${item.label}</a
            >`;
          })}
        </aside>
        <div className="mes-main">
          ${err ? html`<div className="mes-banner-err">${err}</div>` : null}
          <header className="mes-header">
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
                <section className="mes-process-map" aria-label="Production map">
                  <div className="mes-pm-h">Production control map</div>
                  ${lanes.map(function (lane, i) {
                    return html`<${FlowLaneRow} key=${lane.id || i} lane=${lane} />`;
                  })}
                </section>
                <${AlertsRail} items=${mergedAlerts} />
              </div>
            </div>

            <div className="mes-b3">
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
                    <${SvgLine} labels=${trend.labels} series=${{
                      Blister: trend.blister,
                      Bottle: trend.bottle,
                      Card: trend.card,
                    }} />
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
                <div className="mes-panel">
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
                <${PharmaIntelStrip} phi=${pharma} />
              </div>
              <div className="mes-b4-row mes-b4-row-d">
                <${BagGenealogyPanel} geo=${pharma.genealogy || {}} />
                <${BottleneckHeat} hm=${pharma.bottleneck_heatmap || {}} />
                <${QueueAgingHeat} q=${pharma.queue_aging_map || {}} />
                <div className="mes-b4-mini-col">
                  <${AlarmPriorityBoard} footer=${pharma.intel_footer || {}} />
                  <${UtilizationGaugePanel} pct=${pharma.gauge_util_pct} />
                  <${QualityReconcileMini} qc=${(pharma.intel_footer || {}).quality_reconcile || {}} />
                  <${ShiftEtaPanel} eta=${(pharma.intel_footer || {}).shift_eta} pharma=${pharma} />
                </div>
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
