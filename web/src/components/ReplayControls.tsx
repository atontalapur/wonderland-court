import { Pause, Play, RotateCcw } from "lucide-react";
import type { MouseEvent } from "react";
import type { ReplaySpeed } from "../api/sse";

interface ReplayControlsProps {
  isPlaying: boolean;
  speed: ReplaySpeed;
  cursor: number;
  totalEvents: number;
  onPlay: () => void;
  onPause: () => void;
  onRestart: () => void;
  onSeek: (index: number) => void;
  onSpeedChange: (speed: ReplaySpeed) => void;
  onExitReplay?: () => void;
}

const SPEEDS: ReplaySpeed[] = [1, 2, 4];

export function ReplayControls({
  isPlaying,
  speed,
  cursor,
  totalEvents,
  onPlay,
  onPause,
  onRestart,
  onSeek,
  onSpeedChange,
  onExitReplay,
}: ReplayControlsProps) {
  const pct = totalEvents > 0 ? Math.round((cursor / totalEvents) * 100) : 0;

  const handleBarClick = (e: MouseEvent<HTMLDivElement>) => {
    if (totalEvents <= 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    onSeek(Math.round(ratio * totalEvents));
  };

  return (
    <div
      className="flex flex-wrap items-center gap-3 rounded-xl border border-[#23293a] bg-[#131722]/95 px-4 py-2.5 shadow-lg"
      data-testid="replay-controls"
    >
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={isPlaying ? onPause : onPlay}
          aria-label={isPlaying ? "Pause replay" : "Play replay"}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[#23293a] bg-[#191f2e] px-3 py-1.5 text-xs font-semibold text-slate-100 transition hover:border-amber-400/50 hover:text-amber-300"
        >
          {isPlaying ? (
            <>
              <Pause className="h-3.5 w-3.5 text-amber-400" />
              <span>Pause</span>
            </>
          ) : (
            <>
              <Play className="h-3.5 w-3.5 text-emerald-400" />
              <span>Play</span>
            </>
          )}
        </button>

        <button
          type="button"
          onClick={onRestart}
          aria-label="Restart replay"
          className="inline-flex items-center gap-1 rounded-lg border border-[#23293a] bg-[#191f2e] px-2.5 py-1.5 text-xs font-medium text-slate-300 transition hover:border-slate-500 hover:text-white"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          <span>Restart</span>
        </button>
      </div>

      <div
        className="flex items-center rounded-lg border border-[#23293a] bg-[#0b0d14] p-0.5"
        role="group"
        aria-label="Replay speed"
      >
        {SPEEDS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onSpeedChange(s)}
            aria-pressed={speed === s}
            className={`rounded-md px-2 py-1 font-mono text-xs font-medium transition ${
              speed === s
                ? "bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/40"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {s}x
          </button>
        ))}
      </div>

      <div className="flex min-w-[180px] flex-1 items-center gap-3">
        <div className="relative flex-1">
          <div
            role="presentation"
            data-testid="replay-scrubber-bar"
            onClick={handleBarClick}
            className="h-2.5 w-full cursor-pointer overflow-hidden rounded-full border border-[#23293a] bg-[#0b0d14]"
          >
            <div
              className="h-full bg-gradient-to-r from-amber-500 via-rose-500 to-emerald-500 transition-all duration-150"
              style={{ width: `${pct}%` }}
            />
          </div>
          <input
            type="range"
            aria-label="Replay event scrubber"
            min={0}
            max={totalEvents}
            value={cursor}
            onChange={(e) => onSeek(Number(e.target.value))}
            className="sr-only"
          />
        </div>

        <span
          className="whitespace-nowrap font-mono text-xs text-slate-300"
          data-testid="replay-progress"
        >
          Event {cursor} / {totalEvents}
        </span>
      </div>

      {onExitReplay && (
        <button
          type="button"
          onClick={onExitReplay}
          className="rounded-lg border border-[#23293a] px-2.5 py-1 text-xs text-slate-400 transition hover:border-slate-500 hover:text-slate-200"
        >
          Show Full Run
        </button>
      )}
    </div>
  );
}
