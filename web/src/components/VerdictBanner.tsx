import type { Verdict } from "../types/events";

interface VerdictBannerProps {
  verdict: Verdict;
}

const LAYER_LABELS: Record<Verdict["layer"], string> = {
  canary: "CANARY",
  tool_call: "TOOL_CALL",
  similarity: "SIMILARITY",
  llm: "LLM",
};

export function VerdictBanner({ verdict }: VerdictBannerProps) {
  const isLeak = verdict.ruling === "leak";

  return (
    <div
      className={`mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border px-3.5 py-2.5 ${
        isLeak
          ? "border-rose-500/50 bg-rose-950/25"
          : "border-emerald-500/35 bg-emerald-950/20"
      }`}
      data-testid="verdict-banner"
    >
      <div className="flex flex-wrap items-center gap-2.5">
        <span
          className={`inline-flex items-center gap-1.5 rounded px-2.5 py-1 font-editorial text-xs font-bold tracking-wider ${
            isLeak
              ? "court-stamp-leak bg-rose-600/20 text-rose-300"
              : "court-stamp-held bg-emerald-600/20 text-emerald-300"
          }`}
        >
          {isLeak ? "♥︎ OFF WITH HER HEAD!" : "♣︎ HELD"}
        </span>

        <span className="rounded border border-[#23293a] bg-[#0b0d14] px-2 py-0.5 font-mono text-[11px] font-semibold text-slate-300">
          {LAYER_LABELS[verdict.layer]}
        </span>

        <span className="font-mono text-xs text-slate-400">
          {Math.round(verdict.confidence * 100)}% conf
        </span>
      </div>

      <p className="text-xs text-slate-300">{verdict.reason}</p>
    </div>
  );
}
