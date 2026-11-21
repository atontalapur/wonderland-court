import { ArrowRight, GitCompare, ShieldCheck } from "lucide-react";
import type { RetrialComparisonView } from "../types/events";

interface RetrialDiffCardProps {
  retrial: RetrialComparisonView | null;
}

function readScenarioPair(metrics: Record<string, number>): {
  before: number;
  after: number;
} {
  const before =
    metrics.baseline_asr ??
    metrics.before_asr ??
    metrics.baseline ??
    metrics.before ??
    0;
  const after =
    metrics.retrial_asr ??
    metrics.after_asr ??
    metrics.retrial ??
    metrics.after ??
    0;
  return { before, after };
}

export function RetrialDiffCard({ retrial }: RetrialDiffCardProps) {
  if (!retrial) {
    return (
      <div
        className="court-card rounded-xl p-6"
        data-testid="retrial-empty-state"
      >
        <div className="flex items-start gap-3">
          <GitCompare className="mt-0.5 h-5 w-5 text-slate-400" />
          <div>
            <h3 className="font-editorial text-base font-bold text-slate-100">
              Seed-Matched Retrial Comparison
            </h3>
            <p className="mt-1 text-xs leading-relaxed text-slate-400">
              No retrial comparison has been recorded for this run yet. Apply the
              recommended config patch and run{" "}
              <code className="rounded bg-[#0b0d14] px-1.5 py-0.5 font-mono text-amber-300">
                court retrial
              </code>{" "}
              to measure before-vs-after ASR and Dodo utility on identical seeds.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const formatPct = (val: number) => `${Number((val * 100).toFixed(1))}%`;
  const baseAsrPct = formatPct(retrial.baseline_asr);
  const retrialAsrPct = formatPct(retrial.retrial_asr);
  const asrDeltaNum = Number((retrial.asr_delta * 100).toFixed(1));
  const scenarioEntries = Object.entries(retrial.per_scenario_diff ?? {});

  const baseUtilPct =
    retrial.baseline_utility !== null
      ? Math.round(retrial.baseline_utility * 100)
      : null;
  const retrialUtilPct =
    retrial.retrial_utility !== null
      ? Math.round(retrial.retrial_utility * 100)
      : null;
  const utilDeltaPct =
    baseUtilPct !== null && retrialUtilPct !== null
      ? retrialUtilPct - baseUtilPct
      : null;

  return (
    <div
      className="court-card space-y-4 rounded-xl p-5"
      data-testid="retrial-diff-card"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#23293a] pb-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-emerald-400" />
          <div>
            <h3 className="font-editorial text-base font-bold text-slate-100">
              Seed-Matched Retrial Comparison
            </h3>
            <p className="font-mono text-xs text-slate-400">
              {retrial.baseline_run_id} → {retrial.retrial_run_id} ·{" "}
              {retrial.matched_seeds.length} matched seeds
            </p>
          </div>
        </div>

        <span
          className={`rounded-full border px-3 py-1 font-mono text-xs font-bold ${
            asrDeltaNum <= 0
              ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
              : "border-rose-500/40 bg-rose-500/15 text-rose-300"
          }`}
        >
          ASR Δ {asrDeltaNum > 0 ? `+${asrDeltaNum}%` : `${asrDeltaNum}%`}
        </span>
      </div>

      {/* Top KPI summary */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-[#23293a] bg-[#0b0d14] p-4">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Attack Success Rate (Lower is Safer)
          </div>
          <div className="mt-2 flex items-center gap-3 font-mono">
            <span className="text-lg font-bold text-rose-400">
              {baseAsrPct}
            </span>
            <ArrowRight className="h-4 w-4 text-slate-500" />
            <span className="text-lg font-bold text-emerald-400">
              {retrialAsrPct}
            </span>
          </div>
        </div>

        <div className="rounded-lg border border-[#23293a] bg-[#0b0d14] p-4">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Dodo Benign Utility (Higher is Better)
          </div>
          <div className="mt-2 flex items-center gap-3 font-mono">
            {baseUtilPct !== null && retrialUtilPct !== null ? (
              <>
                <span className="text-lg font-bold text-slate-300">
                  {baseUtilPct}%
                </span>
                <ArrowRight className="h-4 w-4 text-slate-500" />
                <span className="text-lg font-bold text-emerald-400">
                  {retrialUtilPct}%
                </span>
                {utilDeltaPct !== null && (
                  <span className="text-xs text-slate-400">
                    ({utilDeltaPct >= 0 ? `+${utilDeltaPct}%` : `${utilDeltaPct}%`})
                  </span>
                )}
              </>
            ) : (
              <span className="text-sm text-slate-500">
                Dodo utility not recorded
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Per-scenario bars */}
      {scenarioEntries.length > 0 && (
        <div className="space-y-3 pt-1">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Per-Scenario ASR Before vs. After
          </h4>
          {scenarioEntries.map(([scenario, metrics]) => {
            const { before, after } = readScenarioPair(metrics);
            const beforePct = Math.max(0, Math.min(100, Number((before * 100).toFixed(1))));
            const afterPct = Math.max(0, Math.min(100, Number((after * 100).toFixed(1))));

            return (
              <div
                key={scenario}
                className="rounded-lg border border-[#23293a] bg-[#0b0d14] p-3"
              >
                <div className="mb-2 flex items-center justify-between font-mono text-xs">
                  <span className="font-semibold text-slate-200">
                    {scenario}
                  </span>
                  <span className="text-slate-400">
                    {beforePct.toFixed(1)}% →{" "}
                    <span className="font-bold text-emerald-400">
                      {afterPct.toFixed(1)}%
                    </span>
                  </span>
                </div>

                <div className="space-y-1.5">
                  <div className="flex items-center gap-2 text-[10px] font-mono text-slate-400">
                    <span className="w-12">Before</span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-[#191f2e]">
                      <div
                        className="h-full rounded-full bg-rose-500"
                        style={{ width: `${beforePct}%` }}
                      />
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] font-mono text-slate-400">
                    <span className="w-12">After</span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-[#191f2e]">
                      <div
                        className="h-full rounded-full bg-emerald-500"
                        style={{ width: `${afterPct}%` }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
