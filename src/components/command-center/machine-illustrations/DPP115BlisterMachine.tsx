import * as React from "react";

export function DPP115BlisterMachine({ running, dimmed }: { running: boolean; dimmed?: boolean }) {
  const g = "#22d3ee";
  const g2 = "#67e8f9";
  const mute = dimmed ? 0.45 : running ? 1 : 0.55;
  return (
    <svg
      className={`mes-svg-twin mes-svg-twin--dpp ${running ? "mes-svg-twin--run" : ""}`}
      viewBox="0 0 220 92"
      style={{ opacity: mute }}
      aria-hidden
    >
      <defs>
        <filter id="glow">
          <feGaussianBlur stdDeviation="1.2" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <text x={6} y={12} fill="#64748b" fontSize={9}>
        DPP115 · blister thermoformer
      </text>
      <g filter="url(#glow)" stroke={g} fill="none" strokeWidth={1}>
        {/* film roll */}
        <circle cx={28} cy={58} r={14} opacity={running ? 0.95 : 0.65} />
        <path d="M42 54 L118 54" strokeDasharray="4 3" />
        {/* forming platten */}
        <rect x={98} y={34} width={62} height={36} rx={2} />
        {/* conveyor */}
        <rect x={152} y={58} width={58} height={10} rx={2} opacity={0.95} stroke={g2} />
      </g>
      <circle
        cx={118}
        cy={52}
        r={6}
        fill="none"
        stroke={running ? "#4ade80" : "#64748b"}
        className={running ? "mes-svg-spin" : ""}
      />
      {/* counter badge */}
      <rect x={168} y={10} width={44} height={18} rx={2} fill="rgba(6,182,212,0.12)" stroke={g} />
      <text x={172} y={22} fill="#bae6fd" fontSize={8}>
        CTR
      </text>
      <circle cx={204} cy={18} r={5} fill={running ? "#22c55e" : "#64748b"} />
    </svg>
  );
}
