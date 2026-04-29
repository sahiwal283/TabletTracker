/**
 * Single derivation layer for MES command center — formulas only from event inputs.
 * No fabricated production data when demoMode is false.
 */

export type DataSourceStatus =
  | "LIVE_QR"
  | "MANUAL_ENTRY"
  | "NOT_INTEGRATED"
  | "NO_ACTIVITY_TODAY";

export interface WorkflowEventRow {
  atMs: number;
  stationId: number | null;
  eventType: string;
  bagId: number | null;
  userId: number | null;
  operatorLabel: string | null;
  countTotal: number | null;
  displayCount: number | null;
  counterStart: number | null;
  counterEnd: number | null;
}

export interface MachineRow {
  id: number;
  displayName?: string;
  stationLabel?: string;
  stationKind: string;
  status: string;
  occupancyStartedAtMs: number | null;
  pausedAtMs?: number | null;
  workflowBagId: number | null;
  manualEntrySignal?: boolean;
}

export interface BagRow {
  id: number;
  receiptNumber?: string | null;
  sku?: string | null;
  qtyReceived?: number | null;
  productLabel?: string | null;
}

export interface ShiftConfig {
  dayStartMs: number;
  nowMs: number;
  plannedShiftMinutes: number;
  targetThroughputPerHour: number | null;
  productionDueMs: number | null;
}

export interface SlotDef {
  slot: number;
  label: string;
  shortLabel: string;
  stationId: number | null;
  stationKind: string | null;
  /** e.g. bottle_seal · requires SEALING_* events at station to be LIVE */
  role?: string | null;
}

export interface MetricsInputs {
  demoMode: boolean;
  events: WorkflowEventRow[];
  machines: MachineRow[];
  bags: BagRow[];
  shiftConfig: ShiftConfig;
  slots: SlotDef[];
}

export interface DerivedKpi {
  id: string;
  displayLabel: string;
  value: string | number | null;
  valuePct: number | null;
  formulaNote: string;
  sparkline: number[] | null;
  deltaPct: number | null;
  deltaMin?: number | null;
  subtitle?: string;
}

export interface DerivedMachineUi {
  slot: number;
  label: string;
  shortLabel: string;
  canonical: string;
  stationId: number | null;
  dataSourceStatus: DataSourceStatus;
  statusUi: string;
  statusLight: "run" | "wait" | "idle" | "fault";
  rawStatus: string;
  integrationMessage: string;
  dataSourceLine: string;
  bagId: string;
  sku: string;
  operatorLabel: string;
  timerMs: number | null;
  counterDisplay: string;
  throughputUh: string;
  utilizationPct: string;
  oeePct: string;
  cycleElapsedMin: string;
  lastScan: string;
}

export interface GenealogyTimelineStep {
  key: string;
  label: string;
  pending: boolean;
  atMs: number | null;
  machineLabel: string;
  stationId: number | null;
  operatorLabel: string;
  counterReading: string;
  dwellFromPrevMinutes: number | null;
  statusBadge: string;
}

export interface DerivedBagGenealogy {
  bagId: number | null;
  sku: string;
  receivedQtyDisplay: string;
  traceLines: GenealogyTimelineStep[];
  totals: {
    elapsedMinutes: number | null;
    dwellMinutes: number | null;
    message: string;
  };
}

function insuf(): string {
  return "Insufficient data";
}

export function clampOeePct(a: number, p: number, q: number): number | null {
  const o = (a / 100) * (p / 100) * (q / 100) * 100;
  if (Number.isNaN(o)) return null;
  return Math.min(100, Math.max(0, o));
}

/** Events attributed to station (sid may be Floor aggregate—client should pass concrete station ids.) */
export function stationEventsToday(events: WorkflowEventRow[], sid: number): WorkflowEventRow[] {
  return events.filter((e) => e.stationId === sid);
}

