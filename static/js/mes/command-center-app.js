/**
 * MES Command Center — React + htm (ES modules, no bundle).
 * Styled with static/css/mes-command-center.css. Data: snapshot JSON `.mes`.
 */
import React, { useEffect, useState } from "https://esm.sh/react@18.2.0";
import { createRoot } from "https://esm.sh/react-dom@18.2.0/client";
import htm from "https://esm.sh/htm@3.1.1";

const html = htm.bind(React.createElement);

const NAV_DEFAULT = [
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
  const w = 132;
  const h = 32;
  const mn = Math.min.apply(null, vals);
  const mx = Math.max.apply(null, vals);
  const rg = mx - mn || 1;
  const pts = vals
    .map(function (v, i) {
      const x = (i / (vals.length - 1)) * (w - 4) + 2;
      const y = h - 2 - ((v - mn) / rg) * (h - 8);
      return x.toFixed(1) + "," + y.toFixed(1);
    })
    .join(" ");
  const fillPts = "0," + h + " " + pts + " " + w + "," + h;
  return html`
    <svg className="mes-spark" width=${w} height=${h} viewBox=${"0 0 " + w + " " + h} aria-hidden="true">
      <polygon fill=${stroke + "22"} stroke="none" points=${fillPts} />
      <polyline fill="none" stroke=${stroke} stroke-width="1.5" points=${pts} />
    </svg>
  `;
}

function fmtKpiVal(row) {
  if (row.id === "bags" || row.id === "units" || row.id === "cycles")
    return (row.value != null ? Number(row.value).toLocaleString() : "—");
  if (row.id === "avg_cycle") return row.value != null ? String(row.value) : "—";
  if (row.id === "on_time" || row.id === "rework" || row.id === "oee") {
    if (row.value_pct == null && row.value == null) return "—";
    const n = row.value_pct != null ? row.value_pct : row.value;
    return typeof n === "number" ? n.toFixed(row.id === "rework" ? 2 : 1) + "%" : String(n);
  }
  return "—";
}

function DeltaLine({ row }) {
  let t = "";
  if (row.delta_pct != null) t = (row.delta_pct >= 0 ? "↑ " : "↓ ") + Math.abs(row.delta_pct).toFixed(1) + "%";
  else if (row.delta_min != null) t = "Δ " + row.delta_min + "m cycle";
  if (row.subtitle) t += (t ? " · " : "") + row.subtitle;
  const pos = row.delta_pct != null ? row.delta_pct >= 0 : (row.delta_min != null ? row.delta_min <= 0 : true);
  return html`<div className=${"mes-kpi-delta " + (pos ? "mes-pos" : "mes-neg")}>${t}</div>`;
}

function KpiCard({ row, accent }) {
  return html`
    <div className="mes-kpi-card">
      <div className="mes-kpi-title">${row.label}</div>
      <div className="mes-kpi-val">${fmtKpiVal(row)}</div>
      <${Sparkline} vals=${row.sparkline || []} stroke=${accent} />
      <${DeltaLine} row=${row} />
    </div>
  `;
}

function StageBlock({ st }) {
  const ex = st.alert === "crit" ? " mes-stage-crit" : st.alert === "warn" ? " mes-stage-warn" : "";
  return html`
    <div className=${"mes-stage" + ex}>
      <div className="mes-stage-h">${st.title}</div>
      <div className="mes-stage-r">
        <span>WIP ${st.wip != null ? st.wip : "—"}</span>
        <span>Bags ${st.bags != null ? st.bags : "—"}</span>
      </div>
      ${st.dwell ? html`<div className="mes-stage-d">${st.dwell}</div>` : null}
      ${st.alert_note ? html`<div className="mes-stage-note">${st.alert_note}</div>` : null}
    </div>
  `;
}

function LaneCol({ lane }) {
  const stages = lane.stages || [];
  return html`
    <div className="mes-lane">
      <div className="mes-lane-title">${lane.title}</div>
      <div className="mes-lane-sku">SKU: <strong>${lane.sku || "—"}</strong></div>
      <div className="mes-stage-wrap">
        ${stages.map(function (st, idx) {
          return html`<div key=${st.key || idx}>
            <${StageBlock} st=${st} />
            ${idx < stages.length - 1 ? html`<div className="mes-arrow">↓</div>` : null}
          </div>`;
        })}
      </div>
    </div>
  `;
}

