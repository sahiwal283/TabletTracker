import * as React from "react";

export function HeatPressMachine({ running, variant }: { running: boolean; variant?: string; dimmed?: boolean }) {
  const g = "#22d3ee";
  const op = running ? 1 : 0.55;
  return (
    <svg
      className={`mes-svg-twin mes-svg-twin--heat ${running ? "mes-svg-twin--run" : ""}`}
      viewBox="0 0 220 92"
      style={{ opacity: op }}
      aria-hidden
    >
      <text x={6} y={12} fill="#64748b" fontSize={9}>
        Heat seal press {variant ?? ""}
      </text>
      <g stroke={g} fill="none" strokeWidth={1}>
        {/* top plate */}
        <rect x={40} y={22} width={140} height={18} rx={3} opacity={0.95} />
        {/* frame */}
        <path d="M48 52 L172 52" stroke="#94a3b8" opacity={0.6} strokeWidth={1.2} />
        {/* lower tray */}
        <rect x={44} y={56} width={132} height={18} rx={3} opacity={0.9} stroke="#fde68a" />
        {/* vertical compression */}
        {[66, 110, 154].map((cx) => (
          <React.Fragment key={cx}>
            <path d={`M${cx} 40 V 56`} stroke="#f97316" strokeDasharray="2 3" opacity={running ? 0.9 : 0.35} />
            <path d={`M${cx} 78 V 92`} stroke="#f97316" strokeDasharray="2 3" opacity={running ? 0.9 : 0.35} />
          </React.Fragment>
        ))}
      </g>
      <circle cx={178} cy={24} r={5} fill={running ? "#fbbf24" : "#475569"} className={running ? "mes-svg-pulse" : ""} />
    </svg>
  );
}