export function getMachineIntegrationStatus(
  stationId: number | null,
  stationKind: string | null,
  machine: MachineRow | undefined,
  eventsToday: WorkflowEventRow[],
  slotRole?: string | null,
): DataSourceStatus {
  if (!stationId) return "NOT_INTEGRATED";
  if (machine?.manualEntrySignal) return "MANUAL_ENTRY";
  if (
    slotRole === "bottle_seal" &&
    !eventsToday.some((e) => e.stationId === stationId && e.eventType === "SEALING_COMPLETE")
  ) {
    return "NOT_INTEGRATED";
  }

  const hasWorkflow =
    stationId !== null &&
    eventsToday.some(
      (e) =>
        e.stationId === stationId &&
        [
          "BAG_CLAIMED",
          "BLISTER_COMPLETE",
          "SEALING_COMPLETE",
          "BOTTLE_HANDPACK_COMPLETE",
          "BOTTLE_CAP_SEAL_COMPLETE",
          "BOTTLE_STICKER_COMPLETE",
          "PACKAGING_SNAPSHOT",
          "CARD_ASSIGNED",
          "BAG_FINALIZED",
        ].includes(String(e.eventType)),
    );
  if (!hasWorkflow) return "NO_ACTIVITY_TODAY";
  return "LIVE_QR";
}

export function deriveQueueAging(_events: WorkflowEventRow[]): { zones: { line: string; area: string; ageMinutes: number; tier: string; heat: number }[] } {
  return { zones: [] };
}

export function deriveBottleneck(_events: WorkflowEventRow[]): { label: string | null; stageId: string | null } {
  return { label: null, stageId: null };
}

function sumCounterDeltas(events: WorkflowEventRow[]): number | null {
  let acc = 0;
  let any = false;
  for (const e of events) {
    if (e.counterStart != null && e.counterEnd != null) {
      acc += Math.max(0, e.counterEnd - e.counterStart);
      any = true;
      continue;
    }
    if (e.countTotal != null && e.countTotal > 0) {
      acc += e.countTotal;
      any = true;
    }
    if (e.displayCount != null && e.displayCount > 0) {
      acc += e.displayCount;
      any = true;
    }
  }
  return any ? acc : null;
}

function uniqueBagsToday(events: WorkflowEventRow[]): number {
  const s = new Set<number>();
  for (const e of events) {
    if (e.bagId != null) s.add(e.bagId);
  }
  return s.size;
}

function completedCycleMinutes(events: WorkflowEventRow[]): number[] {
  const byBag = new Map<number, WorkflowEventRow[]>();
  for (const e of events) {
    if (e.bagId == null) continue;
    const xs = byBag.get(e.bagId) || [];
    xs.push(e);
    byBag.set(e.bagId, xs);
  }
  const out: number[] = [];
  for (const [, xs] of byBag) {
    xs.sort((a, b) => a.atMs - b.atMs);
    const claim = xs.find((e) => e.eventType === "BAG_CLAIMED");
    const fin = xs.find(
      (e) => e.eventType === "BAG_FINALIZED" || (e.eventType === "PACKAGING_SNAPSHOT" && e.displayCount != null),
    );
    if (claim && fin && fin.atMs > claim.atMs) {
      out.push((fin.atMs - claim.atMs) / 60000);
    }
  }
  return out;
}

