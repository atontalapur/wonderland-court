import { Bug, ExternalLink } from "lucide-react";
import { formatScenario, formatTacticLabel } from "../theme/wonderland";
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
      <div className="storybook-card rounded-3xl p-6 text-center text-sm font-semibold text-[#047857]">
        ♣ Zero failure patterns found — Alice held every trial!
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="failure-clusters">
      <div className="flex items-center justify-between">
        <h3 className="font-editorial text-lg font-bold text-[#231f1a]">
          Where Alice Was Tricked ({clusters.length})
        </h3>
        <span className="text-xs text-[#6b5e4e]">
          Click an example to read the exchange
        </span>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {clusters.map((cluster) => (
          <div
            key={cluster.cluster_id}
            className="storybook-card flex flex-col justify-between rounded-2xl p-5"
            data-testid={`cluster-card-${cluster.cluster_id}`}
          >
            <div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Bug className="h-4 w-4 text-[#c81e3a]" />
                  <h4 className="font-editorial text-base font-bold text-[#231f1a]">
                    {cluster.family_label}
                  </h4>
                </div>
                <span className="rounded-full border border-[#f5b7c2] bg-[#ffe4e8] px-2.5 py-0.5 text-xs font-bold text-[#a5152e]">
                  {cluster.count} {cluster.count === 1 ? "breach" : "breaches"}
                </span>
              </div>

              <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                <span className="rounded-full border border-[#ddd6fe] bg-[#f5f3ff] px-2.5 py-0.5 font-semibold text-[#5b21b6]">
                  {formatTacticLabel(cluster.technique_family)}
                </span>
                <span className="rounded-full border border-[#e4d2b4] bg-[#faf4e8] px-2.5 py-0.5 font-semibold text-[#5c4f41]">
                  {formatScenario(cluster.scenario).title}
                </span>
              </div>

              <p className="mt-3 text-xs leading-relaxed text-[#4a3b2c]">
                {cluster.root_cause_summary}
              </p>
            </div>

            {cluster.example_match_ids.length > 0 && (
              <div className="mt-3.5 flex flex-wrap items-center gap-1.5 border-t border-[#efe2cc] pt-3">
                <span className="text-[11px] font-medium text-[#6b5e4e]">
                  Inspect:
                </span>
                {cluster.example_match_ids.map((mid) => (
                  <button
                    key={mid}
                    type="button"
                    onClick={() =>
                      onInspectMatches(
                        [
                          mid,
                          ...cluster.example_match_ids.filter((x) => x !== mid),
                        ],
                        `${cluster.family_label}`,
                        `${formatTacticLabel(cluster.technique_family)} · ${formatScenario(cluster.scenario).title}`
                      )
                    }
                    className="inline-flex items-center gap-1 rounded-full border border-[#b7cfe8] bg-[#eff6ff] px-2.5 py-0.5 font-mono text-[11px] font-semibold text-[#1e4568] transition hover:bg-[#dbeafe]"
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
