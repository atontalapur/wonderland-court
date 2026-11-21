import { ArrowUpDown, Crown, Skull } from "lucide-react";
import { useMemo, useState } from "react";
import type { Standing } from "../types/events";

interface LeaderboardTableProps {
  standings: Standing[];
}

type SortKey =
  | "elo"
  | "defense"
  | "matches"
  | "attack_success"
  | "mean_turns_to_break"
  | "utility";

export function LeaderboardTable({ standings }: LeaderboardTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("elo");
  const [sortDesc, setSortDesc] = useState<boolean>(true);

  const topEloDefense = useMemo(() => {
    if (standings.length === 0) return null;
    const best = [...standings].sort((a, b) => b.elo - a.elo)[0];
    return best?.defense ?? null;
  }, [standings]);

  const sorted = useMemo(() => {
    const copy = [...standings];
    copy.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "defense":
          cmp = a.defense.localeCompare(b.defense);
          break;
        case "elo":
          cmp = a.elo - b.elo;
          break;
        case "matches":
          cmp = a.matches - b.matches;
          break;
        case "attack_success":
          cmp = a.attack_success - b.attack_success;
          break;
        case "mean_turns_to_break":
          cmp = (a.mean_turns_to_break ?? 999) - (b.mean_turns_to_break ?? 999);
          break;
        case "utility":
          cmp = (a.utility ?? -1) - (b.utility ?? -1);
          break;
      }
      return sortDesc ? -cmp : cmp;
    });
    return copy;
  }, [standings, sortKey, sortDesc]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDesc((d) => !d);
    } else {
      setSortKey(key);
      setSortDesc(key !== "defense" && key !== "attack_success");
    }
  };

  if (standings.length === 0) {
    return (
      <div className="court-card rounded-xl p-6 text-center text-sm text-slate-400">
        No defense standings computed yet.
      </div>
    );
  }

  return (
    <div className="court-card overflow-hidden rounded-xl">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#23293a] px-4 py-3">
        <div>
          <h3 className="font-editorial text-base font-bold text-slate-100">
            Defense Leaderboard
          </h3>
          <p className="text-xs text-slate-400">
            Ranked by pairwise Elo with 95% Wilson confidence intervals on
            Attack Success Rate (ASR) and Dodo benign-task utility.
          </p>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr className="border-b border-[#23293a] bg-[#0f121b] text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-4 py-3">Rank</th>
              <th className="px-4 py-3">
                <button
                  type="button"
                  onClick={() => handleSort("defense")}
                  className="inline-flex items-center gap-1 hover:text-white"
                >
                  Defense
                  <ArrowUpDown className="h-3 w-3" />
                </button>
              </th>
              <th className="px-4 py-3 text-right">
                <button
                  type="button"
                  onClick={() => handleSort("elo")}
                  className="inline-flex items-center gap-1 hover:text-white"
                >
                  Elo
                  <ArrowUpDown className="h-3 w-3" />
                </button>
              </th>
              <th className="px-4 py-3 text-right">
                <button
                  type="button"
                  onClick={() => handleSort("matches")}
                  className="inline-flex items-center gap-1 hover:text-white"
                >
                  Matches
                  <ArrowUpDown className="h-3 w-3" />
                </button>
              </th>
              <th className="min-w-[210px] px-4 py-3">
                <button
                  type="button"
                  onClick={() => handleSort("attack_success")}
                  className="inline-flex items-center gap-1 hover:text-white"
                >
                  ASR & 95% Wilson CI
                  <ArrowUpDown className="h-3 w-3" />
                </button>
              </th>
              <th className="px-4 py-3 text-right">
                <button
                  type="button"
                  onClick={() => handleSort("mean_turns_to_break")}
                  className="inline-flex items-center gap-1 hover:text-white"
                >
                  Mean Turns to Break
                  <ArrowUpDown className="h-3 w-3" />
                </button>
              </th>
              <th className="min-w-[150px] px-4 py-3">
                <button
                  type="button"
                  onClick={() => handleSort("utility")}
                  className="inline-flex items-center gap-1 hover:text-white"
                >
                  Dodo Utility
                  <ArrowUpDown className="h-3 w-3" />
                </button>
              </th>
            </tr>
          </thead>

          <tbody className="divide-y divide-[#23293a]/70">
            {sorted.map((row, idx) => {
              const isCrown = row.defense === topEloDefense;
              const isEliminated = row.attack_success >= 0.75;
              const asrPct = Math.round(row.attack_success * 100);
              const ciLowPct = Math.round(row.ci_low * 100);
              const ciHighPct = Math.round(row.ci_high * 100);
              const utilPct =
                row.utility !== null ? Math.round(row.utility * 100) : null;

              return (
                <tr
                  key={row.defense}
                  className="transition hover:bg-[#191f2e]/70"
                  data-testid={`leaderboard-row-${row.defense}`}
                >
                  <td className="px-4 py-3 font-mono text-slate-400">
                    {isCrown ? (
                      <span
                        className="inline-flex items-center gap-1 font-bold text-[#eab308]"
                        title="Elo #1 Champion"
                      >
                        <Crown className="h-4 w-4 text-[#eab308]" />
                        #1
                      </span>
                    ) : (
                      <span>#{idx + 1}</span>
                    )}
                  </td>

                  <td className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono font-semibold text-slate-100">
                        {row.defense}
                      </span>
                      {isEliminated && (
                        <span className="inline-flex items-center gap-1 rounded-full border border-rose-500/50 bg-rose-500/15 px-2 py-0.5 text-[10px] font-bold uppercase text-rose-300">
                          <Skull className="h-3 w-3" />
                          Eliminated
                        </span>
                      )}
                    </div>
                  </td>

                  <td
                    className={`px-4 py-3 text-right font-mono font-bold ${
                      isCrown ? "text-[#eab308]" : "text-slate-200"
                    }`}
                  >
                    {row.elo.toFixed(1)}
                  </td>

                  <td className="px-4 py-3 text-right font-mono text-slate-300">
                    {row.matches}
                  </td>

                  <td className="px-4 py-3">
                    <div className="flex items-center justify-between gap-2 font-mono text-[11px]">
                      <span
                        className={
                          row.attack_success === 0
                            ? "font-bold text-emerald-400"
                            : isEliminated
                              ? "font-bold text-rose-400"
                              : "font-semibold text-amber-300"
                        }
                      >
                        {asrPct}%
                      </span>
                      <span className="text-slate-500">
                        [{ciLowPct}% – {ciHighPct}%]
                      </span>
                    </div>
                    <div className="relative mt-1.5 h-2 w-full rounded-full bg-[#0b0d14]">
                      {/* Wilson 95% CI span */}
                      <div
                        className="absolute top-0 h-2 rounded-full bg-slate-600/60"
                        style={{
                          left: `${ciLowPct}%`,
                          width: `${Math.max(2, ciHighPct - ciLowPct)}%`,
                        }}
                      />
                      {/* Point estimate marker */}
                      <div
                        className={`absolute top-0 h-2 w-1.5 -translate-x-1/2 rounded-full ${
                          row.attack_success === 0
                            ? "bg-emerald-400"
                            : isEliminated
                              ? "bg-rose-500"
                              : "bg-amber-400"
                        }`}
                        style={{ left: `${Math.min(99, Math.max(1, asrPct))}%` }}
                      />
                    </div>
                  </td>

                  <td className="px-4 py-3 text-right font-mono text-slate-300">
                    {row.mean_turns_to_break !== null
                      ? row.mean_turns_to_break.toFixed(1)
                      : "—"}
                  </td>

                  <td className="px-4 py-3">
                    {utilPct !== null ? (
                      <div>
                        <div className="flex items-center justify-between font-mono text-[11px]">
                          <span className="font-semibold text-emerald-400">
                            {utilPct}%
                          </span>
                        </div>
                        <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-[#0b0d14]">
                          <div
                            className="h-full rounded-full bg-emerald-500"
                            style={{ width: `${utilPct}%` }}
                          />
                        </div>
                      </div>
                    ) : (
                      <span className="font-mono text-[11px] text-slate-500">
                        Pending
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