export function deriveMachineMetrics(
  slot: SlotDef,
  machine: MachineRow | undefined,
  events: WorkflowEventRow[],
  shift: ShiftConfig,
): DerivedMachineUi {
  const sid = slot.stationId;
  const se = sid != null ? stationEventsToday(events, sid) : [];
  const stLow = String(machine?.status || "idle").toLowerCase();
  const st = stLow === "occupied" ? "running" : stLow;
  const vis = st === "running" ? "RUNNING" : st === "paused" ? "WAITING" : "IDLE";
  const light: "run" | "wait" | "idle" | "fault" =
    vis === "RUNNING" ? "run" : vis === "WAITING" ? "wait" : "idle";
  const integ = getMachineIntegrationStatus(sid, slot.stationKind, machine, events, slot.role);
  let statusUi = vis;
  if (integ === "NOT_INTEGRATED") statusUi = "NOT INTEGRATED";
  if (sid == null || integ === "NOT_INTEGRATED") {
    return {
      slot: slot.slot,
      label: slot.label,
      shortLabel: slot.shortLabel,
      canonical: slot.label,
      stationId: sid,
      dataSourceStatus: integ === "NOT_INTEGRATED" ? "NOT_INTEGRATED" : integ,
      statusUi,
      statusLight: "idle",
      rawStatus: st,
      integrationMessage: "Not integrated — QR workflow not configured.",
      dataSourceLine: "Manual / Not connected",
      bagId: "N/A",
      sku: "N/A",
      operatorLabel: "N/A",
      timerMs: null,
      counterDisplay: "N/A",
      throughputUh: "N/A",
      utilizationPct: "N/A",
      oeePct: "N/A",
      cycleElapsedMin: "N/A",
      lastScan: "N/A",
    };
  }

  /** Only LIVE_QR may show throughput/counter math */
  const hasLive = integ === "LIVE_QR";
  let lastScan = "—";
  if (se.length) lastScan = new Date(Math.max(...se.map((x) => x.atMs))).toLocaleTimeString();

  let bag = "—";
  if (hasLive && machine?.workflowBagId != null) bag = String(machine.workflowBagId);

  let timerMs: number | null = null;
  if (machine?.occupancyStartedAtMs && st === "running") {
    timerMs = Number(machine.occupancyStartedAtMs);
  }

  const delta = sumCounterDeltas(se);
  const ctrDisp = !hasLive ? "N/A" : delta != null ? String(Math.round(delta)) : insuf();

  let thrStr = insuf();
  let thrNum = NaN;
  const runH =
    timerMs != null
      ? Math.max(5 / 3600, (shift.nowMs - timerMs) / 3600000)
      : shift.plannedShiftMinutes > 1
        ? shift.plannedShiftMinutes / 60
        : 1;
  if (hasLive && delta != null && runH > 0) {
    thrNum = delta / runH;
    thrStr = thrNum.toFixed(1);
  }

  let utilDisp = insuf();
  const plannedMin = shift.plannedShiftMinutes || 480;
  if (hasLive && sid != null && se.length >= 2) {
    const span = (Math.max(...se.map((x) => x.atMs)) - Math.min(...se.map((x) => x.atMs))) / 60000;
    utilDisp = String(Math.min(100, Math.round((span / plannedMin) * 100)));
  } else if (hasLive && timerMs) {
    utilDisp = String(
      Math.min(100, Math.round((((shift.nowMs - timerMs) / 60000) / plannedMin) * 100)),
    );
  }

  let oee = insuf();
  if (hasLive && se.length >= 3) {
    const avail =
      plannedMin > 0
        ? Math.min(
            100,
            (Math.min(shift.nowMs - shift.dayStartMs, plannedMin * 60000) / 60000 / plannedMin) * 50,
          )
        : null;
    let perf: number | null = null;
    if (shift.targetThroughputPerHour != null && shift.targetThroughputPerHour > 0 && !Number.isNaN(thrNum)) {
      perf = Math.min(100, (thrNum / shift.targetThroughputPerHour) * 100);
    }
    const qual = rejectStats(events).qualityPct;
    const ox =
      avail != null && perf != null && qual != null ? clampOeePct(avail, perf, qual) : null;
    oee = ox != null ? ox.toFixed(1) + "%" : insuf();
  }

  let cycleDisp = insuf();
  const occ = machine?.occupancyStartedAtMs;
  if (hasLive && occ) cycleDisp = `${((shift.nowMs - Number(occ)) / 60000).toFixed(1)}`;

  let dataLine = "Manual / Not connected";
  if (integ === "LIVE_QR") dataLine = "QR / workflow_events";
  else if (integ === "NO_ACTIVITY_TODAY") dataLine = "Station live — no workflow scans today";
  else if (integ === "MANUAL_ENTRY") dataLine = "Manual entry pathway";

  return {
    slot: slot.slot,
    label: slot.label,
    shortLabel: slot.shortLabel,
    canonical: slot.label,
    stationId: sid,
    dataSourceStatus: integ,
    statusUi,
    statusLight: light,
    rawStatus: st,
    integrationMessage:
      integ === "NOT_INTEGRATED"
        ? "Not integrated — QR workflow not configured."
        : integ === "NO_ACTIVITY_TODAY"
          ? "No workflow scans today."
          : "",
    dataSourceLine: dataLine,
    bagId:
      machine?.workflowBagId != null
        ? String(machine.workflowBagId)
        : integ === "NO_ACTIVITY_TODAY" || !hasLive
          ? "—"
          : "N/A",
    sku: "—",
    operatorLabel: (() => {
      if (!hasLive) return "N/A";
      const op = [...se].reverse().find((e) => e.operatorLabel && String(e.operatorLabel).trim());
      return op?.operatorLabel ? String(op.operatorLabel) : "—";
    })(),
    timerMs: hasLive ? timerMs : null,
    counterDisplay: !hasLive ? "N/A" : ctrDisp,
    throughputUh: !hasLive || thrStr === insuf() ? "N/A" : thrStr + " u/h",
    utilizationPct: !hasLive || utilDisp === insuf() ? "N/A" : utilDisp + "%",
    oeePct: !hasLive ? "N/A" : oee,
    cycleElapsedMin: !hasLive ? "N/A" : cycleDisp,
    lastScan: !hasLive ? "N/A" : lastScan,
  };
}