function AlertsPanel({ items }) {
  const rank = { alert: 0, warn: 1, info: 2 };
  var xs = (items || []).slice().sort(function (a, b) {
    return (rank[a.severity] ?? 2) - (rank[b.severity] ?? 2);
  });
  xs = xs.slice(0, 14);
  return html`
    <div className="mes-alerts" id="mes-alerts">
      <div className="mes-alerts-h">Active Alerts</div>
      <div className="mes-alert-list">
        ${xs.length
          ? xs.map(function (a, i) {
              const mod = a.severity === "alert" ? " mes-alert-a" : a.severity === "warn" ? " mes-alert-w" : "";
              return html`<div key=${i} className=${"mes-alert" + mod}>
                  <span className="mes-num mes-muted"
                    >${new Date(a.at_ms).toLocaleTimeString([], {
                      hour: "numeric",
                      minute: "2-digit",
                    })}</span
                  >
                  · ${a.message || ""}
                  ${a.severity
                    ? html`<span className="mes-muted" style=${{ fontWeight: 800 }}> ${String(a.severity).toUpperCase()}</span>`
                    : null}
                </div>`;
            })
          : html`<div className="mes-muted" style=${{ fontSize: "11px" }}>No active alerts.</div>`}
      </div>
    </div>
  `;
}

function fmtTimerMs(startMs) {
  if (startMs == null) return "—";
  var s = Math.max(0, Math.floor((Date.now() - Number(startMs)) / 1000));
  var mm = Math.floor(s / 60);
  var sec = s % 60;
  return mm + ":" + (sec < 10 ? "0" : "") + sec;
}

function ScadaCard({ m }) {
  const idle = m.raw_status === "idle";
  const stCls = m.status === "RUNNING" ? "mes-run" : m.status === "WAITING" ? "mes-wait" : "mes-idle";
  const grid = html`
      <div className="mes-scada-grid2">
        <span className="mes-muted">Bag</span><span className="mes-num rt">${m.bag_id != null ? m.bag_id : "—"}</span>
        <span className="mes-muted">SKU</span><span className="mes-ell rt">${m.sku || "—"}</span>
        <span className="mes-muted">Operator</span><span className="rt">${m.operator || "—"}</span>
        <span className="mes-muted">Timer run</span><span className="mes-num rt">${fmtTimerMs(m.timer_ms)}</span>
        <span className="mes-muted">Ctr start</span><span className="mes-num rt">${m.counter_start != null ? m.counter_start : "—"}</span>
        <span className="mes-muted">Ctr curr</span><span className="mes-num rt">${m.counter_current != null ? m.counter_current : "—"}</span>
        <span className="mes-muted">Ctr end</span><span className="mes-num rt">${m.counter_end != null ? m.counter_end : "—"}</span>
        <span className="mes-muted">Units prod</span>
        <span className="mes-num rt">${m.units_produced != null ? m.units_produced : "—"}</span>
        <span className="mes-muted">Cycle elapsed</span>
        <span className="mes-num rt">${m.cycle_elapsed_min != null ? m.cycle_elapsed_min + "m" : "—"}</span>
        <span className="mes-muted">Utilization</span><span className="rt mes-c-util">${m.utilization_pct}%</span>
        <span className="mes-muted">OEE</span><span className="rt mes-c-oee">${m.oee_pct}%</span>
        <span className="mes-muted">Last scan</span>
        <span className="mes-num rt mes-ts">${m.last_scan_ms ? new Date(m.last_scan_ms).toLocaleTimeString() : "—"}</span>
      </div>
    `;
  return html`
    <div className=${"mes-scada" + (idle ? " mes-scada-idle" : "")}>
      <div className="mes-scada-name">${m.label}</div>
      <div className="mes-scada-can">${m.canonical}</div>
      <div className=${"mes-scada-st " + stCls}>${m.status}</div>
      ${grid}
    </div>
  `;
}

