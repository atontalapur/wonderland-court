import { ArrowRight, GitCompare, ShieldCheck } from "lucide-react";
import { formatScenario } from "../theme/wonderland";
import type { RetrialComparisonView, ScenarioId } from "../types/events";

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
        className="storybook-card rounded-3xl p-6"
        data-testid="retrial-empty-state"
      >
        <div className="flex items-start gap-3">
          <GitCompare className="mt-0.5 h-5 w-5 text-[#8c7a64]" />
          <div>
            <h3 className="font-editorial text-base font-bold text-[#231f1a]">
              Before & After Retrial
            </h3>
            <p className="mt-1 text-xs leading-relaxed text-[#6b5e4e]">
              Once you apply the Caterpillar’s patch, run{" "}
              <code className="rounded bg-[#f2e7d3] px-1.5 py-0.5 font-mono text-[#8c3f0b]">
                court retrial
              </code>{" "}
              to replay the exact same attacks and verify Alice holds firm.
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

  return (
    <div
      className="storybook-card space-y-4 rounded-3xl p-6"
      data-testid="retrial-diff-card"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#e9dcc6] pb-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-[#047857]" />
          <div>
            <h3 className="font-editorial text-lg font-bold text-[#231f1a]">
              Before & After Retrial
            </h3>
            <p className="text-xs text-[#6b5e4e]">
              {retrial.matched_seeds.length} matched trials replayed
            </p>
          </div>
        </div>

        <span
          className={`rounded-full border px-3 py-1 font-mono text-xs font-bold ${
            asrDeltaNum <= 0
              ? "border-[#9ad8be] bg-[#dcfce7] text-[#065f46]"
              : "border-[#f5b7c2] bg-[#ffe4e8] text-[#a5152e]"
          }`}
        >
          ASR Δ {asrDeltaNum > 0 ? `+${asrDeltaNum}%` : `${asrDeltaNum}%`}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-2xl border border-[#e9dcc6] bg-[#faf4e8]/70 p-4">
          <div className="text-xs font-semibold text-[#5c4f41]">
            Breach Rate (Lower is Safer)
          </div>
          <div className="mt-2 flex items-center gap-3 font-editorial text-xl font-bold">
            <span className="text-[#c81e3a]">{baseAsrPct}</span>
            <ArrowRight className="h-4 w-4 text-[#8c7a64]" />
            <span className="text-[#047857]">{retrialAsrPct}</span>
          </div>
        </div>

        <div className="rounded-2xl border border-[#e9dcc6] bg-[#faf4e8]/70 p-4">
          <div className="text-xs font-semibold text-[#5c4f41]">
            Helpfulness (Higher is Better)
          </div>
          <div className="mt-2 flex items-center gap-3 font-editorial text-xl font-bold">
            {baseUtilPct !== null && retrialUtilPct !== null ? (
              <>
                <span className="text-[#5c4f41]">{baseUtilPct}%</span>
                <ArrowRight className="h-4 w-4 text-[#8c7a64]" />
                <span className="text-[#047857]">{retrialUtilPct}%</span>
              </>
            ) : (
              <span className="font-sans text-sm font-normal text-[#8c7a64]">
                Not measured
              </span>
            )}
          </div>
        </div>
      </div>

      {scenarioEntries.length > 0 && (
        <div className="space-y-3 pt-1">
          {scenarioEntries.map(([scenario, metrics]) => {
            const { before, after } = readScenarioPair(metrics);
            const beforePct = Math.max(
              0,
              Math.min(100, Number((before * 100).toFixed(1)))
            );
            const afterPct = Math.max(
              0,
              Math.min(100, Number((after * 100).toFixed(1)))
            );
            const label = formatScenario(scenario as ScenarioId).title;

            return (
              <div
                key={scenario}
                className="rounded-2xl border border-[#e9dcc6] bg-[#fffdf9] p-3.5"
              >
                <div className="mb-2 flex items-center justify-between text-xs">
                  <span className="font-semibold text-[#231f1a]">{label}</span>
                  <span className="font-mono text-[#6b5e4e]">
                    {beforePct.toFixed(1)}% →{" "}
                    <span className="font-bold text-[#047857]">
                      {afterPct.toFixed(1)}%
                    </span>
                  </span>
                </div>

                <div className="space-y-1.5">
                  <div className="flex items-center gap-2 text-[11px] text-[#6b5e4e]">
                    <span className="w-12">Before</span>
                    <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-[#efe2cc]">
                      <div
                        className="h-full rounded-full bg-[#c81e3a]"
                        style={{ width: `${beforePct}%` }}
                      />
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] text-[#6b5e4e]">
                    <span className="w-12">After</span>
                    <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-[#efe2cc]">
                      <div
                        className="h-full rounded-full bg-[#047857]"
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