function rejectStats(events: WorkflowEventRow[]): { rejectUnits: number; totalApprox: number; qualityPct: number | null } {
  let rejects = 0;
  let totalApprox = 0;
  for (const e of events) {
    if (e.eventType === "CARD_REJECT" || e.eventType === "CARD_FORCE_RELEASED") rejects += 1;
    const u = e.countTotal ?? e.displayCount ?? null;
    if (u != null && u > 0) totalApprox += u;
  }
  if (totalApprox <= 0) return { rejectUnits: rejects, totalApprox: 0, qualityPct: null };
  const good = Math.max(0, totalApprox - rejects);
  return { rejectUnits: rejects, totalApprox, qualityPct: (good / (totalApprox + rejects)) * 100 };
}

export function deriveDashboardMetrics(
  inputs: MetricsInputs | { events?: WorkflowEventRow[]; machines?: MachineRow[]; bags?: BagRow[]; shiftConfig?: ShiftConfig; demoMode?: boolean; slots?: SlotDef[] },
): {
  kpis: DerivedKpi[];
  machines: DerivedMachineUi[];
  oeeDonut: { total: string; availability: string; performance: string; quality: string };
  notes: string[];
} {
  const demo = !!(inputs as MetricsInputs).demoMode;
  const events = (inputs as MetricsInputs).events || [];
  const machines = (inputs as MetricsInputs).machines || [];
  const bags = (inputs as MetricsInputs).bags || [];
  const shift = (inputs as MetricsInputs).shiftConfig;
  const slots = (inputs as MetricsInputs).slots || [];
  const notes: string[] = [];
  if (!shift) {
    return {
      kpis: [],
      machines: [],
      oeeDonut: { total: insuf(), availability: insuf(), performance: insuf(), quality: insuf() },
      notes: [insuf()],
    };
  }

  const byId = new Map<number, MachineRow>();
  for (const m of machines) byId.set(Number(m.id), m);

  const bagsToday = uniqueBagsToday(events);
  const units = sumCounterDeltas(events);
  const cycles = completedCycleMinutes(events);
  const avgCycle =
    cycles.length > 0 ? (cycles.reduce((a, b) => a + b, 0) / cycles.length).toFixed(1) + " min" : insuf();

  const plannedMin = shift.plannedShiftMinutes || 1;
  const elapsedMin = Math.max(1, (shift.nowMs - shift.dayStartMs) / 60000);
  const rs = rejectStats(events);
  const qualPct = rs.qualityPct;
  const rejectRate =
    rs.totalApprox + rs.rejectUnits > 0 ? (rs.rejectUnits / (rs.totalApprox + rs.rejectUnits)) * 100 : null;

  let availability: number | null = null;
  let runtimeMin = 0;
  for (const m of machines) {
    const sid = m.id;
    const se = stationEventsToday(events, sid);
    if (se.length >= 2) {
      runtimeMin += (Math.max(...se.map((x) => x.atMs)) - Math.min(...se.map((x) => x.atMs))) / 60000;
    } else if (
      m.occupancyStartedAtMs &&
      ["running", "occupied"].includes(String(m.status || "").toLowerCase())
    ) {
      runtimeMin += (shift.nowMs - Number(m.occupancyStartedAtMs)) / 60000;
    }
  }
  if (runtimeMin > 0 && plannedMin > 0) availability = Math.min(100, (runtimeMin / plannedMin) * 100);

  const actualThr = units != null && elapsedMin > 0 ? units / (elapsedMin / 60) : null;
  const perf =
    shift.targetThroughputPerHour != null && shift.targetThroughputPerHour > 0 && actualThr != null
      ? Math.min(100, (actualThr / shift.targetThroughputPerHour) * 100)
      : null;

  const oee =
    availability != null && perf != null && qualPct != null
      ? clampOeePct(availability, perf, qualPct)
      : null;

  let oeeLabel = oee != null ? oee.toFixed(1) + "%" : insuf();
  if (qualPct == null && availability != null && perf != null) {
    oeeLabel = `Est. ${((availability / 100) * (perf / 100) * 85).toFixed(1)}% (quality assumed 85%)`;
    notes.push("Estimated OEE — no reject totals; quality assumed.");
  }

  const reworkLabel =
    rejectRate != null ? rejectRate.toFixed(2) + "%" : "No reject data";

  const kpis: DerivedKpi[] = [
    {
      id: "bags",
      displayLabel: "Bags Today",
      value: bagsToday,
      valuePct: null,
      formulaNote: "Distinct workflow_bag_id on events today.",
      sparkline: null,
      deltaPct: null,
    },
    {
      id: "units",
      displayLabel: "Units Today",
      value: units != null ? Math.round(units) : insuf(),
      valuePct: null,
      formulaNote: "Sum counter deltas (∆) or completion counts from payloads.",
      sparkline: null,
      deltaPct: null,
    },
    {
      id: "cycles",
      displayLabel: "Completed cycles",
      value: cycles.length ? cycles.length : 0,
      valuePct: null,
      formulaNote: "Bags with claim→finalize window today.",
      sparkline: null,
      deltaPct: null,
    },
    {
      id: "avg_cycle",
      displayLabel: "Avg Cycle Time",
      value: avgCycle,
      valuePct: null,
      formulaNote: "Average (finalize − claim) by bag.",
      sparkline: null,
      deltaPct: null,
    },
    {
      id: "oee",
      displayLabel:
        qualPct !== null
          ? "OEE"
          : availability != null && perf != null
            ? "Estimated OEE (quality unknown)"
            : "OEE",
      value: oeeLabel,
      valuePct: oee != null ? oee : null,
      formulaNote: `OEE = A×P×Q; A=${availability != null ? availability.toFixed(1) + "%" : insuf()}, P=${perf != null ? perf.toFixed(1) + "%" : insuf()}, Q=${qualPct != null ? qualPct.toFixed(2) + "%" : "Needs reject/counter data"}`,
      sparkline: null,
      deltaPct: null,
    },
    {
      id: "on_time",
      displayLabel: "On-Time Completion",
      value: shift.productionDueMs == null ? "No target set" : insuf(),
      valuePct: null,
      formulaNote: "Requires planned due vs actual finish.",
      sparkline: null,
      deltaPct: null,
    },
    {
      id: "rework",
      displayLabel: "Reject Rate",
      valuePct: rejectRate != null ? rejectRate : null,
      value: reworkLabel,
      formulaNote: "reject_events / total units (approx).",
      sparkline: null,
      deltaPct: null,
    },
  ];

  /** Fix KPI value_pct for display */
  kpis.forEach((k) => {
    if (k.id === "oee" && oee != null) k.valuePct = oee;
  });

  const dm: DerivedMachineUi[] = slots.map((s) =>
    deriveMachineMetrics(s, s.stationId != null ? byId.get(s.stationId) : undefined, events, shift),
  );

  const oeeDonut = {
    total: oee != null ? oee.toFixed(2) + "%" : insuf(),
    availability: availability != null ? availability.toFixed(2) + "%" : insuf(),
    performance: perf != null ? perf.toFixed(2) + "%" : insuf(),
    quality: qualPct != null ? qualPct.toFixed(2) + "%" : "No reject data",
  };

  /** Demo overlays */
  if (demo && inputs && (inputs as MetricsInputs).demoMode) {
    kpis.forEach((k, i) => {
      k.sparkline = Array.from({ length: 12 }, (_, j) => 30 + Math.sin(j + i) * 12 + i);
    });
    notes.push("Demo mode overlays sparklines.");
  }

  /** Ensure OEE clamp */
  void bags;

  return { kpis, machines: dm, oeeDonut, notes };
}