function SvgLine({ labels, series }) {
  const W = 400;
  const H = 120;
  const keys = Object.keys(series || {});
  if (!keys.length) return html`<div className="mes-muted" style=${{ fontSize: "11px", padding: "0.5rem" }}>No trend data</div>`;
  const all = keys.flatMap((k) => series[k] || []);
  const mx = Math.max.apply(null, all.concat([1]));
  const palette = ["#22d3ee", "#4ade80", "#a78bfa"];
  return html`
    <svg style=${{ width: "100%", height: "auto" }} viewBox=${"0 0 " + W + " " + H} role="img">
      ${keys.map(function (k, ki) {
        const pts = (series[k] || []).map(function (v, i) {
          const x = (i / Math.max(1, (labels || []).length - 1)) * (W - 20) + 10;
          const y = H - 10 - (v / mx) * (H - 20);
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
      ${keys.map(
        (k, ki) =>
          html`<span key=${k}><span style=${{ color: palette[ki % palette.length] }}>■</span> ${k}</span>`
      )}
    </div>
  `;
}

function SvgBars({ labels, today, yesterday }) {
  const W = 400;
  const H = 120;
  const n = Math.max((labels || []).length, 1);
  const all = (today || []).concat(yesterday || []);
  const mx = Math.max.apply(null, all.concat([1]));
  const bw = (W - 40) / n / 2.2;
  return html`
    <svg style=${{ width: "100%", height: "auto" }} viewBox=${"0 0 " + W + " " + H}>
      ${(labels || []).map(function (lab, i) {
        const x0 = 20 + (i * (W - 40)) / n;
        const h1 = ((today[i] || 0) / mx) * (H - 30);
        const h2 = ((yesterday[i] || 0) / mx) * (H - 30);
        return html`<g key=${lab}>
          <rect x=${x0} y=${H - 10 - h1} width=${bw} height=${h1} fill="#22d3ee" opacity="0.85" />
          <rect x=${x0 + bw + 2} y=${H - 10 - h2} width=${bw} height=${h2} fill="#64748b" opacity="0.75" />
        </g>`;
      })}
    </svg>
  `;
}

