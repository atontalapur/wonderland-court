import { Filter } from "lucide-react";
import { useMemo, useState } from "react";
import {
  formatDefenseName,
  formatScenario,
  formatTacticLabel,
} from "../theme/wonderland";
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
    return "border-[#efe2cc] bg-[#faf4e8]/50 text-[#b4a48f]";
  }
  if (asr === 0) {
    return "border-[#9ad8be] bg-[#ecfdf5] text-[#065f46] hover:border-[#047857]";
  }
  if (asr <= 0.5) {
    return "border-[#f5c26b] bg-[#fef3c7] text-[#92400e] hover:border-[#d97706]";
  }
  return "border-[#f5b7c2] bg-[#ffe4e8] text-[#a5152e] hover:border-[#c81e3a]";
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
            scenarioFilter === "all"
              ? "All scenarios"
              : formatScenario(c.scenario).title,
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
    return null;
  }

  return (
    <div className="storybook-card overflow-hidden rounded-3xl">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#e9dcc6] bg-[#faf4e8]/70 px-6 py-4">
        <div>
          <h3 className="font-editorial text-lg font-bold text-[#231f1a]">
            Which Tricks Worked Against Which Shields
          </h3>
          <p className="text-xs text-[#6b5e4e]">
            Click any square to read that character exchange.
          </p>
        </div>

        <label className="inline-flex items-center gap-2 text-xs font-medium text-[#5c4f41]">
          <Filter className="h-3.5 w-3.5 text-[#8c7a64]" />
          <select
            aria-label="Filter heatmap by scenario"
            value={scenarioFilter}
            onChange={(e) =>
              setScenarioFilter(e.target.value as "all" | ScenarioId)
            }
            className="rounded-xl border border-[#dec8a4] bg-[#fffdf9] px-3 py-1.5 text-xs font-semibold text-[#3a3026] focus:border-[#2b5b84] focus:outline-none"
          >
            <option value="all">All Scenarios</option>
            {heatmap.scenarios.map((sc) => (
              <option key={sc} value={sc}>
                {formatScenario(sc).title}
              </option>
            ))}
          </select>
        </label>
      </div>

      {heatmap.families.length === 0 ? (
        <div className="p-6 text-center text-xs text-[#6b5e4e]">
          No attack tactics recorded yet.
        </div>
      ) : (
        <div className="overflow-x-auto p-5">
          <table className="w-full border-separate border-spacing-2 text-xs">
            <thead>
              <tr>
                <th className="px-2 py-1.5 text-left font-editorial text-xs font-bold text-[#5c4f41]">
                  Shield \ Trick
                </th>
                {heatmap.families.map((fam) => (
                  <th
                    key={fam}
                    className="px-2 py-1.5 text-center text-xs font-semibold text-[#4a3b2c]"
                  >
                    {formatTacticLabel(fam)}
                  </th>
                ))}
              </tr>
            </thead>

            <tbody>
              {heatmap.defenses.map((defense) => (
                <tr key={defense}>
                  <td className="whitespace-nowrap px-2 py-1.5 font-semibold text-[#231f1a]">
                    {formatDefenseName(defense)}
                  </td>

                  {heatmap.families.map((fam) => {
                    const cell = cellLookup.get(`${defense}::${fam}`);
                    const matches = cell?.matches ?? 0;
                    const leaks = cell?.leaks ?? 0;
                    const asr = cell?.asr ?? 0;

                    return (
                      <td key={fam} className="text-center">
                        <button
                          type="button"
                          disabled={!cell || matches === 0}
                          onClick={() => cell && onSelectCell(cell)}
                          data-testid={`heatmap-cell-${defense}-${fam}`}
                          className={`w-full min-w-[92px] rounded-xl border-2 px-2.5 py-2 transition ${cellColorClass(
                            asr,
                            matches
                          )} disabled:cursor-default`}
                        >
                          {matches > 0 ? (
                            <div className="flex flex-col items-center leading-tight">
                              <span className="text-xs font-bold">
                                {leaks === 0 ? "♣ Held" : "♥ Breached"}
                              </span>
                              <span className="mt-0.5 text-[11px] opacity-80">
                                {leaks}/{matches}
                              </span>
                            </div>
                          ) : (
                            <span className="text-xs">—</span>
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