const TIMELINE_RULES: { key: string; label: string; match: (e: WorkflowEventRow) => boolean }[] = [
  {
    key: "recv",
    label: "Received",
    match: (e) => /RECEIVE|RECEIVING|INTAKE/i.test(String(e.eventType)),
  },
  { key: "m1", label: "Assigned to M1 DPP115 · claim", match: (e) => e.eventType === "BAG_CLAIMED" },
  { key: "bst", label: "Blister Start", match: (e) => e.eventType === "BLISTER_START" },
  { key: "bend", label: "Blister Complete", match: (e) => e.eventType === "BLISTER_COMPLETE" },
  { key: "bhp", label: "Bottle Hand Pack", match: (e) => e.eventType === "BOTTLE_HANDPACK_COMPLETE" },
  { key: "bcs", label: "Bottle Cap Seal", match: (e) => e.eventType === "BOTTLE_CAP_SEAL_COMPLETE" },
  { key: "bstk", label: "Bottle Sticker", match: (e) => e.eventType === "BOTTLE_STICKER_COMPLETE" },
  { key: "pstg", label: "Post-Blister Staging", match: (e) => String(e.eventType).includes("STAGING") },
  { key: "hs0", label: "Heat Seal Start", match: (e) => String(e.eventType).startsWith("SEALING_START") },
  {
    key: "hs1",
    label: "Heat Seal Complete",
    match: (e) =>
      e.eventType === "SEALING_COMPLETE" || String(e.eventType).startsWith("SEALING_CMPL"),
  },
  { key: "pkg0", label: "Packaging Start", match: (e) => e.eventType.includes("PACKAGING") && String(e.eventType).includes("START") },
  {
    key: "pkg1",
    label: "Packaging Complete",
    match: (e) => e.eventType === "PACKAGING_SNAPSHOT" || e.eventType === "PACKAGE_COMPLETE",
  },
  { key: "fg", label: "Finished Goods", match: (e) => e.eventType === "BAG_FINALIZED" },
];

