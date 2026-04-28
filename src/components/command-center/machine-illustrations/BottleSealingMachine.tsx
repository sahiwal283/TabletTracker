import * as React from "react";

export function BottleSealingMachine({ running, dimmed }: { running: boolean; dimmed?: boolean }) {
  const g = "#38bdf8";
  const op = dimmed ? 0.42 : running ? 1 : 0.55;
  return (
    <svg
      className={`mes-svg-twin mes-svg-twin--bottle ${running ? "mes-svg-twin--run" : ""}`}
      viewBox="0 0 220 92"
      style={{ opacity: op }}
      aria-hidden
    >
      <text x={6} y={12} fill="#64748b" fontSize={9}>
        Bottle sealing / capper
      </text>
      <ellipse cx={90} cy={58} rx={42} ry={22} stroke={g} fill="rgba(56,189,248,0.06)" strokeWidth={1} />
      <ellipse cx={90} cy={72} rx={56} ry={14} stroke="#64748b" fill="none" strokeWidth={1} opacity={0.7} />
      <path d="M90 42 V 28 Q90 22 104 26" stroke={g} fill="none" />
      {/* bottle */}
      <rect x={112} y={36} width={22} height={34} rx={6} stroke="#94a3b8" opacity={running ? 0.95 : 0.65} />
      <rect x={128} y={30} width={46} height={16} rx={4} stroke="#fb923c" fill="rgba(251,146,60,0.12)" strokeWidth={1} />
      <circle cx={168} cy={22} r={5} fill={running ? "#4ade80" : "#475569"} className={running ? "mes-svg-pulse" : ""} />
    </svg>
  );
}
