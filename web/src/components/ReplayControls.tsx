import { Pause, Play, RotateCcw } from "lucide-react";
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

  return (
    <div
      className="flex flex-wrap items-center gap-3 rounded-2xl border border-[#e4d2b4] bg-[#faf4e8] px-4 py-2.5 shadow-sm"
      data-testid="replay-controls"
    >
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={isPlaying ? onPause : onPlay}
          aria-label={isPlaying ? "Pause replay" : "Play replay"}
          className="inline-flex items-center gap-1.5 rounded-xl border border-[#d6be96] bg-[#fffdf9] px-3 py-1.5 text-xs font-semibold text-[#231f1a] transition hover:border-[#2b5b84] hover:text-[#2b5b84]"
        >
          {isPlaying ? (
            <>
              <Pause className="h-3.5 w-3.5 text-[#b45309]" />
              <span>Pause</span>
            </>
          ) : (
            <>
              <Play className="h-3.5 w-3.5 text-[#047857]" />
              <span>Play</span>
            </>
          )}
        </button>

        <button
          type="button"
          onClick={onRestart}
          aria-label="Restart replay"
          className="inline-flex items-center gap-1 rounded-xl border border-[#e4d2b4] bg-[#fffdf9] px-2.5 py-1.5 text-xs font-medium text-[#5c4f41] transition hover:border-[#b49464] hover:text-[#231f1a]"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          <span>Restart</span>
        </button>
      </div>

      <div
        className="flex items-center rounded-xl border border-[#e4d2b4] bg-[#fffdf9] p-0.5"
        role="group"
        aria-label="Replay speed"
      >
        {SPEEDS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onSpeedChange(s)}
            aria-pressed={speed === s}
            className={`rounded-lg px-2 py-1 font-mono text-xs font-semibold transition ${
              speed === s
                ? "bg-[#2b5b84] text-white"
                : "text-[#6b5e4e] hover:text-[#231f1a]"
            }`}
          >
            {s}x
          </button>
        ))}
      </div>

      <div className="flex min-w-[180px] flex-1 items-center gap-3">
        <div className="relative flex flex-1 items-center py-1">
          <input
            type="range"
            aria-label="Replay event scrubber"
            min={0}
            max={totalEvents}
            value={cursor}
            onChange={(e) => onSeek(Number(e.target.value))}
            className="peer absolute inset-0 z-10 h-full w-full cursor-pointer opacity-0"
          />
          <div
            role="presentation"
            data-testid="replay-scrubber-bar"
            className="h-2.5 w-full overflow-hidden rounded-full border border-[#dec8a4] bg-[#fffdf9] peer-focus-visible:ring-2 peer-focus-visible:ring-[#2b5b84]"
          >
            <div
              className="h-full bg-gradient-to-r from-[#2b5b84] via-[#d97706] to-[#c81e3a] transition-all duration-150"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>

        <span
          className="whitespace-nowrap font-mono text-xs font-medium text-[#5c4f41]"
          data-testid="replay-progress"
        >
          Event {cursor} / {totalEvents}
        </span>
      </div>

      {onExitReplay && (
        <button
          type="button"
          onClick={onExitReplay}
          className="rounded-xl border border-[#dec8a4] bg-[#fffdf9] px-3 py-1 text-xs font-semibold text-[#5c4f41] transition hover:border-[#2b5b84] hover:text-[#2b5b84]"
        >
          Show Full Run
        </button>
      )}
    </div>
  );
}