function SvgDonut({ oee }) {
  const o = oee || {};
  const parts = [
    { k: "Availability", v: o.availability || 0, c: "#22d3ee" },
    { k: "Performance", v: o.performance || 0, c: "#fb923c" },
    { k: "Quality", v: o.quality || 0, c: "#4ade80" },
  ];
  const tot = o.total || 0;
  return html`
    <div style=${{ display: "flex", flexDirection: "column", alignItems: "center", padding: "0.5rem" }}>
      <div style=${{ fontSize: "1.75rem", fontWeight: 900, color: "#e0f2fe" }}>${tot.toFixed ? tot.toFixed(1) : tot}%</div>
      <div className="mes-muted" style=${{ fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.12em", marginTop: "0.25rem" }}>OEE</div>
      <div style=${{ marginTop: "0.6rem", width: "100%", fontSize: "10px", display: "flex", flexDirection: "column", gap: "0.25rem" }}>
        ${parts.map(
          (p) =>
            html`<div key=${p.k} style=${{ display: "flex", justifyContent: "space-between" }}
              ><span style=${{ color: p.c }}>${p.k}</span
              ><span>${p.v}%</span></div
            >`
        )}
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
  const [snap, setSnap] = useState(null);
  const [err, setErr] = useState(null);
  const [tick, setTick] = useState(0);
  const nav = React.useMemo(function () {
    return readNavBoot();
  }, []);
  const load = function () {
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
  };
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

  const mes = (snap && snap.mes) || {};
  const kpis = mes.kpis || [];
  const lanes = mes.lanes || [];
  const alerts = mes.alerts || (snap && snap.activity) || [];
  const scada = mes.scada_machines || [];
  const trend = mes.trend || {};
  const cyc = mes.cycle_analysis || {};
  const oee = mes.oee_donut || {};
  const inv = mes.inventory || [];
  const skuT = mes.sku_table || [];
  const stg = mes.staging || [];
  const tl = mes.timeline || [];
  const team = mes.team || [];
  const down = mes.downtime || [];
  const accents = ["#22d3ee", "#4ade80", "#fbbf24", "#a78bfa", "#f472b6", "#38bdf8", "#94a3b8"];
  const genAt =
    mes.generated_at_ms != null ? mes.generated_at_ms : snap != null ? snap.generated_at_ms : null;
  const lastUp = fmtSnapTime(genAt) || (snap ? new Date().toLocaleTimeString() : "—");

  return html`
    <div className="mes-app" data-wall-tick=${tick}>
      <aside className="mes-aside">
        ${nav.map(function (item, i) {
          const active = item.href.indexOf("ops-tv") >= 0;
          return html`<a
            key=${item.label + i}
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
            <span id="mes-clock" className="mes-clock" />
            <select className="mes-select" aria-label="Production line"><option>All Lines</option></select>
            <select className="mes-select" aria-label="SKU filter"><option>All SKUs</option></select>
          </div>
        </header>

        <section className="mes-kpi-grid" aria-label="Production KPI">
          ${kpis.map(function (row, idx) {
            return html`<${KpiCard} key=${row.id || idx} row=${row} accent=${accents[idx % accents.length]} />`;
          })}
        </section>

        <section className="mes-band">
          <div className="mes-lanes">${lanes.map((l, i) => html`<${LaneCol} key=${l.id || i} lane=${l} />`)}</div>
          <${AlertsPanel} items=${alerts} />
        </section>

        <div className="mes-scada-head">Machine status · SCADA</div>
        <section className="mes-scada-grid" aria-label="Machine tiles">${scada.map((m, i) => html`<${ScadaCard} key=${m.slot || i} m=${m} />`)}</section>

        <section className="mes-grid-r1" aria-label="Analytics row one">
          <div className="mes-panel">
            <div className="mes-panel-h">Bag inventory · in stock</div>
            <div className="mes-scroll">
              <table className="mes-table">
                <thead
                  ><tr><th>SKU</th><th>Bag ID</th><th>Units</th><th>Qty</th><th>Status</th></tr></thead
                >
                <tbody>
                  ${(inv.length ? inv : [{ sku: "—", bag_id: "—", units: "—", qty: "—", status: "—" }]).map(
                    function (r, i) {
                      return html`<tr key=${i}
                        ><td>${r.sku}</td><td className="mes-num">${r.bag_id}</td
                        ><td>${r.units}</td><td>${r.qty}</td
                        ><td className="mes-inv-st">${r.status}</td></tr
                      >`;
                    }
                  )}
                </tbody>
              </table>
            </div>
          </div>
          <div className="mes-panel mes-r1-trend">
            <div className="mes-panel-h">Production trend · units</div>
            <${SvgLine} labels=${trend.labels} series=${{ Blister: trend.blister, Bottle: trend.bottle, Card: trend.card }} />
          </div>
          <div className="mes-panel">
            <div className="mes-panel-h">Cycle time analysis · avg</div>
            <${SvgBars} labels=${cyc.labels} today=${cyc.today} yesterday=${cyc.yesterday} />
            <div className="mes-legend"><span style=${{ color: "#22d3ee" }}>■</span> Today <span style=${{ color: "#64748b" }}>■</span> Yesterday</div>
          </div>
          <div className="mes-panel">
            <div className="mes-panel-h">Top SKUs · today</div>
            <div className="mes-scroll">
              <table className="mes-table">
                <thead><tr><th>SKU</th><th>Line</th><th>Units</th><th>Bags</th><th>Cycles</th></tr></thead>
                <tbody>
                  ${(skuT.length ? skuT : [{ sku: "—", line: "—", units: "—", bags: "—", cycles: "—" }]).map(function (r, i) {
                    return html`<tr key=${i}
                      ><td>${r.sku}</td><td>${r.line}</td><td>${r.units}</td><td>${r.bags}</td><td>${r.cycles}</td></tr
                    >`;
                  })}
                </tbody>
              </table>
            </div>
          </div>
          <div className="mes-panel">
            <div className="mes-panel-h">Staging area status</div>
            <div className="mes-scroll">
              <table className="mes-table">
                <thead><tr><th>Line</th><th>Staging</th><th>Bags</th><th>Oldest</th><th>Time</th></tr></thead>
                <tbody>
                  ${(stg.length ? stg : [{ line: "—", area_name: "—", bags: "—", oldest_bag: "—", minutes: "—" }]).map(function (r, i) {
                    return html`<tr key=${i}
                      ><td>${r.line}</td><td>${r.area_name}</td><td>${r.bags}</td><td>${r.oldest_bag}</td><td>${r.minutes}</td></tr
                    >`;
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="mes-grid2" aria-label="Analytics row two">
          <div className="mes-panel">
            <div className="mes-panel-h">Production timeline · event feed</div>
            <div className="mes-scroll" style=${{ maxHeight: "220px" }}>
              <table className="mes-table">
                <thead><tr><th>Time</th><th>Line</th><th>Machine</th><th>Event</th><th>Bag</th><th>SKU</th><th>Employee</th></tr></thead>
                <tbody>
                  ${(tl.length ? tl : []).map(function (r, i) {
                    return html`<tr key=${i} className=${r.alert ? "row-al" : ""}
                      ><td>${r.at_ms ? new Date(r.at_ms).toLocaleTimeString() : "—"}</td
                      ><td>${r.line}</td><td>${r.machine}</td><td>${r.event}</td><td>${r.bag_id}</td><td>${r.sku}</td><td>${r.employee}</td></tr
                    >`;
                  })}
                </tbody>
              </table>
            </div>
          </div>
          <div className="mes-panel">
            <div className="mes-panel-h">OEE breakdown · overall</div>
            <${SvgDonut} oee=${oee} />
          </div>
          <div className="mes-panel">
            <div className="mes-panel-h">Downtime summary · today</div>
            <div className="mes-scroll" style=${{ maxHeight: "180px" }}>
              ${
                down.length
                  ? html`<table className="mes-table">
                      <thead><tr><th>Line</th><th>Downtime</th><th>Reason</th><th>Impact</th></tr></thead>
                      <tbody>
                        ${down.map(function (r, i) {
                          if (typeof r === "string" || typeof r === "number")
                            return html`<tr key=${i}><td colspan="4" className="mes-muted">${String(r)}</td></tr>`;
                          return html`<tr key=${i}
                            ><td>${r.line != null ? r.line : "—"}</td><td>${r.downtime != null ? r.downtime : r.minutes != null ? r.minutes : "—"}</td
                            ><td>${r.reason != null ? r.reason : "—"}</td><td>${r.impact != null ? r.impact : "—"}</td></tr
                          >`;
                        })}
                      </tbody>
                    </table>`
                  : html`<div className="mes-muted" style=${{ fontSize: "11px" }}>No downtime recorded.</div>`
              }
            </div>
          </div>
          <div className="mes-panel">
            <div className="mes-panel-h">Team performance · today</div>
            <div className="mes-scroll" style=${{ maxHeight: "180px" }}>
              <table className="mes-table">
                <thead><tr><th>Team</th><th>Line</th><th>Cycles</th><th>Units</th></tr></thead>
                <tbody>
                  ${team.map(function (r, i) {
                    return html`<tr key=${i}><td>${r.team}</td><td>${r.line}</td><td>${r.cycles}</td><td>${r.units}</td></tr>`;
                  })}
                </tbody>
              </table>
              ${team.length === 0 ? html`<div className="mes-muted" style=${{ fontSize: "11px", marginTop: "0.5rem" }}>No team rows.</div>` : null}
            </div>
          </div>
        </section>

        <footer className="mes-footer">
          <span>All data is real-time and updates automatically.</span>
          <span style=${{ display: "flex", alignItems: "center", gap: "0.35rem" }}
            ><span className="mes-pulse" aria-hidden="true"></span> Last updated ·
            <span className="mes-num" style=${{ color: "#cbd5e1" }}>${lastUp}</span></span
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
if (rootEl) {
  var u = rootEl.getAttribute("data-snapshot-url") || "";
  createRoot(rootEl).render(html`<${App} snapshotUrl=${u} />`);
}
