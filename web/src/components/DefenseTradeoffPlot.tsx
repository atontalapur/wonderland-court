import { useState } from "react";
import type { Standing } from "../types/events";

interface DefenseTradeoffPlotProps {
  standings: Standing[];
}

const WIDTH = 520;
const HEIGHT = 300;
const PAD_L = 54;
const PAD_R = 24;
const PAD_T = 24;
const PAD_B = 46;
const PLOT_W = WIDTH - PAD_L - PAD_R;
const PLOT_H = HEIGHT - PAD_T - PAD_B;

export function DefenseTradeoffPlot({ standings }: DefenseTradeoffPlotProps) {
  const [hovered, setHovered] = useState<string | null>(null);

  if (standings.length === 0) {
    return null;
  }

  const topElo = [...standings].sort((a, b) => b.elo - a.elo)[0]?.defense;
  const hasAnyUtility = standings.some((s) => s.utility !== null);

  return (
    <div className="court-card rounded-xl p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-editorial text-base font-bold text-slate-100">
            Security vs. Dodo Utility Trade-Off
          </h3>
          <p className="text-xs text-slate-400">
            Top-right quadrant maximizes both Security (1 − ASR) and benign
            task Helpfulness.
          </p>
        </div>
        {!hasAnyUtility && (
          <span className="rounded-full border border-[#23293a] bg-[#0b0d14] px-2.5 py-0.5 text-[11px] text-slate-400">
            Utility pending Dodo eval (plotted at 50% baseline)
          </span>
        )}
      </div>

      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-auto w-full select-none"
        role="img"
        aria-label="Defense Security vs Utility Tradeoff Scatter Plot"
      >
        {/* Optimal top-right quadrant (>=75% security & >=75% utility) */}
        <rect
          x={PAD_L + PLOT_W * 0.75}
          y={PAD_T}
          width={PLOT_W * 0.25}
          height={PLOT_H * 0.25}
          fill="rgba(16, 185, 129, 0.08)"
          stroke="rgba(16, 185, 129, 0.28)"
          strokeDasharray="4 4"
        />
        <text
          x={PAD_L + PLOT_W * 0.875}
          y={PAD_T + 14}
          textAnchor="middle"
          fill="#34d399"
          fontSize="9"
          fontFamily="ui-monospace, monospace"
        >
          IDEAL
        </text>

        {/* Grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const x = PAD_L + t * PLOT_W;
          const y = PAD_T + (1 - t) * PLOT_H;
          return (
            <g key={t}>
              <line
                x1={PAD_L}
                y1={y}
                x2={PAD_L + PLOT_W}
                y2={y}
                stroke="#23293a"
                strokeWidth="1"
              />
              <line
                x1={x}
                y1={PAD_T}
                x2={x}
                y2={PAD_T + PLOT_H}
                stroke="#23293a"
                strokeWidth="1"
              />
              <text
                x={PAD_L - 8}
                y={y + 3}
                textAnchor="end"
                fill="#94a3b8"
                fontSize="10"
                fontFamily="ui-monospace, monospace"
              >
                {Math.round(t * 100)}%
              </text>
              <text
                x={x}
                y={PAD_T + PLOT_H + 16}
                textAnchor="middle"
                fill="#94a3b8"
                fontSize="10"
                fontFamily="ui-monospace, monospace"
              >
                {Math.round(t * 100)}%
              </text>
            </g>
          );
        })}

        {/* Axis labels */}
        <text
          x={PAD_L + PLOT_W / 2}
          y={HEIGHT - 6}
          textAnchor="middle"
          fill="#cbd5e1"
          fontSize="11"
        >
          Dodo Helpfulness / Utility →
        </text>
        <text
          x={14}
          y={PAD_T + PLOT_H / 2}
          textAnchor="middle"
          fill="#cbd5e1"
          fontSize="11"
          transform={`rotate(-90 14 ${PAD_T + PLOT_H / 2})`}
        >
          Security (1 − ASR) →
        </text>

        {/* Points */}
        {(() => {
          const seenBuckets = new Map<string, number>();
          return standings.map((s) => {
            const security = 1 - s.attack_success;
            const util = s.utility ?? 0.5;
            const cx = PAD_L + util * PLOT_W;
            const cy = PAD_T + (1 - security) * PLOT_H;
            const bucketKey = `${Math.round(cx / 18)}:${Math.round(cy / 16)}`;
            const overlapIdx = seenBuckets.get(bucketKey) ?? 0;
            seenBuckets.set(bucketKey, overlapIdx + 1);
            const isTop = s.defense === topElo;
            const isEliminated = s.attack_success >= 0.75;
            const fill = isTop
              ? "#eab308"
              : isEliminated
                ? "#e11d48"
                : "#10b981";
            const isHovered = hovered === s.defense;
            const labelAnchor = util > 0.72 ? "end" : "start";
            const labelDx = util > 0.72 ? -10 : 10;
            const labelDy =
              cy > PAD_T + PLOT_H * 0.55
                ? 3 - overlapIdx * 13
                : 3 + overlapIdx * 13;

            return (
              <g
                key={s.defense}
                className="cursor-pointer"
                onMouseEnter={() => setHovered(s.defense)}
                onMouseLeave={() => setHovered(null)}
              >
                {isTop && (
                  <circle
                    cx={cx}
                    cy={cy}
                    r={12}
                    fill="none"
                    stroke="#eab308"
                    strokeOpacity={0.45}
                    strokeWidth={1.5}
                  />
                )}
                <circle
                  cx={cx}
                  cy={cy}
                  r={isHovered ? 8 : 6.5}
                  fill={fill}
                  stroke="#0b0d14"
                  strokeWidth={2}
                  strokeDasharray={s.utility === null ? "2 2" : undefined}
                />
                <text
                  x={cx + labelDx}
                  y={cy + labelDy}
                  textAnchor={labelAnchor}
                  fill="#e2e8f0"
                  fontSize="10.5"
                  fontFamily="ui-monospace, monospace"
                >
                  {s.defense}
                </text>
              </g>
            );
          });
        })()}
      </svg>
    </div>
  );
}
