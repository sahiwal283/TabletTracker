(function (global) {
  var R = global.React;

  function DPP115(props) {
    var r = !!(props && props.running);
    return R.createElement(
      "svg",
      { viewBox: "0 0 220 92", className: "mes-mac-svg" + (r ? " mes-mac-svg--run" : "") },
      R.createElement("defs", null, R.createElement("filter", { id: "mg" }, R.createElement("feGaussianBlur", { stdDeviation: "1", result: "b" }), R.createElement("feMerge", null, R.createElement("feMergeNode", { in: "b" }), R.createElement("feMergeNode", { in: "SourceGraphic" })))),
      R.createElement(
        "g",
        { filter: "url(#mg)", stroke: "#22d3ee", fill: "none", strokeWidth: 1 },
        R.createElement("text", { x: 6, y: 12, fill: "#64748b", fontSize: 9 }, "DPP115"),
        R.createElement("circle", { cx: 28, cy: 58, r: 14, className: r ? "mes-mac-spin" : "" }),
        R.createElement("rect", { x: 98, y: 34, width: 62, height: 36, rx: 2 }),
        R.createElement("rect", { x: 152, y: 58, width: 58, height: 10, rx: 2, stroke: "#67e8f9" }),
      ),
      R.createElement("rect", { x: 168, y: 10, width: 44, height: 18, rx: 2, fill: "rgba(34,211,238,0.12)", stroke: "#22d3ee" }),
      R.createElement("circle", { cx: 204, cy: 18, r: 5, fill: r ? "#22c55e" : "#475569" }),
    );
  }

  function HeatPress(props) {
    var r = !!(props && props.running);
    return R.createElement(
      "svg",
      { viewBox: "0 0 220 92", className: "mes-mac-svg" + (r ? " mes-mac-svg--run" : "") },
      R.createElement("text", { x: 6, y: 12, fill: "#64748b", fontSize: 9 }, "Heat seal · " + (props.variant || "")),
      R.createElement("rect", { x: 40, y: 22, width: 140, height: 18, rx: 3, stroke: "#22d3ee", fill: "none" }),
      R.createElement("rect", { x: 44, y: 56, width: 132, height: 18, rx: 3, stroke: "#fcd34d", fill: "none" }),
      R.createElement("path", { d: "M66 40 V56", stroke: "#fb923c", strokeDasharray: "2 3", opacity: r ? 0.9 : 0.35 }),
      R.createElement("path", { d: "M110 40 V56", stroke: "#fb923c", strokeDasharray: "2 3", opacity: r ? 0.9 : 0.35 }),
      R.createElement("path", { d: "M154 40 V56", stroke: "#fb923c", strokeDasharray: "2 3", opacity: r ? 0.9 : 0.35 }),
      R.createElement("circle", { cx: 178, cy: 26, r: 5, fill: r ? "#fbbf24" : "#475569" }),
    );
  }

  function Stickering(props) {
    var r = !!(props && props.running);
    return R.createElement(
      "svg",
      { viewBox: "0 0 220 92", className: "mes-mac-svg" },
      R.createElement("text", { x: 6, y: 12, fill: "#64748b", fontSize: 9 }, "Stickering"),
      R.createElement("circle", { cx: 52, cy: 52, r: 18, stroke: "#67e8f9", fill: "none", className: r ? "mes-mac-spin" : "" }),
      R.createElement("path", { d: "M78 54 H190", stroke: "#67e8f9", strokeDasharray: "3 4" }),
      R.createElement("rect", { x: 124, y: 42, width: 36, height: 18, rx: 4, stroke: "#c4b5fd", fill: "none" }),
    );
  }

  function BottleSeal(props) {
    var dim = !!(props && props.dimmed);
    return R.createElement(
      "svg",
      { viewBox: "0 0 220 92", style: { opacity: dim ? 0.45 : 0.92 }, className: "mes-mac-svg" },
      R.createElement("text", { x: 6, y: 12, fill: "#64748b", fontSize: 9 }, "Bottle sealing"),
      R.createElement("ellipse", { cx: 90, cy: 58, rx: 42, ry: 22, stroke: "#38bdf8", fill: "none" }),
      R.createElement("rect", { x: 112, y: 36, width: 22, height: 34, rx: 6, stroke: "#94a3b8", fill: "none" }),
      R.createElement("rect", { x: 126, y: 30, width: 46, height: 16, rx: 4, stroke: "#fb923c", fill: "rgba(251,146,60,0.1)" }),
    );
  }

  function Packaging(props) {
    var r = !!(props && props.running);
    return R.createElement(
      "svg",
      { viewBox: "0 0 220 92", className: "mes-mac-svg" },
      R.createElement("text", { x: 6, y: 12, fill: "#64748b", fontSize: 9 }, "Packaging"),
      R.createElement("rect", { x: 32, y: 34, width: 78, height: 44, rx: 4, stroke: "#67e8f9", fill: "none" }),
      R.createElement("rect", { x: 118, y: 36, width: 68, height: 28, rx: 4, stroke: "#38bdf8", strokeDasharray: "4 4" }),
      R.createElement("circle", { cx: 180, cy: 52, r: 6, stroke: "#fbbf24", fill: "rgba(251,191,36,0.1)", className: r ? "mes-mac-pulse" : "" }),
    );
  }

  global.MesMachineIllustrations = {
    DPP115BlisterMachine: DPP115,
    HeatPressMachine: HeatPress,
    StickeringMachine: Stickering,
    BottleSealingMachine: BottleSeal,
    PackagingStation: Packaging,
  };
})(typeof globalThis !== "undefined" ? globalThis : window);
