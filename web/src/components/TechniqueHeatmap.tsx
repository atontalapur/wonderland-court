import { Filter } from "lucide-react";
import { useMemo, useState } from "react";
import type { HeatmapCell, HeatmapData, ScenarioId } from "../types/events";

interface AggregatedCellView {
  defense: string;
  family: string;
  matches: number;
  leaks: number;
  asr: number;
  match_ids: string[];
  scenarioLabel: string;
}

interface TechniqueHeatmapProps {
  heatmap: HeatmapData | null;
  onSelectCell: (cell: AggregatedCellView) => void;
}

function cellColorClass(asr: number, matches: number): string {
  if (matches === 0) {
    return "border-[#23293a]/50 bg-[#0b0d14]/50 text-slate-600";
  }
  if (asr === 0) {
    return "border-emerald-500/40 bg-emerald-500/15 text-emerald-300 hover:border-emerald-400";
  }
  if (asr <= 0.5) {
    return "border-amber-500/45 bg-amber-500/15 text-amber-200 hover:border-amber-400";
  }
  return "border-rose-500/55 bg-rose-600/25 text-rose-200 hover:border-rose-400";
}

export function TechniqueHeatmap({
  heatmap,
  onSelectCell,
}: TechniqueHeatmapProps) {
  const [scenarioFilter, setScenarioFilter] = useState<"all" | ScenarioId>("all");

  const cellLookup = useMemo(() => {
    const map = new Map<string, AggregatedCellView>();
    if (!heatmap) return map;

    for (const c of heatmap.cells) {
      if (scenarioFilter !== "all" && c.scenario !== scenarioFilter) {
        continue;
      }
      const key = `${c.defense}::${c.family}`;
      const existing = map.get(key);
      if (!existing) {
        map.set(key, {
          defense: c.defense,
          family: c.family,
          matches: c.matches,
          leaks: c.leaks,
          asr: c.asr,
          match_ids: [...c.match_ids],
          scenarioLabel:
            scenarioFilter === "all" ? "All scenarios" : c.scenario,
        });
      } else {
        const mergedIds = Array.from(
          new Set([...existing.match_ids, ...c.match_ids])
        );
        const matches = existing.matches + c.matches;
        const leaks = existing.leaks + c.leaks;
        map.set(key, {
          defense: c.defense,
          family: c.family,
          matches,
          leaks,
          asr: matches > 0 ? leaks / matches : 0,
          match_ids: mergedIds,
          scenarioLabel: "All scenarios",
        });
      }
    }
    return map;
  }, [heatmap, scenarioFilter]);

  if (!heatmap || heatmap.defenses.length === 0) {
    return (
      <div className="court-card rounded-xl p-6 text-center text-sm text-slate-400">
        Technique heatmap will appear once attacks are recorded.
      </div>
    );
  }

  return (
    <div className="court-card overflow-hidden rounded-xl">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#23293a] px-4 py-3">
        <div>
          <h3 className="font-editorial text-base font-bold text-slate-100">
            Defense × Technique Family Heatmap
          </h3>
          <p className="text-xs text-slate-400">
            Click any cell to inspect the underlying match transcripts.
          </p>
        </div>

        <label className="inline-flex items-center gap-2 text-xs text-slate-300">
          <Filter className="h-3.5 w-3.5 text-slate-400" />
          <span>Scenario</span>
          <select
            aria-label="Filter heatmap by scenario"
            value={scenarioFilter}
            onChange={(e) =>
              setScenarioFilter(e.target.value as "all" | ScenarioId)
            }
            className="rounded-lg border border-[#23293a] bg-[#0b0d14] px-2.5 py-1 font-mono text-xs text-slate-200 focus:border-amber-400 focus:outline-none"
          >
            <option value="all">All Scenarios</option>
            {heatmap.scenarios.map((sc) => (
              <option key={sc} value={sc}>
                {sc}
              </option>
            ))}
          </select>
        </label>
      </div>

      {heatmap.families.length === 0 ? (
        <div className="p-6 text-center text-xs text-slate-400">
          No attack families attempted yet.
        </div>
      ) : (
        <div className="overflow-x-auto p-4">
          <table className="w-full border-separate border-spacing-1.5 text-xs">
            <thead>
              <tr>
                <th className="px-2 py-1.5 text-left font-mono text-[11px] uppercase tracking-wider text-slate-400">
                  Defense \ Family
                </th>
                {heatmap.families.map((fam) => (
                  <th
                    key={fam}
                    className="px-2 py-1.5 text-center font-mono text-[11px] text-slate-300"
                  >
                    {fam}
                  </th>
                ))}
              </tr>
            </thead>

            <tbody>
              {heatmap.defenses.map((defense) => (
                <tr key={defense}>
                  <td className="whitespace-nowrap px-2 py-1.5 font-mono font-semibold text-slate-200">
                    {defense}
                  </td>

                  {heatmap.families.map((fam) => {
                    const cell = cellLookup.get(`${defense}::${fam}`);
                    const matches = cell?.matches ?? 0;
                    const leaks = cell?.leaks ?? 0;
                    const asr = cell?.asr ?? 0;
                    const pct = Math.round(asr * 100);

                    return (
                      <td key={fam} className="text-center">
                        <button
                          type="button"
                          disabled={!cell || matches === 0}
                          onClick={() => cell && onSelectCell(cell)}
                          data-testid={`heatmap-cell-${defense}-${fam}`}
                          className={`w-full min-w-[84px] rounded-lg border px-2 py-2 font-mono transition ${cellColorClass(
                            asr,
                            matches
                          )} disabled:cursor-default`}
                        >
                          {matches > 0 ? (
                            <div className="flex flex-col items-center leading-tight">
                              <span className="text-xs font-bold">{pct}%</span>
                              <span className="mt-0.5 text-[10px] opacity-80">
                                {leaks}/{matches} leaks
                              </span>
                            </div>
                          ) : (
                            <span className="text-[11px]">—</span>
                          )}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export type { HeatmapCell, AggregatedCellView };
