import * as React from "react";

export function PackagingStation({ running }: { running: boolean }) {
  const g = "#67e8f9";
  return (
    <svg
      className={`mes-svg-twin mes-svg-twin--pkg ${running ? "mes-svg-twin--run" : ""}`}
      viewBox="0 0 220 92"
      style={{ opacity: running ? 1 : 0.55 }}
      aria-hidden
    >
      <text x={6} y={12} fill="#64748b" fontSize={9}>
        Packaging bench
      </text>
      <rect x={32} y={34} width={78} height={44} rx={4} stroke={g} fill="rgba(103,232,249,0.05)" strokeWidth={1} />
      <polyline points="38,74 138,74 154,88" stroke="#94a3b8" fill="none" strokeWidth={1} />
      <rect x={116} y={36} width={68} height={28} rx={4} stroke="#38bdf8" strokeDasharray="3 4" opacity={running ? 0.95 : 0.65} />
      <circle cx={180} cy={48} r={6} stroke="#fbbf24" fill="rgba(251,191,36,0.12)" strokeWidth={1} className={running ? "mes-svg-pulse" : ""} />
    </svg>
  );
}
