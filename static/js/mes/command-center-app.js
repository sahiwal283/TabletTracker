(function () {
  var React = window.React;
  var ReactDOM = window.ReactDOM;
  var htmVendor = window.htm;
  if (!React || !ReactDOM || !htmVendor) return;

  var html = htmVendor.bind(React.createElement);
  var useEffect = React.useEffect;
  var useMemo = React.useMemo;
  var useState = React.useState;
  var FALLBACK_NAV_ITEMS = [
    { label: "Overview", tab: "overview" },
    { label: "Blister / Card Line", tab: "blister" },
    { label: "Bottle Line", tab: "bottle" },
    { label: "Machines", tab: "machines" },
    { label: "Bags / Inventory", tab: "bags" },
    { label: "Staging", tab: "staging" },
    { label: "Alerts", tab: "alerts" },
    { label: "Analytics", tab: "analytics" },
    { label: "Team", tab: "team" },
    { label: "Materials", tab: "materials" },
  ];

  function readBoot() {
    try {
      var n = document.getElementById("mes-nav-boot");
      return JSON.parse((n && n.textContent) || "{}");
    } catch (e) {
      return {};
    }
  }

  function readCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    var token = meta && meta.getAttribute("content");
    return token ? String(token).trim() : "";
  }

  function readInitialTab(navItems) {
    var allowed = {};
    (navItems || []).forEach(function (item) {
      var t = String(item.tab || "").toLowerCase();
      if (t) allowed[t] = 1;
    });
    var h = String(window.location.hash || "").replace(/^#/, "").toLowerCase();
    if (h === "card") h = "blister";
    if (h && allowed[h]) return h;
    return (navItems && navItems[0] && String(navItems[0].tab || "").toLowerCase()) || "overview";
  }

  function normalizeMesNav(items) {
    var out = [];
    var hasMerged = false;
    (items || []).forEach(function (item) {
      var tab = String(item && item.tab || "").toLowerCase();
      if (!tab) return;
      if (tab === "blister" || tab === "card") {
        if (!hasMerged) {
          out.push({ label: "Blister / Card Line", tab: "blister" });
          hasMerged = true;
        }
        return;
      }
      out.push(item);
    });
    return out.length ? out : FALLBACK_NAV_ITEMS;
  }

  function asNum(v) {
    var n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function fmtNumber(v) {
    var n = asNum(v);
    return n == null ? "N/A" : n.toLocaleString();
  }

  function fmtPct(v) {
    var n = asNum(v);
    return n == null ? "Insufficient data" : n.toFixed(1) + "%";
  }

  function pctVsRef(current, ref) {
    var c = asNum(current);
    var r = asNum(ref);
    if (c == null || r == null || r <= 0) return null;
    return (100.0 * (c - r)) / r;
  }

  function fmtVsRef(current, ref, refLabel) {
    var p = pctVsRef(current, ref);
    if (p == null) return "—";
    var adj = refLabel ? " vs " + refLabel : "";
    return (p >= 0 ? "+" : "") + p.toFixed(0) + "%" + adj;
  }

  function fmtTime(ms, seconds) {
    var n = asNum(ms);
    if (n == null) return "N/A";
    return new Date(n).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: seconds ? "2-digit" : undefined });
  }

  function fmtDate(ms) {
    var d = ms ? new Date(ms) : new Date();
    return d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
  }

  function timeInputValue(ms) {
    var n = asNum(ms);
    if (n == null) return "";
    var d = new Date(n);
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }

  function todayIsoDate() {
    var d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 10);
  }

  function elapsedSince(ms) {
    var n = asNum(ms);
    var ref = asNum(arguments.length > 2 ? arguments[2] : null) || Date.now();
    if (n == null) return "N/A";
    var total = Math.max(0, Math.floor((ref - n) / 1000));
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    return h > 0 ? h + "h " + String(m).padStart(2, "0") + "m" : m + "m";
  }

  function durationClock(ms) {
    var n = asNum(ms);
    if (n == null) return "N/A";
    var total = Math.max(0, Math.floor((Date.now() - n) / 1000));
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    return h + "h " + String(m).padStart(2, "0") + "m";
  }

  function eventType(e) {
    return String((e && e.eventType) || "").toUpperCase();
  }

  function eventAt(e) {
    return asNum(e && (e.atMs != null ? e.atMs : e.at_ms));
  }

  function eventBagId(e) {
    return asNum(e && (e.bagId != null ? e.bagId : e.workflowBagId));
  }

  function eventMachineId(e) {
    return asNum(e && (e.stationId != null ? e.stationId : e.machineId));
  }

  function isFinalPackagingSnapshot(e) {
    return eventType(e) === "PACKAGING_SNAPSHOT" && String((e && e.reason) || "").toLowerCase() === "final_submit";
  }

  function eventDisplayCount(e) {
    var n = asNum(e && (e.displayCount != null ? e.displayCount : e.countTotal));
    return n != null && n >= 0 ? n : null;
  }

  function eventDamagedCards(e) {
    var n = asNum(e && (e.cardsReopened != null ? e.cardsReopened : e.cards_reopened));
    return n != null && n >= 0 ? n : null;
  }

  function statusText(status) {
    if (status === "LIVE_QR") return "RUNNING";
    if (status === "LIVE_PAUSED") return "PAUSED";
    if (status === "NO_ACTIVITY_TODAY") return "IDLE";
    if (status === "NOT_INTEGRATED") return "NOT INTEGRATED";
    return String(status || "N/A").toUpperCase();
  }

  function statusTone(status) {
    if (status === "LIVE_QR") return "run";
    if (status === "LIVE_PAUSED") return "idle";
    if (status === "NO_ACTIVITY_TODAY") return "idle";
    if (status === "NOT_INTEGRATED") return "off";
    return "idle";
  }

  /** Prefer workflow occupancy from server over event-only integration guess. */
  function resolveIntegrationBadge(liveRow, stationId, events, cfg) {
    var live = String((liveRow && liveRow.status) || "").toLowerCase();
    var base = window.OpsMetrics.getMachineIntegrationStatus(stationId, events, cfg);
    if (!live) return base;
    if (live === "paused") return "LIVE_PAUSED";
    if (live === "running") return "LIVE_QR";
    if (live === "idle") return "NO_ACTIVITY_TODAY";
    return base;
  }

  function liveElapsedMinutes(ms, nowMs) {
    var n = asNum(ms);
    var ref = asNum(nowMs) || Date.now();
    return n == null ? null : Math.max(0, (ref - n) / 60000);
  }

  function stationAverageFor(machine, shiftConfig) {
    var avgs = (shiftConfig && shiftConfig.stationCycleAvgMinutes) || {};
    var row = machine && machine.stationId != null ? avgs[String(machine.stationId)] : null;
    var avg = asNum(row && row.avgMinutes);
    var samples = asNum(row && row.sampleCount);
    return avg != null && samples != null && samples >= 2 ? { avgMinutes: avg, sampleCount: samples } : null;
  }

  function overAverage(machine, shiftConfig, nowMs) {
    if (!machine || machine.integrationStatus === "LIVE_PAUSED") return false;
    if (String(machine.occupancyStatus || "").toLowerCase() === "paused") return false;
    if (machine.integrationStatus !== "LIVE_QR" || machine.workflowBagId == null) return false;
    var avg = stationAverageFor(machine, shiftConfig);
    var elapsed = liveElapsedMinutes(machine.occupancyStartedAtMs || machine.lastScanMs, nowMs);
    return !!(avg && elapsed != null && elapsed > avg.avgMinutes);
  }

  function latestByMachine(events, stationId) {
    var sid = asNum(stationId);
    if (sid == null) return null;
    return (events || []).filter(function (e) { return eventMachineId(e) === sid; }).sort(function (a, b) {
      return (eventAt(b) || 0) - (eventAt(a) || 0);
    })[0] || null;
  }

  function completedCounterEvent(events, stationId) {
    var sid = asNum(stationId);
    if (sid == null) return null;
    return (events || []).filter(function (e) {
      var t = eventType(e);
      return eventMachineId(e) === sid && (t === "BLISTER_COMPLETE" || t === "SEALING_COMPLETE" || t === "PACKAGING_SNAPSHOT" || t === "BAG_FINALIZED");
    }).sort(function (a, b) {
      return (eventAt(b) || 0) - (eventAt(a) || 0);
    })[0] || null;
  }

  function unitsTodayLabelForMachine(m) {
    var stationKind = String(m && m.stationKind || "").toLowerCase();
    var role = String(m && m.machineRole || "").toLowerCase();
    var kind = String(m && m.kind || "").toLowerCase();
    if (stationKind === "blister" || role === "blister" || kind === "blister") return "Blisters Today";
    if (stationKind === "sealing" || role === "sealing" || kind === "heat") return "Cards Today";
    if (stationKind === "packaging" || role === "packaging" || kind === "pack") return "Displays Today";
    if (role === "bottle" || kind === "bottle" || role === "stickering" || kind === "sticker") return "Bottles Today";
    return "Units Today";
  }

  function machineIcon(kind, status) {
    var tone = statusTone(status);
    var body;
    if (kind === "blister") {
      body = html`<g><rect x="12" y="22" width="30" height="43" rx="4" /><circle cx="20" cy="31" r="3" /><circle cx="32" cy="31" r="3" /><circle cx="20" cy="44" r="3" /><circle cx="32" cy="44" r="3" /><circle cx="20" cy="57" r="3" /><circle cx="32" cy="57" r="3" /></g>`;
    } else if (kind === "heat") {
      body = html`<g><rect x="8" y="26" width="56" height="11" rx="2" /><rect x="4" y="54" width="64" height="11" rx="2" /><path d="M13 37v17M59 37v17M27 42l8 8 8-8" /></g>`;
    } else if (kind === "sticker") {
      body = html`<g><path d="M30 18h13v15h-4v38H26V33h-4V18z" /><path d="M18 71h32" /></g>`;
    } else if (kind === "bag") {
      body = html`<g><path d="M20 24h30l6 47H14z" /><path d="M25 24c0-12 20-12 20 0" /></g>`;
    } else if (kind === "pack") {
      body = html`<g><rect x="14" y="28" width="44" height="34" rx="3" /><path d="M14 39h44M24 28v34M48 28v34" /><path d="M22 22h28" /></g>`;
    } else if (kind === "bottle") {
      body = html`<g><path d="M25 69h21l4-30h-8V23H29v16h-8z" /><path d="M24 51h24" /></g>`;
    } else {
      body = html`<g><circle cx="36" cy="36" r="24" /><path d="M36 16v20l14 9" /></g>`;
    }
    return html`<svg className=${"line-icon " + tone} viewBox="0 0 72 82" aria-hidden="true">${body}</svg>`;
  }

  function miniIcon(type) {
    if (type === "bag") return html`<svg viewBox="0 0 48 48"><path d="M14 18h20l4 24H10z"/><path d="M18 18c0-10 12-10 12 0"/></svg>`;
    if (type === "bars") return html`<svg viewBox="0 0 48 48"><path d="M9 38V25M20 38V18M31 38V12M42 38V6"/></svg>`;
    if (type === "grid") return html`<svg viewBox="0 0 48 48"><rect x="9" y="9" width="10" height="10" rx="1"/><rect x="29" y="9" width="10" height="10" rx="1"/><rect x="9" y="29" width="10" height="10" rx="1"/><rect x="29" y="29" width="10" height="10" rx="1"/></svg>`;
    if (type === "cycle") return html`<svg viewBox="0 0 48 48"><path d="M36 16a15 15 0 0 0-25 7M12 13v10h10M12 32a15 15 0 0 0 25-7M36 35V25H26"/></svg>`;
    if (type === "clock") return html`<svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="17"/><path d="M24 12v13l9 7"/></svg>`;
    if (type === "gauge") return html`<svg viewBox="0 0 48 48"><path d="M8 32a16 16 0 0 1 32 0"/><path d="M24 32l9-13"/><path d="M13 32h4M31 32h4"/></svg>`;
    if (type === "target") return html`<svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="16"/><circle cx="24" cy="24" r="9"/><circle cx="24" cy="24" r="3"/><path d="M36 12l6-6M35 13h7v7"/></svg>`;
    if (type === "blister") return html`<svg viewBox="0 0 48 48"><rect x="14" y="8" width="20" height="32" rx="3"/><circle cx="21" cy="17" r="2"/><circle cx="28" cy="17" r="2"/><circle cx="21" cy="25" r="2"/><circle cx="28" cy="25" r="2"/><circle cx="21" cy="33" r="2"/><circle cx="28" cy="33" r="2"/></svg>`;
    if (type === "machine") return html`<svg viewBox="0 0 48 48"><rect x="8" y="15" width="32" height="8" rx="2"/><rect x="5" y="31" width="38" height="8" rx="2"/><path d="M11 23v8M37 23v8M18 25l6 5 6-5"/></svg>`;
    if (type === "bottle") return html`<svg viewBox="0 0 48 48"><path d="M19 42h14l3-20h-5V10h-9v12h-5z"/><path d="M19 31h14"/></svg>`;
    if (type === "users") return html`<svg viewBox="0 0 48 48"><circle cx="19" cy="18" r="6"/><circle cx="32" cy="20" r="5"/><path d="M8 39c2-8 20-8 22 0"/><path d="M27 38c2-5 10-5 13 0"/></svg>`;
    if (type === "settings") return html`<svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="5"/><path d="M24 7v6M24 35v6M7 24h6M35 24h6M12 12l4 4M32 32l4 4M36 12l-4 4M16 32l-4 4"/></svg>`;
    if (type === "warn") return html`<svg viewBox="0 0 48 48"><path d="M24 7l19 34H5z"/><path d="M24 18v10M24 35h.01"/></svg>`;
    if (type === "pencil") return html`<svg viewBox="0 0 48 48"><path d="M10 36l2 2 9-2 17-17-7-7-17 17z"/><path d="M28 15l7 7"/></svg>`;
    return html`<svg viewBox="0 0 48 48"><path d="M24 7l19 34H5z"/><path d="M24 18v10M24 35h.01"/></svg>`;
  }

  function Badge(props) {
    return html`<span className=${"occ-badge occ-" + (props.tone || "off")}>${props.children}</span>`;
  }

  function KpiCard(props) {
    var editing = !!props.editing;
    return html`<article className=${"occ-kpi" + (editing ? " is-editing" : "")}>
      ${props.editable ? html`<button className="kpi-edit-btn" type="button" title=${editing ? "Close target editor" : "Edit target"} onClick=${props.onEdit}>${miniIcon("pencil")}</button>` : null}
      ${editing ? html`<form className="kpi-target-form" onSubmit=${function (e) { e.preventDefault(); props.onSave && props.onSave(e); }}>
        <label>${props.editLabel || "Target"}<input name="target" type=${props.editType || "number"} min="0" step=${props.editStep || "1"} defaultValue=${props.editValue || ""} /></label>
        <div><button type="submit">Save</button><button type="button" onClick=${props.onEdit}>Cancel</button></div>
      </form>` : html`<div><span>${props.label}</span><strong className=${props.tone ? "kpi-" + props.tone : ""}>${props.value}</strong><em>${props.note || "Insufficient data"}</em></div>
      <div className="occ-kpi-icon">${miniIcon(props.icon)}</div>`}
    </article>`;
  }

  function Sidebar(props) {
    var iconByTab = {
      overview: "grid",
      blister: "blister",
      card: "machine",
      bottle: "bottle",
      machines: "machine",
      bags: "bag",
      staging: "grid",
      alerts: "warn",
      analytics: "bars",
      team: "users",
      materials: "settings",
    };
    var items = props.items || [];
    return html`<aside className="occ-side">
      <div className="occ-logo"><span></span><span></span><span></span></div>
      ${items.map(function (item) {
        var tab = String(item.tab || "").toLowerCase();
        var label = item.label || tab || "Section";
        return html`<button
          key=${tab}
          type="button"
          className=${props.activeTab === tab ? "active" : ""}
          onClick=${function () {
            props.onSelect(tab);
          }}
        >
          <span className="nav-icon">${miniIcon(iconByTab[tab] || "grid")}</span><em>${label}</em>
        </button>`;
      })}
    </aside>`;
  }

  function StepCard(props) {
    return html`<div className=${"step-card" + (props.attention ? " attention" : "")}>
      <b>${props.index}</b>
      <div><strong title=${props.title}>${props.title}</strong><small title=${props.sub || "Insufficient data"}>${props.sub || "Insufficient data"}</small></div>
      ${machineIcon(props.icon || "bag", props.status || "NO_ACTIVITY_TODAY")}
      <p title=${props.detail || "Insufficient data"}>${props.attention ? "Over historical avg" : (props.detail || "Insufficient data")}</p>
    </div>`;
  }

  function LifecycleLane(props) {
    return html`<section className=${"life-lane " + props.tone + (props.dimmed ? " dimmed" : "")}>
      <header><h2>${props.title} <span>(FULL LIFECYCLE)</span></h2><p>SKU: <b>${props.sku || "N/A"}</b></p></header>
      <div className="step-row">${props.steps.map(function (s, i) {
        return html`<${StepCard} key=${i} index=${i + 1} title=${s.title} sub=${s.sub} detail=${s.detail} icon=${s.icon} status=${s.status} attention=${s.attention} />`;
      })}</div>
      ${props.recentRun ? html`<${RecentRunStrip} run=${props.recentRun} />` : null}
      <footer><span></span><strong>FULL PRODUCTION CYCLE COMPLETE</strong><i>✓</i></footer>
    </section>`;
  }

  function RecentRunStrip(props) {
    var r = props.run || {};
    return html`<div className="life-run-strip">
      <b>MOST RECENT FINAL RUN</b>
      <span><em>Bag</em>${r.bag || "N/A"}</span>
      <span><em>Flavor</em>${r.sku || "N/A"}</span>
      <span><em>Displays</em>${r.displays != null ? fmtNumber(r.displays) : "Insufficient data"}</span>
      <span><em>Damaged</em>${r.damaged != null ? fmtNumber(r.damaged) : "No reject data"}</span>
      <span><em>Completed</em>${r.at ? fmtTime(r.at) : "N/A"}</span>
    </div>`;
  }

  function FlavorBarPanel(props) {
    var rows = (props.rows || []).slice(0, 8).map(function (r) {
      return {
        flavor: r.sku || r.flavor || "N/A",
        displays: asNum(r.displays != null ? r.displays : r.units),
        bags: asNum(r.bags),
      };
    }).filter(function (r) {
      return r.displays != null && r.displays > 0;
    });
    var max = rows.reduce(function (m, r) { return Math.max(m, r.displays || 0); }, 0);
    return html`<section className="wall-panel"><h3>DISPLAYS BY FLAVOR (DAY)</h3>
      ${rows.length ? html`<div className="flavor-bar-list">${rows.map(function (r) {
        var pct = max > 0 ? Math.max(4, Math.round((r.displays / max) * 100)) : 0;
        return html`<div className="flavor-bar-row" key=${r.flavor}>
          <div><strong title=${r.flavor}>${r.flavor}</strong><span>${r.bags != null ? fmtNumber(r.bags) + " bags" : "Bags N/A"}</span></div>
          <div className="flavor-bar-track"><i style=${{ width: pct + "%" }}></i></div>
          <b>${fmtNumber(r.displays)}</b>
        </div>`;
      })}</div>` : html`<div className="panel-empty">Insufficient data</div>`}
    </section>`;
  }

  function MachineCard(props) {
    var m = props.machine;
    var notIntegrated = m.integrationStatus === "NOT_INTEGRATED";
    var avg = stationAverageFor(m, props.shiftConfig);
    var latest = m.latestEvent || {};
    var done = m.counterEvent || {};
    var start = done.counterStart != null ? done.counterStart : latest.counterStart;
    var end = done.counterEnd != null ? done.counterEnd : latest.counterEnd;
    var countTotal = asNum(done.countTotal != null ? done.countTotal : latest.countTotal);
    var counter = "Insufficient data";
    if (notIntegrated) {
      counter = "N/A";
    } else if (start != null || end != null) {
      counter = String(start != null ? start : "N/A") + " / " + String(end != null ? end : "N/A");
    } else if (countTotal != null) {
      counter = fmtNumber(countTotal);
    }
    var bagLabel = notIntegrated ? "N/A" : ((m.workflowBagId != null || m.currentBagId != null) ? (m.currentBagLabel || ("BAG-" + (m.workflowBagId != null ? m.workflowBagId : m.currentBagId))) : "No activity today");
    var isPackaging = String(m.stationKind || "").toLowerCase() === "packaging";
    var serverOut = isPackaging ? m.displaysToday : m.tabletsToday;
    var unitsTodayVal = serverOut != null && serverOut !== undefined ? serverOut : m.completedUnits;
    var histUh = asNum(m.rateHistUh);
    var throughputLabel = notIntegrated ? "N/A" : (m.throughputPerHour != null ? m.throughputPerHour.toFixed(1) + " u/h" : (histUh != null && histUh > 0 ? histUh.toFixed(1) + " u/h 7D avg" : "Insufficient data"));
    return html`<article className=${"occ-machine " + statusTone(m.integrationStatus) + (props.attention ? " attention" : "")}>
      <header><div><h3>${m.shortLabel}</h3><p>${m.label}</p></div><${Badge} tone=${statusTone(m.integrationStatus)}>${statusText(m.integrationStatus)}</${Badge}></header>
      <div className="machine-mid">${machineIcon(m.kind, m.integrationStatus)}<dl>
        <div><dt>Current Bag</dt><dd title=${bagLabel}>${bagLabel}</dd></div>
        <div><dt>SKU</dt><dd>${m.sku || "N/A"}</dd></div>
      </dl></div>
      <div className="machine-grid-data">
        <div><span>Start Time</span><b>${notIntegrated ? "N/A" : fmtTime(m.occupancyStartedAtMs || m.lastScanMs)}</b></div>
        <div><span>Elapsed Time</span><b>${notIntegrated ? "N/A" : (m.occupancyStartedAtMs || m.lastScanMs ? durationClock(m.occupancyStartedAtMs || m.lastScanMs) : "N/A")}</b></div>
        <div><span>Counter</span><b>${counter}</b></div>
        <div><span>Last Scan</span><b>${notIntegrated ? "N/A" : fmtTime(m.lastScanMs)}</b></div>
        <div><span>Throughput</span><b>${throughputLabel}</b></div>
        <div><span>${unitsTodayLabelForMachine(m)}</span><b>${notIntegrated ? "N/A" : fmtNumber(unitsTodayVal)}</b></div>
        <div><span>7D Avg Cycle</span><b>${notIntegrated ? "N/A" : (avg ? avg.avgMinutes.toFixed(1) + " min" : "Insufficient data")}</b></div>
      </div>
    </article>`;
  }

  function MachineBand(props) {
    var machines = props.machines || [];
    return html`<section className=${"machine-band " + props.tone}>
      <h2>${props.title}</h2>
      <div className="machine-band-row">${machines.length ? machines.map(function (m) { return html`<${MachineCard} key=${m.shortLabel + "-" + m.stationId} machine=${m} shiftConfig=${props.shiftConfig} attention=${overAverage(m, props.shiftConfig, props.nowMs)} />`; }) : html`<div className="panel-empty compact">No configured stations</div>`}</div>
    </section>`;
  }

  function AlertsRail(props) {
    var alerts = (props.alerts || []).slice(0, 5);
    return html`<aside className="alerts-rail">
      <header><h2>ACTIVE ALERTS</h2></header>
      ${alerts.length ? alerts.map(function (a, i) {
        var sev = String(a.severity || "info").toLowerCase();
        return html`<div key=${i} className=${"alert-item " + sev}>
          <b>${fmtTime(a.at_ms || a.atMs)}</b><p>${a.message || a.event || "Activity"}</p><${Badge} tone=${sev === "warn" || sev === "alert" ? "idle" : "off"}>${sev}</${Badge}>
        </div>`;
      }) : html`<div className="alert-item info"><b>N/A</b><p>No active alerts</p><${Badge} tone="off">INFO</${Badge}></div>`}
    </aside>`;
  }

  function DataTable(props) {
    var emptyText =
      props.emptyLabel != null && props.emptyLabel !== ""
        ? props.emptyLabel
        : "Insufficient data";
    return html`<table className="occ-table"><thead><tr>${props.headers.map(function (h) { return html`<th key=${h}>${h}</th>`; })}</tr></thead>
      <tbody>${props.rows.length ? props.rows.map(function (r, i) { return html`<tr key=${i}>${r.map(function (c, j) { return html`<td key=${j}>${c}</td>`; })}</tr>`; }) : html`<tr><td colSpan=${props.headers.length}>${emptyText}</td></tr>`}</tbody></table>`;
  }

  function TrendPanel(props) {
    var trend = props.trend || {};
    var valid = trend.series_valid && Array.isArray(trend.blister) && trend.blister.length;
    var series = valid ? [trend.blister || [], trend.bottle || [], trend.card || []] : [];
    var max = Math.max.apply(null, [1].concat(series.reduce(function (a, b) { return a.concat(b); }, [])));
    var names = ["Blister / Card", "Bottle", "Card Finishing"];
    var labels = trend.labels || ["12A", "4A", "8A", "12P", "4P", "8P", "12A"];
    return html`<section className="wall-panel trend-panel"><h3>PRODUCTION TREND (UNITS)</h3>
      <div className="trend-legend">${names.map(function (n, i) { return html`<span key=${n} className=${"legend s" + i}>${n}</span>`; })}</div>
      ${valid ? html`<svg viewBox="0 0 460 176" className="trend-svg" role="img" aria-label="Production trend in units by line">
        ${[0, 1, 2, 3, 4].map(function (i) {
          var y = 132 - i * 27;
          var val = Math.round((max / 4) * i);
          return html`<g key=${i}><path d=${"M36 " + y + "H446"} /><text x="4" y=${y + 3}>${fmtNumber(val)}</text></g>`;
        })}
        ${labels.slice(0, 7).map(function (l, i) {
          var x = 42 + (i / 6) * 390;
          return html`<text key=${i} className="x-label" x=${x} y="166">${l}</text>`;
        })}
        ${series.map(function (s, si) {
          var d = s.map(function (v, i) {
            var x = 42 + (i / Math.max(1, s.length - 1)) * 390;
            var y = 132 - (Number(v || 0) / max) * 116;
            return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
          }).join(" ");
          return html`<path key=${si} className=${"line s" + si} d=${d} />`;
        })}
      </svg>` : html`<div className="panel-empty">Insufficient data</div>`}
    </section>`;
  }

  function OeePanel(props) {
    var label = String(props.value || "Insufficient data");
    var pct = parseFloat(label);
    var valid = Number.isFinite(pct);
    var dash = valid ? Math.max(0, Math.min(100, pct)) + " 100" : "0 100";
    return html`<section className="wall-panel oee-panel"><h3>OEE BREAKDOWN (OVERALL)</h3>
      <div className="donut-wrap"><svg viewBox="0 0 42 42"><circle cx="21" cy="21" r="15.9" /><circle className="donut-meter" cx="21" cy="21" r="15.9" stroke-dasharray=${dash} /></svg><strong>${label}</strong></div>
    </section>`;
  }

  function TracePanel(props) {
    var inputState = useState("");
    var q = inputState[0];
    var setQ = inputState[1];
    var parsed = parseInt(String(q || "").trim(), 10);
    var bagId = Number.isFinite(parsed) ? parsed : props.defaultBagId;
    var geo = window.OpsMetrics.deriveBagGenealogy(bagId, props.events, props.bags);
    return html`<section className="wall-panel trace-panel"><h3>LIVE BAG GENEALOGY / LOT TRACE</h3>
      <div className="trace-meta"><input aria-label="Trace bag ID" value=${q} placeholder=${String(props.defaultBagId || "Bag ID")} onInput=${function (e) { setQ(e.target.value); }} /><b>Bag ${geo.bagId || "N/A"}</b><span>SKU ${geo.sku || "N/A"}</span><span>Qty ${geo.receivedQtyDisplay || "N/A"}</span></div>
      <div className="trace-steps">${(geo.traceLines || []).map(function (r, i) { return html`<div key=${i} className=${r.pending ? "pending" : "done"}><span></span><b>${r.label}</b><em>${r.pending ? "Pending" : fmtTime(r.atMs)}</em></div>`; })}</div>
    </section>`;
  }

  function MaterialRollHistoryTable(props) {
    var summary = props.summary || {};
    var stats = summary.roll_stats || {};
    var active = summary.active_rolls || {};
    function row(mt, label) {
      var s = stats[mt] || {};
      var a = active[mt] || null;
      var live = a && a.blisters_used_live != null ? Number(a.blisters_used_live) : null;
      var avg = s.avg_blisters_per_completed_roll;
      var last = s.last_completed_blisters;
      var n = s.sample_size != null ? s.sample_size : 0;
      return html`<tr key=${mt}>
        <td>${label}</td>
        <td>${avg != null ? fmtNumber(avg) : "—"}</td>
        <td>${live != null && avg != null ? fmtVsRef(live, avg, "avg") : "—"}</td>
        <td>${live != null && last != null ? fmtVsRef(live, last, "last") : "—"}</td>
        <td title="Rolls in sample for average">${n > 0 ? String(n) : "—"}</td>
      </tr>`;
    }
    var sp = stats.pvc && stats.pvc.sample_size;
    var sf = stats.foil && stats.foil.sample_size;
    var sampleNote = Math.max(sp || 0, sf || 0);
    return html`<section className="wall-panel mes-material-kpi-wrap">
      <h3>ROLL USAGE vs HISTORY</h3>
      <p className="muted" style=${{ marginBottom: "8px" }}>
        Averages use up to 40 completed rolls per material. Current use is live from the active roll (press count × blisters-per-press).
        ${sampleNote > 0 ? " Sample size (max): " + sampleNote + " rolls." : " No completed rolls yet — change a roll to start history."}
      </p>
      <div className="mini-table-wrap">
        <table className="occ-table">
          <thead><tr><th>Material</th><th>Avg / roll</th><th>Current vs avg</th><th>Current vs last</th><th title="Rolls used for average">N</th></tr></thead>
          <tbody>
            ${row("pvc", "PVC")}
            ${row("foil", "Foil")}
          </tbody>
        </table>
      </div>
    </section>`;
  }

  function BlisterMaterialPanel(props) {
    var summary = props.summary || {};
    var active = summary.active_rolls || {};
    var pvc = active.pvc || null;
    var foil = active.foil || null;
    var disabled = !props.stationId || props.busy;
    var msg = props.rollMessage || null;
    function rollStatus(row) {
      return row ? "In use" : "None";
    }
    return html`<div className="mes-material-stack">
      ${msg
        ? html`<div
            className=${"mes-roll-flash " + (msg.kind === "ok" ? "mes-roll-flash--ok" : "mes-roll-flash--err")}
            role="status"
          >${msg.text}</div>`
        : null}
      ${!props.stationId
        ? html`<section className="wall-panel mes-material-kpi-wrap">
            <h3>BLISTER STATION</h3>
            <p className="mes-roll-flash mes-roll-flash--err" style=${{ display: "block" }}>
              No blister workflow station is configured, or it is not in today’s line map. Add a machine with role <b>blister</b> and a workflow station with kind <b>blister</b> in Machine Settings, then refresh.
            </p>
          </section>`
        : null}
      <${MaterialRollHistoryTable} summary=${summary} />
      <section className="wall-panel">
        <h3>BLISTER MATERIAL TRACKING</h3>
        <div className="mini-table-wrap">
          <table className="occ-table">
            <thead><tr><th>Material</th><th>Current roll</th><th>Blisters used (est.)</th></tr></thead>
            <tbody>
              <tr><td>PVC</td><td>${rollStatus(pvc)}</td><td>${pvc ? fmtNumber(pvc.blisters_used_live) : "N/A"}</td></tr>
              <tr><td>Foil</td><td>${rollStatus(foil)}</td><td>${foil ? fmtNumber(foil.blisters_used_live) : "N/A"}</td></tr>
            </tbody>
          </table>
        </div>
        <div className="trace-meta mes-material-roll-actions" style=${{ marginTop: "10px" }}>
          <button type="button" disabled=${disabled} onClick=${function () { props.onChangeRoll("pvc"); }}>Change PVC roll</button>
          <button type="button" disabled=${disabled} onClick=${function () { props.onChangeRoll("foil"); }}>Change foil roll</button>
        </div>
        <p className="muted" style=${{ marginTop: "8px" }}>
          When you swap material on the blister line, tap the matching button. Roll IDs are assigned automatically for traceability; usage is estimated from press count × blisters-per-press.
        </p>
      </section>
    </div>`;
  }

  function App(props) {
    var snapState = useState(null);
    var snap = snapState[0];
    var setSnap = snapState[1];
    var clockState = useState(new Date());
    var now = clockState[0];
    var setNow = clockState[1];
    var matSummaryState = useState(null);
    var materialSummary = matSummaryState[0];
    var setMaterialSummary = matSummaryState[1];
    var matBusyState = useState(false);
    var materialBusy = matBusyState[0];
    var setMaterialBusy = matBusyState[1];
    var rollMsgState = useState(null);
    var rollMessage = rollMsgState[0];
    var setRollMessage = rollMsgState[1];
    var compressorsState = useState([]);
    var compressors = compressorsState[0];
    var setCompressors = compressorsState[1];
    var dateState = useState(function () {
      try {
        return new URLSearchParams(window.location.search).get("date") || todayIsoDate();
      } catch (e) {
        return todayIsoDate();
      }
    });
    var selectedDate = dateState[0];
    var setSelectedDate = dateState[1];
    var targetEditState = useState(null);
    var targetEditing = targetEditState[0];
    var setTargetEditing = targetEditState[1];
    var saveTickState = useState(0);
    var saveTick = saveTickState[0];
    var setSaveTick = saveTickState[1];

    useEffect(function () {
      var t = setInterval(function () { setNow(new Date()); }, 1000);
      return function () { clearInterval(t); };
    }, []);

    useEffect(function () {
      if (!rollMessage) return undefined;
      var timer = setTimeout(function () { setRollMessage(null); }, 8000);
      return function () { clearTimeout(timer); };
    }, [rollMessage]);

    useEffect(function () {
      var n = document.getElementById("ops-tv-initial-data");
      if (n && n.textContent) {
        try { setSnap(JSON.parse(n.textContent)); } catch (e) {}
      }
      function load() {
        var url = props.snapshotUrl + (props.snapshotUrl.indexOf("?") >= 0 ? "&" : "?") + "date=" + encodeURIComponent(selectedDate);
        fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (out) {
          setSnap(out);
          try {
            var u = new URL(window.location.href);
            u.searchParams.set("date", selectedDate);
            window.history.replaceState(null, "", u.toString());
          } catch (e) {}
        }).catch(function () {});
      }
      load();
      var id = setInterval(load, 5000);
      return function () { clearInterval(id); };
    }, [props.snapshotUrl, selectedDate, saveTick]);

    var boot = readBoot();
    var navRaw = Array.isArray(boot.nav) && boot.nav.length ? boot.nav : FALLBACK_NAV_ITEMS;
    var navItems = normalizeMesNav(navRaw);
    var machineSettingsUrl = (boot && boot.urls && boot.urls.machine_settings) || "/admin/settings/machines";
    var tabState = useState(function () { return readInitialTab(navItems); });
    var activeTab = tabState[0];
    var setActiveTab = tabState[1];
    var selectedPoState = useState("");
    var selectedInventoryPo = selectedPoState[0];
    var setSelectedInventoryPo = selectedPoState[1];
    var mes = (snap && snap.mes) || {};
    var inp = mes.metrics_inputs || {};
    var events = inp.events || [];
    var derived = useMemo(function () {
      return window.OpsMetrics.deriveDashboardMetrics(inp.events || [], inp.machines || [], inp.bags || [], inp.shiftConfig || {});
    }, [snap]);
    var kpiBy = {};
    (derived.kpis || []).forEach(function (k) { kpiBy[k.id] = k; });

    var slots = inp.slots || [];
    function kindForSlot(s) {
      var role = String((s && s.stepRole) || "").toLowerCase();
      var stationKind = String((s && s.stationKind) || "").toLowerCase();
      if (role === "blister" || stationKind === "blister") return "blister";
      if (role === "heat_seal" || stationKind === "sealing") return "heat";
      if (role === "packaging" || stationKind === "packaging") return "pack";
      if (role === "stickering") return "sticker";
      if (role === "bottle") return "bottle";
      return "bag";
    }
    var defs = slots.length ? slots.map(function (s, i) {
      return {
        slot: s.slot || i + 1,
        shortLabel: s.shortLabel || ("STATION " + (i + 1)),
        label: s.displayName || s.label || "WORKFLOW STATION",
        kind: kindForSlot(s),
        stationId: s.stationId,
        flow: s.flow || "blister_card",
        stepRole: s.stepRole || "",
        stationKind: s.stationKind || "",
        machineRole: s.machineRole || "",
      };
    }) : [
      { slot: 1, shortLabel: "MACHINE 1", label: "DPP115 BLISTER MACHINE", kind: "blister", stationId: null, flow: "blister_card", stepRole: "blister" },
      { slot: 2, shortLabel: "MACHINE 2", label: "HEAT PRESS MACHINE", kind: "heat", stationId: null, flow: "blister_card", stepRole: "heat_seal" },
      { slot: 3, shortLabel: "MACHINE 3", label: "HEAT PRESS MACHINE", kind: "heat", stationId: null, flow: "blister_card", stepRole: "heat_seal" },
      { slot: 4, shortLabel: "MACHINE 4", label: "HEAT PRESS MACHINE", kind: "heat", stationId: null, flow: "blister_card", stepRole: "heat_seal" },
      { slot: 5, shortLabel: "PACKAGING", label: "PACKAGING STATION", kind: "pack", stationId: null, flow: "packaging_station", stepRole: "packaging" },
    ];
    var configured = (inp.machines || []).map(function (m) { return m.id; });
    var bagById = {};
    (inp.bags || []).forEach(function (b) {
      if (b && b.id != null) bagById[String(b.id)] = b;
    });
    function skuForBag(bagId) {
      var b = bagId != null ? bagById[String(bagId)] : null;
      return b && (b.sku || b.productLabel) ? (b.sku || b.productLabel) : "N/A";
    }
    function bagDisplayLabel(bagId) {
      if (bagId == null || bagId === "") return "N/A";
      var b = bagById[String(bagId)] || null;
      var receipt = b ? String(b.receiptNumber || "").trim() : "";
      var flavor = b ? String(b.productLabel || b.sku || "").trim() : "";
      if (receipt && flavor && flavor !== "—") return receipt + " (" + flavor + ")";
      if (receipt) return receipt;
      if (flavor && flavor !== "—") return "BAG-" + bagId + " (" + flavor + ")";
      return "BAG-" + bagId;
    }
    function bagShortLabel(bagId) {
      if (bagId == null || bagId === "") return "N/A";
      var b = bagById[String(bagId)] || null;
      var receipt = b ? String(b.receiptNumber || "").trim() : "";
      return receipt || ("BAG-" + bagId);
    }
    var machines = defs.map(function (d) {
      var liveRow = (inp.machines || []).find(function (r) { return r.id === d.stationId; }) || {};
      var metrics = (derived.machines || []).find(function (m) { return m.id === d.stationId; }) || {};
      var merged = Object.assign({}, metrics, {
        workflowBagId: liveRow.workflowBagId != null ? liveRow.workflowBagId : metrics.workflowBagId,
        currentBagId: liveRow.workflowBagId != null ? liveRow.workflowBagId : metrics.currentBagId,
        occupancyStartedAtMs: liveRow.occupancyStartedAtMs != null ? liveRow.occupancyStartedAtMs : metrics.occupancyStartedAtMs,
        pausedAtMs: liveRow.pausedAtMs != null ? liveRow.pausedAtMs : metrics.pausedAtMs,
        tabletsToday: liveRow.tabletsToday != null ? liveRow.tabletsToday : metrics.tabletsToday,
        displaysToday: liveRow.displaysToday != null ? liveRow.displaysToday : metrics.displaysToday,
        stationKind: liveRow.stationKind || metrics.stationKind || d.stationKind,
        machineRole: liveRow.machineRole || metrics.machineRole || d.machineRole,
        cardsPerTurn: liveRow.cardsPerTurn != null ? liveRow.cardsPerTurn : metrics.cardsPerTurn,
        occupancyStatus: liveRow.status || null,
      });
      var isBottleFlow = d.flow === "bottle";
      var hasBottleEvents = !isBottleFlow || events.some(function (e) { return eventMachineId(e) === asNum(d.stationId); });
      var status = d.stationId == null ? "NOT_INTEGRATED" : resolveIntegrationBadge(liveRow, d.stationId, events, {
        dayStartMs: inp.shiftConfig && inp.shiftConfig.dayStartMs,
        configuredMachineIds: configured,
        forceNotIntegratedMachineIds: isBottleFlow && !hasBottleEvents ? [d.stationId] : [],
      });
      var wid = merged.workflowBagId != null ? merged.workflowBagId : merged.currentBagId;
      return Object.assign({}, d, merged, {
        integrationStatus: status,
        latestEvent: latestByMachine(events, d.stationId),
        counterEvent: completedCounterEvent(events, d.stationId),
        sku: skuForBag(wid),
        currentBagLabel: bagDisplayLabel(wid),
      });
    });

    var blisterCardMachines = machines.filter(function (m) { return m.flow === "blister_card" && (m.stepRole === "blister" || m.stepRole === "heat_seal"); });
    var blisterMachines = blisterCardMachines.filter(function (m) { return m.stepRole === "blister" || m.stationKind === "blister"; }).slice(0, 1);
    var heatSealMachines = blisterCardMachines.filter(function (m) { return m.stepRole === "heat_seal" || m.stationKind === "sealing"; }).slice(0, 3);
    blisterCardMachines = blisterMachines.concat(heatSealMachines);
    var packagingMachines = machines.filter(function (m) { return m.flow === "packaging_station" || m.stepRole === "packaging" || m.stationKind === "packaging"; });

    var alerts = (mes.alerts || []).filter(function (a) { return String(a.severity || "info").toLowerCase() !== "info"; });
    var timeline = (mes.timeline || []).slice(0, 7);
    var staging = derived.stagingBags || [];
    var inventoryRaw = mes.inventory || [];
    function inventoryRowPo(r) {
      if (!r) return "";
      var pn = r.po_number != null ? r.po_number : r.poNumber;
      return String(pn || "").trim();
    }
    function normPoKey(s) {
      return String(s || "").trim().toLowerCase();
    }
    var poOptsMerged = {};
    var vendorByPo = {};
    function mergeInventoryPoEntry(entry) {
      if (entry == null) return;
      if (typeof entry === "object" && (entry.po_number != null || entry.poNumber != null)) {
        var pnum = String(entry.po_number != null ? entry.po_number : entry.poNumber).trim();
        if (!pnum) return;
        poOptsMerged[pnum] = 1;
        var v = String((entry.vendor_name != null ? entry.vendor_name : entry.vendorName) || "").trim();
        if (v && !vendorByPo[pnum]) vendorByPo[pnum] = v;
        return;
      }
      var ks = String(entry || "").trim();
      if (ks) poOptsMerged[ks] = 1;
    }
    (mes.inventory_po_options || []).forEach(mergeInventoryPoEntry);
    inventoryRaw.forEach(function (r) {
      var k = inventoryRowPo(r);
      if (k) {
        poOptsMerged[k] = 1;
        var vn = String((r.vendor_name != null ? r.vendor_name : r.vendorName) || "").trim();
        if (vn && !vendorByPo[k]) vendorByPo[k] = vn;
      }
    });
    var inventoryPoOptionKeys = Object.keys(poOptsMerged).sort().reverse();
    function inventoryRowCells(r) {
      var label = String((r && (r.bag_id != null ? r.bag_id : r.bagId)) || "").trim();
      if (!label) label = "N/A";
      return [r.sku || r.product || "N/A", label, fmtNumber(r.units != null ? r.units : r.qty), fmtNumber(r.quantity != null ? r.quantity : r.bags), r.status || "N/A"];
    }
    var inventoryRows = inventoryRaw.slice(0, 6).map(inventoryRowCells);
    var inventoryFiltered = selectedInventoryPo
      ? inventoryRaw.filter(function (r) {
          return normPoKey(inventoryRowPo(r)) === normPoKey(selectedInventoryPo);
        })
      : inventoryRaw;
    var inventoryRowsBagsTab = inventoryFiltered.map(inventoryRowCells);
    var bagsInventoryEmptyLabel =
      inventoryRowsBagsTab.length || !selectedInventoryPo ? null : "No bags for this purchase order in the loaded list.";
    var invTableHeaders = ["SKU", "SHIP-BOX-BAG", "UNITS", "QUANTITY", "STATUS"];
    var topSkuRows = (mes.sku_table || []).slice(0, 4).map(function (r) {
      return [r.sku || "N/A", r.line || r.product_type || "N/A", fmtNumber(r.displays != null ? r.displays : r.units), fmtNumber(r.bags), fmtNumber(r.cycles)];
    });
    var recentFinalEvent = (events || []).filter(isFinalPackagingSnapshot).sort(function (a, b) {
      return (eventAt(b) || 0) - (eventAt(a) || 0);
    })[0] || null;
    var recentFinalRun = null;
    if (recentFinalEvent) {
      var recentBag = eventBagId(recentFinalEvent);
      recentFinalRun = {
        bag: recentBag != null ? bagDisplayLabel(recentBag) : "N/A",
        sku: recentBag != null ? skuForBag(recentBag) : (recentFinalEvent.sku || recentFinalEvent.productLabel || "N/A"),
        displays: eventDisplayCount(recentFinalEvent),
        damaged: eventDamagedCards(recentFinalEvent),
        at: eventAt(recentFinalEvent),
      };
    }
    function stagingContext(row) {
      var et = String((row && row.lastEventType) || "").toUpperCase();
      var sid = asNum(row && row.lastStationId);
      if (et.indexOf("BLISTER") >= 0 || sid === 1) {
        return { line: "Blister / Card", area: "After Blister -> Before Heat Seal" };
      }
      if (et.indexOf("SEALING") >= 0 || et.indexOf("HEAT") >= 0 || sid === 2 || sid === 3) {
        return { line: "Blister / Card", area: "After Heat Seal -> Before Packaging" };
      }
      if (et.indexOf("BOTTLE") >= 0 || et.indexOf("STICKER") >= 0 || sid === 4 || sid === 5) {
        return { line: "Bottle", area: "Bottle Flow Staging Queue" };
      }
      return { line: "Line Pending Mapping", area: "Staging Queue" };
    }
    var stagingRows = staging.slice(0, 6).map(function (r) {
      var ctx = stagingContext(r);
      return [ctx.line, ctx.area, bagDisplayLabel(r.bagId), elapsedSince(r.enteredAtMs)];
    });
    var timelineRows = timeline.map(function (r) {
      return [fmtTime(r.at_ms || r.atMs), r.line || "N/A", r.machine || r.station || "N/A", r.event || r.message || "Activity", bagDisplayLabel(r.bag_id)];
    });
    var teamRows = (mes.team || []).slice(0, 6).map(function (r) {
      return [r.employee || r.operator || r.name || "N/A", r.line || "N/A", fmtNumber(r.cycles || r.bags), fmtNumber(r.units || r.qty)];
    });
    var downtimeRows = (mes.downtime || []).slice(0, 4).map(function (r) {
      return [r.line || "N/A", r.downtime || r.duration || "N/A", r.reason || "N/A", fmtNumber(r.impact_units || r.impact)];
    });
    var allAlertRows = (mes.alerts || []).map(function (a) {
      return [fmtTime(a.at_ms || a.atMs), String(a.severity || "info").toUpperCase(), a.message || "Alert"];
    });
    var allMachineRows = machines.map(function (m) {
      var bid = m.workflowBagId != null ? m.workflowBagId : m.currentBagId;
      var histUh = asNum(m.rateHistUh);
      var tp = m.throughputPerHour != null ? m.throughputPerHour.toFixed(1) + " u/h" : (histUh != null && histUh > 0 ? histUh.toFixed(1) + " u/h 7D avg" : "Insufficient data");
      return [m.shortLabel, m.label, m.stationId != null ? String(m.stationId) : "N/A", statusText(m.integrationStatus), bid != null ? bagDisplayLabel(bid) : "No activity", tp];
    });
    var machineNameById = {};
    machines.forEach(function (m) {
      if (m && m.stationId != null) {
        machineNameById[String(m.stationId)] = m.shortLabel + " - " + (m.label || "Machine");
      }
    });
    var compressorRows = (compressors || []).map(function (c) {
      var rawStatus = String((c && c.status) || "").toLowerCase();
      var isUnassigned = !(c && c.machine_id != null);
      var status = isUnassigned
        ? "IDLE"
        : (rawStatus === "working" ? "RUNNING" : (rawStatus ? rawStatus.toUpperCase() : "N/A"));
      var tone = isUnassigned ? "idle" : (rawStatus === "working" ? "run" : (rawStatus === "maintenance" ? "idle" : "off"));
      var machineName = c && c.machine_id != null
        ? (machineNameById[String(c.machine_id)] || c.machine_name || ("Machine #" + c.machine_id))
        : "Unassigned";
      return [(c && c.compressor_name) || "N/A", html`<${Badge} tone=${tone}>${status}</${Badge}>`, machineName];
    });
    var stagingBagRows = staging.map(function (r) {
      return [bagDisplayLabel(r.bagId), elapsedSince(r.enteredAtMs), r.lastStationLabel || "N/A", r.lastEventType || "N/A"];
    });
    var bagAssignmentRows = (inp.machines || []).filter(function (r) { return r.workflowBagId != null; }).map(function (r) {
      return [bagDisplayLabel(r.workflowBagId), r.displayName || r.stationLabel || "N/A", r.stationKind || "N/A", r.status || "N/A", elapsedSince(r.occupancyStartedAtMs)];
    });

    var rawBottleFlowMachines = machines.filter(function (m) { return m.flow === "bottle"; });
    var bottleIntegrated = rawBottleFlowMachines.some(function (m) { return m.integrationStatus !== "NOT_INTEGRATED"; });
    var blisterSku = (blisterCardMachines.find(function (m) { return m.sku && m.sku !== "N/A"; }) || {}).sku || "N/A";
    var bottleSku = bottleIntegrated ? ((rawBottleFlowMachines.find(function (m) { return m.sku && m.sku !== "N/A"; }) || {}).sku || "N/A") : "N/A";
    function offlineCopy(m) {
      return Object.assign({}, m, {
        integrationStatus: "NOT_INTEGRATED",
        currentBagId: null,
        workflowBagId: null,
        occupancyStartedAtMs: null,
        lastScanMs: null,
        throughputPerHour: null,
        completedUnits: null,
        sku: "N/A",
      });
    }
    var bottleLineMachines = bottleIntegrated ? rawBottleFlowMachines : rawBottleFlowMachines.map(offlineCopy);
    var oeeTargetNote = inp.shiftConfig && inp.shiftConfig.targetThroughputSource === "configured" ? "Target configured" : (inp.shiftConfig && inp.shiftConfig.targetThroughputSource === "historical" ? "Historical pace estimate" : "No target set");
    var dailyDisplayTarget = asNum(inp.shiftConfig && inp.shiftConfig.dailyDisplayTarget);
    var targetThroughput = asNum(inp.shiftConfig && inp.shiftConfig.targetThroughputPerHour);
    var dueTimeValue = timeInputValue(inp.shiftConfig && inp.shiftConfig.productionDueMs);
    var finalDisplaysValue = kpiBy.units ? asNum(kpiBy.units.value) : null;
    var finalDisplayNote = dailyDisplayTarget != null && finalDisplaysValue != null
      ? fmtNumber(finalDisplaysValue) + " / " + fmtNumber(dailyDisplayTarget) + " target"
      : "Packaging final submit";

    function toggleTargetEditor(which) {
      setTargetEditing(targetEditing === which ? null : which);
    }

    function saveOpsTarget(kind, event) {
      var form = event && event.currentTarget;
      var target = form && form.elements && form.elements.target ? form.elements.target.value : "";
      var payload = {
        target_units_per_hour: targetThroughput != null ? String(targetThroughput) : "",
        daily_display_target: dailyDisplayTarget != null ? String(dailyDisplayTarget) : "",
        production_due_time: dueTimeValue || "",
      };
      if (kind === "daily") payload.daily_display_target = target;
      if (kind === "throughput") payload.target_units_per_hour = target;
      if (kind === "due") payload.production_due_time = target;
      fetch("/api/settings/ops_tv_dataset", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": readCsrfToken(),
        },
        body: JSON.stringify(payload),
      }).then(function (r) { return r.json(); }).then(function (out) {
        if (out && out.success) {
          setTargetEditing(null);
          setSaveTick(function (n) { return n + 1; });
        }
      }).catch(function () {});
    }
    var blisterStationId =
      asNum(inp.blisterStationId) ||
      (blisterMachines[0] && asNum(blisterMachines[0].stationId)) ||
      null;

    function loadMaterialSummary(stationId) {
      if (!stationId) return;
      fetch("/api/blister-material-rolls/summary?station_id=" + encodeURIComponent(stationId), { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (out) {
          if (out && out.success) setMaterialSummary(out);
        })
        .catch(function () {});
    }

    function changeRoll(materialType) {
      if (materialBusy) return;
      if (!blisterStationId) {
        setRollMessage({
          kind: "err",
          text: "No blister workflow station ID — add a blister station in Machine Settings and reload.",
        });
        return;
      }
      setMaterialBusy(true);
      setRollMessage(null);
      var label = materialType === "pvc" ? "PVC" : "Foil";
      fetch("/api/blister-material-rolls/change", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": readCsrfToken(),
        },
        body: JSON.stringify({
          station_id: blisterStationId,
          material_type: materialType,
          roll_code: null,
        }),
      })
        .then(function (r) {
          return r.json().then(function (body) {
            return { ok: r.ok, status: r.status, body: body };
          });
        })
        .then(function (x) {
          var body = x.body || {};
          if (x.ok && body.success) {
            setRollMessage({
              kind: "ok",
              text:
                label +
                " roll change saved. Active roll " +
                String(body.roll_code || "") +
                " at press count " +
                fmtNumber(body.current_press_count) +
                ".",
            });
            loadMaterialSummary(blisterStationId);
          } else {
            var err = body.error || "HTTP " + (x.status || "?");
            setRollMessage({ kind: "err", text: label + " roll change failed: " + err });
          }
        })
        .catch(function () {
          setRollMessage({ kind: "err", text: label + " roll change failed: network error." });
        })
        .finally(function () { setMaterialBusy(false); });
    }

    function loadCompressors() {
      fetch("/api/compressors", { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (out) {
          if (out && out.success && Array.isArray(out.compressors)) {
            setCompressors(out.compressors);
          }
        })
        .catch(function () {});
    }

    useEffect(function () {
      if (blisterStationId) loadMaterialSummary(blisterStationId);
    }, [blisterStationId]);

    useEffect(function () {
      if (!blisterStationId) return undefined;
      var id = setInterval(function () { loadMaterialSummary(blisterStationId); }, 5000);
      return function () { clearInterval(id); };
    }, [blisterStationId]);

    useEffect(function () {
      loadCompressors();
      var id = setInterval(loadCompressors, 5000);
      return function () { clearInterval(id); };
    }, []);

    useEffect(function () {
      function onHashChange() {
        setActiveTab(readInitialTab(navItems));
      }
      window.addEventListener("hashchange", onHashChange);
      return function () {
        window.removeEventListener("hashchange", onHashChange);
      };
    }, [navItems]);

    function selectTab(tab) {
      setActiveTab(tab);
      var h = "#" + tab;
      if (window.location.hash !== h) window.history.replaceState(null, "", h);
    }

    function renderFocusedTab() {
      if (activeTab === "alerts") return html`<section className="occ-wall"><section className="wall-panel"><h3>ALL ALERTS</h3><${DataTable} headers=${["TIME", "SEVERITY", "MESSAGE"]} rows=${allAlertRows} /></section><section className="wall-panel"><h3>PRODUCTION TIMELINE (LATEST ACTIVITY)</h3><${DataTable} headers=${["TIME", "LINE", "MACHINE", "EVENT", "BAG ID"]} rows=${timelineRows} /></section></section>`;
      if (activeTab === "machines") return html`<div><section className="wall-panel"><h3>ALL MACHINE DATA</h3><${DataTable} headers=${["MACHINE", "TYPE", "STATION", "STATUS", "CURRENT BAG", "THROUGHPUT"]} rows=${allMachineRows} /><div className="trace-meta" style=${{ marginTop: "10px", gridTemplateColumns: "max-content" }}><a className="mes-link-btn" href=${machineSettingsUrl}>Open Machine Settings</a></div></section><section className="occ-machine-grid three-bands"><${MachineBand} title="BLISTER / CARD MACHINES" tone="blue" machines=${blisterCardMachines} shiftConfig=${inp.shiftConfig || {}} nowMs=${now.getTime()} /><${MachineBand} title="PACKAGING QR STATION" tone="purple" machines=${packagingMachines} shiftConfig=${inp.shiftConfig || {}} nowMs=${now.getTime()} /><${MachineBand} title="BOTTLE FLOW MACHINES" tone="green" machines=${bottleLineMachines} shiftConfig=${inp.shiftConfig || {}} nowMs=${now.getTime()} /></section><section className="wall-panel"><h3>COMPRESSORS</h3><${DataTable} headers=${["COMPRESSOR", "STATUS", "CONNECTED MACHINE"]} rows=${compressorRows} /></section></div>`;
      if (activeTab === "staging") return html`<section className="occ-wall"><section className="wall-panel"><h3>ALL BAGS IN STAGING</h3><${DataTable} headers=${["BAG", "TIME IN STAGING", "LAST STATION", "LAST EVENT"]} rows=${stagingBagRows} /></section><section className="wall-panel"><h3>STAGING AREA STATUS</h3><${DataTable} headers=${["LINE", "QUEUE STAGE", "BAG (PO-SHIPMENT-BOX-BAG + FLAVOR)", "TIME IN AREA"]} rows=${stagingRows} /></section></section>`;
      if (activeTab === "bags")
        return html`<section className="occ-wall"><section className="wall-panel"><div className="occ-po-bar"><label className="occ-po-label" htmlFor="occ-po-select">Purchase order</label><select id="occ-po-select" className="occ-po-select" value=${selectedInventoryPo} onChange=${function (e) { setSelectedInventoryPo(e.target.value); }}><option value="">All POs</option>${inventoryPoOptionKeys.map(function (p) {
          var vn = vendorByPo[p];
          var lab = vn ? p + " — " + vn : p;
          return html`<option key=${p} value=${p}>${lab}</option>`;
        })}</select></div><h3>BAGS / INVENTORY</h3><${DataTable} headers=${invTableHeaders} rows=${inventoryRowsBagsTab} emptyLabel=${bagsInventoryEmptyLabel} /></section><section className="wall-panel"><h3>LIVE BAG ASSIGNMENTS</h3><${DataTable} headers=${["BAG", "STATION", "KIND", "STATUS", "ELAPSED"]} rows=${bagAssignmentRows} /></section></section>`;
      if (activeTab === "card" || activeTab === "blister") return html`<section className="occ-machine-grid two-bands"><${MachineBand} title="BLISTER LINE MACHINES" tone="blue" machines=${blisterMachines} shiftConfig=${inp.shiftConfig || {}} nowMs=${now.getTime()} /><${MachineBand} title="CARD LINE MACHINES" tone="blue" machines=${heatSealMachines} shiftConfig=${inp.shiftConfig || {}} nowMs=${now.getTime()} /></section>`;
      if (activeTab === "bottle") return html`<section className="occ-machine-grid two-bands"><${MachineBand} title="BOTTLE LINE MACHINES" tone="green" machines=${bottleLineMachines} shiftConfig=${inp.shiftConfig || {}} nowMs=${now.getTime()} /></section>`;
      if (activeTab === "analytics") return html`<section className="occ-wall"><${TrendPanel} trend=${mes.trend || {}} /><section className="wall-panel"><h3>DISPLAYS BY FLAVOR (DAY)</h3><${DataTable} headers=${["FLAVOR", "LINE", "DISPLAYS", "BAGS", "CYCLES"]} rows=${topSkuRows} /></section><${OeePanel} value=${kpiBy.oee && kpiBy.oee.value} /><section className="wall-panel"><h3>DOWNTIME SUMMARY (TODAY)</h3><${DataTable} headers=${["LINE", "DOWNTIME", "REASON", "IMPACT"]} rows=${downtimeRows} /></section></section>`;
      if (activeTab === "team") return html`<section className="occ-wall"><section className="wall-panel"><h3>TEAM PERFORMANCE (TODAY)</h3><${DataTable} headers=${["TEAM", "LINE", "CYCLES", "UNITS"]} rows=${teamRows} /></section></section>`;
      if (activeTab === "materials") return html`<section className="occ-wall"><${BlisterMaterialPanel} summary=${materialSummary} stationId=${blisterStationId} busy=${materialBusy} rollMessage=${rollMessage} onChangeRoll=${changeRoll} /></section>`;
      return null;
    }
    var generated = snap && snap.generated_at_ms;
    return html`<div className="occ-app">
      <${Sidebar} boot=${boot} items=${navItems} activeTab=${activeTab} onSelect=${selectTab} />
      <main className="occ-main">
        <header className="occ-header">
          <div><h1>PILL PACKING COMMAND CENTER</h1><p>Real-time Production Monitoring <span></span> LIVE</p></div>
          <div className="occ-head-controls"><input type="date" aria-label="Dashboard date" value=${selectedDate} onInput=${function (e) { setSelectedDate(e.target.value || todayIsoDate()); }} /><b>${fmtDate(generated)}</b><b>${fmtTime(now.getTime())}</b></div>
        </header>
        ${activeTab !== "overview" ? renderFocusedTab() : null}
        ${activeTab === "overview" ? html`
        <section className="occ-kpis">
          <${KpiCard} label="COMPLETED BAGS (DAY)" value=${kpiBy.bags ? fmtNumber(kpiBy.bags.value) : "0"} note="Bag to final only" icon="bag" />
          <${KpiCard} label="FINAL DISPLAYS PRODUCED" value=${kpiBy.units ? fmtNumber(kpiBy.units.value) : "0"} note=${finalDisplayNote} icon="bars" editable=${true} editing=${targetEditing === "daily"} editLabel="Daily display target" editValue=${dailyDisplayTarget != null ? String(dailyDisplayTarget) : ""} editStep="1" onEdit=${function () { toggleTargetEditor("daily"); }} onSave=${function (e) { saveOpsTarget("daily", e); }} />
          <${KpiCard} label="FLAVORS PRODUCED (DAY)" value=${kpiBy.cycles ? fmtNumber(kpiBy.cycles.value) : "0"} note="Displays by flavor below" icon="cycle" />
          <${KpiCard} label="AVERAGE CYCLE TIME (ALL)" value=${kpiBy.avg_cycle ? kpiBy.avg_cycle.value : "Insufficient data"} note=${kpiBy.avg_cycle && kpiBy.avg_cycle.value !== "Insufficient data" ? "From completed operations" : "Insufficient data"} icon="clock" tone="amber" />
          <${KpiCard} label="OEE (OVERALL)" value=${kpiBy.oee ? kpiBy.oee.value : "Insufficient data"} note=${oeeTargetNote} icon="gauge" tone="green" editable=${true} editing=${targetEditing === "throughput"} editLabel="Target output/hour" editValue=${targetThroughput != null ? String(targetThroughput) : ""} editStep="0.01" onEdit=${function () { toggleTargetEditor("throughput"); }} onSave=${function (e) { saveOpsTarget("throughput", e); }} />
          <${KpiCard} label="ON TIME COMPLETION" value=${kpiBy.on_time ? kpiBy.on_time.value : "No target set"} note=${inp.shiftConfig && inp.shiftConfig.productionDueMs ? "Due time configured" : "No target set"} icon="target" tone="red" editable=${true} editing=${targetEditing === "due"} editLabel="Daily due time" editType="time" editValue=${dueTimeValue} onEdit=${function () { toggleTargetEditor("due"); }} onSave=${function (e) { saveOpsTarget("due", e); }} />
          <${KpiCard} label="DAMAGED / RIPPED CARDS" value=${kpiBy.rework ? (typeof kpiBy.rework.value === "number" ? fmtNumber(kpiBy.rework.value) : kpiBy.rework.value) : "No reject data"} note="Packaging cards reopened" icon="warn" tone="red" />
        </section>
        <section className="occ-life-grid">
          <${LifecycleLane} tone="blue" title="BLISTER / CARD FLOW" sku=${blisterSku} steps=${[
            { title: "BAG", sub: "Bag QR scanned", detail: "Received qty N/A", icon: "bag" },
            { title: "BLISTER", sub: (blisterMachines[0] && blisterMachines[0].shortLabel) || "M1", detail: (blisterMachines[0] && (blisterMachines[0].workflowBagId != null || blisterMachines[0].currentBagId != null)) ? bagShortLabel(blisterMachines[0].workflowBagId != null ? blisterMachines[0].workflowBagId : blisterMachines[0].currentBagId) : "Insufficient data", icon: "blister", status: blisterMachines[0] && blisterMachines[0].integrationStatus, attention: overAverage(blisterMachines[0], inp.shiftConfig || {}, now.getTime()) },
            { title: "STAGE", sub: "Auto gap queue", detail: "After blister, before heat seal", icon: "bag" },
            { title: "CARD / HEAT SEAL", sub: heatSealMachines.map(function (m) { return m.shortLabel.replace("MACHINE ", "M"); }).join(" / ") || "Heat seal", detail: "Scan station + bag", icon: "heat", status: heatSealMachines.some(function (m) { return m.integrationStatus === "LIVE_QR"; }) ? "LIVE_QR" : "NO_ACTIVITY_TODAY", attention: heatSealMachines.some(function (m) { return overAverage(m, inp.shiftConfig || {}, now.getTime()); }) },
            { title: "STAGE", sub: "Auto gap queue", detail: "After seal, before packing", icon: "bag" },
            { title: "PACKAGING", sub: "Shared QR timer station", detail: packagingMachines[0] && (packagingMachines[0].workflowBagId != null || packagingMachines[0].currentBagId != null) ? bagShortLabel(packagingMachines[0].workflowBagId != null ? packagingMachines[0].workflowBagId : packagingMachines[0].currentBagId) : "Waiting for scan", icon: "pack", status: packagingMachines[0] && packagingMachines[0].integrationStatus, attention: packagingMachines.some(function (m) { return overAverage(m, inp.shiftConfig || {}, now.getTime()); }) },
            { title: "FINAL", sub: "Lifecycle complete", detail: "Finished goods", icon: "bag" }
          ]} recentRun=${recentFinalRun} />
          <${LifecycleLane} tone="green" title="BOTTLE FLOW" sku=${bottleSku} dimmed=${!bottleIntegrated} steps=${[
            { title: "BAG", sub: "Bag QR scanned", detail: bottleIntegrated ? "Received qty N/A" : "Bottle line not integrated yet", icon: "bag", status: "NOT_INTEGRATED" },
            { title: "BOTTLE", sub: "Bottle station", detail: bottleIntegrated ? "Scan station + bag" : "Not integrated", icon: "bottle", status: bottleIntegrated ? "LIVE_QR" : "NOT_INTEGRATED" },
            { title: "STAGE", sub: "Auto gap queue", detail: "After bottle, before sticker", icon: "bag" },
            { title: "STICKER", sub: "Stickering station", detail: bottleIntegrated ? "Scan station + bag" : "Offline", icon: "sticker", status: machines[4].integrationStatus },
            { title: "STAGE", sub: "Auto gap queue", detail: "After sticker, before seal", icon: "bag" },
            { title: "HEAT SEAL", sub: "Bottle seal", detail: bottleIntegrated ? "Counter required" : "Offline", icon: "heat", status: machines[4].integrationStatus },
            { title: "STAGE", sub: "Auto gap queue", detail: "After seal, before packing", icon: "bag" },
            { title: "PACKAGING", sub: "Shared QR timer station", detail: packagingMachines[0] && (packagingMachines[0].workflowBagId != null || packagingMachines[0].currentBagId != null) ? bagShortLabel(packagingMachines[0].workflowBagId != null ? packagingMachines[0].workflowBagId : packagingMachines[0].currentBagId) : "Waiting for scan", icon: "pack", status: packagingMachines[0] && packagingMachines[0].integrationStatus, attention: packagingMachines.some(function (m) { return overAverage(m, inp.shiftConfig || {}, now.getTime()); }) },
            { title: "FINAL", sub: "Lifecycle complete", detail: "Finished goods", icon: "bag" }
          ]} />
          <${AlertsRail} alerts=${alerts} />
        </section>
        <section className="occ-machine-grid three-bands">
          <${MachineBand} title="BLISTER / CARD MACHINES" tone="blue" machines=${blisterCardMachines} shiftConfig=${inp.shiftConfig || {}} nowMs=${now.getTime()} />
          <${MachineBand} title="PACKAGING QR STATION" tone="purple" machines=${packagingMachines} shiftConfig=${inp.shiftConfig || {}} nowMs=${now.getTime()} />
          <${MachineBand} title="BOTTLE FLOW MACHINES" tone="green" machines=${bottleLineMachines} shiftConfig=${inp.shiftConfig || {}} nowMs=${now.getTime()} />
        </section>
        <section className="occ-wall wall-row-a">
          <section className="wall-panel"><h3>BAG INVENTORY (IN STOCK)</h3><${DataTable} headers=${invTableHeaders} rows=${inventoryRows} /></section>
          <${TrendPanel} trend=${mes.trend || {}} />
          <${FlavorBarPanel} rows=${mes.sku_table || []} />
          <section className="wall-panel"><h3>FLAVOR OUTPUT DETAIL (DAY)</h3><${DataTable} headers=${["FLAVOR", "LINE", "DISPLAYS", "BAGS", "CYCLES"]} rows=${topSkuRows} /></section>
          <section className="wall-panel"><h3>STAGING AREA STATUS</h3><${DataTable} headers=${["LINE", "QUEUE STAGE", "BAG (PO-SHIPMENT-BOX-BAG + FLAVOR)", "TIME IN AREA"]} rows=${stagingRows} /></section>
        </section>
        <section className="occ-wall wall-row-b">
          <section className="wall-panel"><h3>PRODUCTION TIMELINE (LATEST ACTIVITY)</h3><${DataTable} headers=${["TIME", "LINE", "MACHINE", "EVENT", "BAG ID"]} rows=${timelineRows} /></section>
          <${BlisterMaterialPanel}
            summary=${materialSummary}
            stationId=${blisterStationId}
            busy=${materialBusy}
            onChangeRoll=${changeRoll}
          />
          <${OeePanel} value=${kpiBy.oee && kpiBy.oee.value} />
          <section className="wall-panel"><h3>DOWNTIME SUMMARY (TODAY)</h3><${DataTable} headers=${["LINE", "DOWNTIME", "REASON", "IMPACT"]} rows=${downtimeRows} /></section>
          <section className="wall-panel"><h3>TEAM PERFORMANCE (TODAY)</h3><${DataTable} headers=${["TEAM", "LINE", "CYCLES", "UNITS"]} rows=${teamRows} /></section>
        </section>
        <${TracePanel} events=${events} bags=${inp.bags || []} defaultBagId=${derived.genealogySelectedBagId || inp.genealogySelectedBagId} />
        ` : null}
        <footer className="occ-footer"><span>All data is real-time and updates automatically.</span><span>Last updated: ${generated ? fmtTime(generated, true) : "N/A"} <i></i></span></footer>
      </main>
    </div>`;
  }

  var root = document.getElementById("mes-root");
  if (!root) return;
  ReactDOM.createRoot(root).render(html`<${App} snapshotUrl=${root.getAttribute("data-snapshot-url") || ""} />`);
})();
