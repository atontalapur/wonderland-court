import { Scale } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { CalibrationSummary } from "../types/events";

interface CalibrationBadgeProps {
  calibration: CalibrationSummary | null;
}

export function CalibrationBadge({ calibration }: CalibrationBadgeProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };
    const handleMouseDown = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("mousedown", handleMouseDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("mousedown", handleMouseDown);
    };
  }, [open]);

  if (!calibration) {
    return (
      <div
        className="inline-flex items-center gap-1.5 rounded-full border border-[#23293a] bg-[#131722] px-3 py-1 text-xs text-slate-400"
        title="Queen of Hearts LLM-vs-exact ground-truth calibration has not run yet"
      >
        <Scale className="h-3.5 w-3.5 text-slate-500" />
        <span>Calibration: N/A</span>
      </div>
    );
  }

  const pct = Math.round(calibration.agreement_rate * 100);
  const tone =
    pct >= 90
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
      : pct >= 75
        ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
        : "border-rose-500/40 bg-rose-500/10 text-rose-300";

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition hover:brightness-110 ${tone}`}
        aria-expanded={open}
        title="Queen of Hearts Judge Calibration vs Exact Ground Truth"
      >
        <Scale className="h-3.5 w-3.5" />
        <span>
          Judge Calibration: {pct}% ({calibration.agreement_count}/
          {calibration.llm_evaluated})
        </span>
      </button>

      {open && (
        <div className="absolute right-0 z-40 mt-2 w-72 rounded-xl border border-[#23293a] bg-[#131722] p-3.5 text-xs shadow-2xl">
          <div className="mb-2 flex items-center justify-between border-b border-[#23293a] pb-2">
            <span className="font-semibold text-slate-200">
              Queen Judge Calibration
            </span>
            <span className="font-mono text-emerald-400">{pct}% agree</span>
          </div>
          <dl className="grid grid-cols-2 gap-y-1.5 text-slate-300">
            <dt className="text-slate-400">Exact Checked</dt>
            <dd className="text-right font-mono">
              {calibration.total_exact_checked}
            </dd>
            <dt className="text-slate-400">LLM Evaluated</dt>
            <dd className="text-right font-mono">{calibration.llm_evaluated}</dd>
            <dt className="text-slate-400">Agreements</dt>
            <dd className="text-right font-mono text-emerald-400">
              {calibration.agreement_count}
            </dd>
            <dt className="text-slate-400">False Positives</dt>
            <dd className="text-right font-mono text-amber-300">
              {calibration.false_positives}
            </dd>
            <dt className="text-slate-400">False Negatives</dt>
            <dd className="text-right font-mono text-rose-400">
              {calibration.false_negatives}
            </dd>
          </dl>
        </div>
      )}
    </div>
  );
}
