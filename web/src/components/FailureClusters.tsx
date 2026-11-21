import { Bug, ExternalLink } from "lucide-react";
import type { FailureClusterView } from "../types/events";

interface FailureClustersProps {
  clusters: FailureClusterView[];
  onInspectMatches: (
    matchIds: string[],
    title: string,
    subtitle?: string
  ) => void;
}

export function FailureClusters({
  clusters,
  onInspectMatches,
}: FailureClustersProps) {
  if (clusters.length === 0) {
    return (
      <div className="court-card rounded-xl p-6 text-center text-sm text-emerald-300">
        Zero failure clusters detected — Alice held every trial!
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="failure-clusters">
      <div className="flex items-center justify-between">
        <h3 className="font-editorial text-base font-bold text-slate-100">
          Deduplicated Failure Clusters ({clusters.length})
        </h3>
        <span className="text-xs text-slate-400">
          Click any match ID to inspect the full transcript
        </span>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {clusters.map((cluster) => (
          <div
            key={cluster.cluster_id}
            className="court-card flex flex-col justify-between rounded-xl p-4"
            data-testid={`cluster-card-${cluster.cluster_id}`}
          >
            <div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Bug className="h-4 w-4 text-rose-400" />
                  <h4 className="font-semibold text-slate-100">
                    {cluster.family_label}
                  </h4>
                </div>
                <span className="rounded-full border border-rose-500/40 bg-rose-500/15 px-2.5 py-0.5 font-mono text-xs font-bold text-rose-300">
                  {cluster.count} {cluster.count === 1 ? "leak" : "leaks"}
                </span>
              </div>

              <div className="mt-2 flex flex-wrap gap-1.5 font-mono text-[11px]">
                <span className="rounded border border-purple-500/35 bg-purple-500/10 px-2 py-0.5 text-purple-300">
                  {cluster.technique_family}
                </span>
                <span className="rounded border border-[#23293a] bg-[#0b0d14] px-2 py-0.5 text-slate-300">
                  {cluster.scenario}
                </span>
              </div>

              <p className="mt-2.5 text-xs leading-relaxed text-slate-300">
                {cluster.root_cause_summary}
              </p>
            </div>

            {cluster.example_match_ids.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-[#23293a] pt-2.5">
                <span className="text-[11px] text-slate-400">Examples:</span>
                {cluster.example_match_ids.map((mid) => (
                  <button
                    key={mid}
                    type="button"
                    onClick={() =>
                      onInspectMatches(
                        [mid, ...cluster.example_match_ids.filter((x) => x !== mid)],
                        `${cluster.family_label} — Transcript`,
                        `${cluster.technique_family} · ${cluster.scenario}`
                      )
                    }
                    className="inline-flex items-center gap-1 rounded border border-[#23293a] bg-[#0b0d14] px-2 py-0.5 font-mono text-[11px] text-amber-300 transition hover:border-amber-400/60 hover:bg-amber-500/10"
                  >
                    <span>{mid}</span>
                    <ExternalLink className="h-2.5 w-2.5" />
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