export function deriveBagGenealogy(bagId: number, eventsAll: WorkflowEventRow[], bags: BagRow[]): DerivedBagGenealogy {
  const ev = eventsAll.filter((e) => e.bagId === bagId).sort((a, b) => a.atMs - b.atMs);
  const bagMeta = bags.find((b) => b.id === bagId);
  const used = new Set<number>();
  function takeOne(rule: { key: string; label: string; match: (e: WorkflowEventRow) => boolean }) {
    for (let i = 0; i < ev.length; i++) {
      if (used.has(i)) continue;
      if (rule.match(ev[i])) {
        used.add(i);
        return ev[i];
      }
    }
    return undefined;
  }

  let prevMs: number | null = null;
  let dwellAcc = 0;
  const traceLines: GenealogyTimelineStep[] = TIMELINE_RULES.map((rule) => {
    const row = takeOne(rule);
    const pending = !row;
    let dwell: number | null = null;
    if (row) {
      if (prevMs != null) {
        dwell = (row.atMs - prevMs) / 60000;
        dwellAcc += dwell;
      }
      prevMs = row.atMs;
    }
    let ctr = "—";
    if (row) {
      if (row.counterStart != null || row.counterEnd != null)
        ctr = `${row.counterStart ?? "—"} → ${row.counterEnd ?? "—"}`;
      else if (row.countTotal != null) ctr = String(row.countTotal);
      else if (row.displayCount != null) ctr = `disp ${row.displayCount}`;
    }
    return {
      key: rule.key,
      label: rule.label,
      pending,
      atMs: row ? row.atMs : null,
      machineLabel: row?.stationId != null ? `Station ${row.stationId}` : "",
      stationId: row?.stationId ?? null,
      operatorLabel: row?.operatorLabel ? String(row.operatorLabel) : "",
      counterReading: pending ? "" : ctr,
      dwellFromPrevMinutes: dwell,
      statusBadge: pending ? "Pending" : "Done",
    };
  });

  const first = ev[0]?.atMs;
  const last = ev[ev.length - 1]?.atMs;
  const elapsed = first != null && last != null ? (last - first) / 60000 : null;

  return {
    bagId,
    sku: bagMeta?.sku || "—",
    receivedQtyDisplay: bagMeta?.qtyReceived != null ? String(bagMeta.qtyReceived) : "—",
    traceLines,
    totals: {
      elapsedMinutes: elapsed,
      dwellMinutes: dwellAcc > 0 ? dwellAcc : null,
      message: ev.length === 0 ? insuf() : "",
    },
  };
}
