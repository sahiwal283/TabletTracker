import * as React from "react";

export function StickeringMachine({ running }: { running: boolean }) {
  const g = "#67e8f9";
  return (
    <svg
      className={`mes-svg-twin ${running ? "mes-svg-twin--run" : ""}`}
      viewBox="0 0 220 92"
      style={{ opacity: running ? 1 : 0.55 }}
      aria-hidden
    >
      <text x={6} y={12} fill="#64748b" fontSize={9}>
        Stickering / card
      </text>
      <circle cx={52} cy={48} r={18} stroke={g} fill="none" strokeWidth={1} />
      <circle cx={52} cy={48} r={8} stroke="#a855f7" fill="none" className={running ? "mes-svg-spin-slow" : ""} />
      <path d="M74 54 H190" stroke={g} strokeDasharray="3 4" opacity={running ? 0.95 : 0.55} />
      <rect x={124} y={42} width={36} height={18} rx={4} stroke="#c4b5fd" />
      <polygon points="170,54 178,54 174,61" stroke="#fcd34d" fill="rgba(251,191,36,0.15)" strokeWidth={1} />
    </svg>
  );
}
