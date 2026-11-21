import { Crown, ShieldAlert, ShieldCheck } from "lucide-react";
import { useMemo } from "react";
import { CHARACTERS, formatDefenseName } from "../theme/wonderland";
import type { Standing } from "../types/events";
import { CharacterAvatar } from "./CharacterAvatar";

interface LeaderboardTableProps {
  standings: Standing[];
}

export function LeaderboardTable({ standings }: LeaderboardTableProps) {
  const sorted = useMemo(() => {
    return [...standings].sort((a, b) => {
      if (b.elo !== a.elo) return b.elo - a.elo;
      if (a.attack_success !== b.attack_success)
        return a.attack_success - b.attack_success;
      return a.defense.localeCompare(b.defense);
    });
  }, [standings]);

  if (sorted.length === 0) {
    return (
      <div className="storybook-card rounded-3xl p-8 text-center text-sm text-[#6b5e4e]">
        No defense scores yet — watch a trial first!
      </div>
    );
  }

  const champion = sorted[0];
  const championBlockedPct = Math.round((1 - champion.attack_success) * 100);

  return (
    <div className="space-y-5">
      {/* Winner Spotlight Card */}
      <div className="storybook-card flex flex-col items-center gap-4 rounded-3xl bg-gradient-to-r from-[#fffdf9] via-[#f4f8fd] to-[#fffdf9] p-5 sm:flex-row sm:justify-between sm:px-7">
        <div className="flex items-center gap-4">
          <CharacterAvatar
            character={CHARACTERS.alice}
            size="md"
            showLabel={false}
          />
          <div>
            <div className="inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-[#b45309]">
              <Crown className="h-4 w-4 text-[#d97706]" />
              Strongest Defense
            </div>
            <h2 className="mt-0.5 font-editorial text-2xl font-bold text-[#231f1a]">
              {formatDefenseName(champion.defense)}
            </h2>
            <p className="text-sm text-[#5c4f41]">
              Blocked <strong className="text-[#047857]">{championBlockedPct}%</strong>{" "}
              of attacks across {champion.matches} trials
              {champion.utility !== null
                ? ` while staying ${Math.round(champion.utility * 100)}% helpful.`
                : "."}
            </p>
          </div>
        </div>

        <div className="rounded-2xl border border-[#b7cfe8] bg-[#eff6ff] px-5 py-3 text-center">
          <div className="text-[11px] font-bold uppercase tracking-wider text-[#1e4568]">
            Score
          </div>
          <div className="font-editorial text-2xl font-bold text-[#2b5b84]">
            {Math.round(champion.elo)}
          </div>
        </div>
      </div>

      {/* Simple Visual Defense Ranking */}
      <div className="storybook-card overflow-hidden rounded-3xl">
        <div className="border-b border-[#e9dcc6] bg-[#faf4e8]/70 px-6 py-4">
          <h3 className="font-editorial text-lg font-bold text-[#231f1a]">
            How Each Shield Held Up
          </h3>
          <p className="text-xs text-[#6b5e4e]">
            Higher block rate means Alice resisted more Wonderland tricks.
          </p>
        </div>

        <div className="divide-y divide-[#efe2cc]">
          {sorted.map((row, idx) => {
            const isChampion = idx === 0;
            const isEliminated = row.attack_success >= 0.75;
            const blockedPct = Math.round((1 - row.attack_success) * 100);
            const breachPct = Math.round(row.attack_success * 100);
            const utilPct =
              row.utility !== null ? Math.round(row.utility * 100) : null;

            return (
              <div
                key={row.defense}
                data-testid={`leaderboard-row-${row.defense}`}
                className="flex flex-col gap-3 px-6 py-4 transition hover:bg-[#faf4e8]/50 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="flex items-center gap-3.5">
                  <div
                    className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full font-editorial text-sm font-bold ${
                      isChampion
                        ? "bg-[#fef3c7] text-[#b45309] ring-2 ring-[#f5c26b]"
                        : "bg-[#f2e7d3] text-[#5c4f41]"
                    }`}
                  >
                    #{idx + 1}
                  </div>

                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-editorial text-base font-bold text-[#231f1a]">
                        {formatDefenseName(row.defense)}
                      </span>
                      {isEliminated && (
                        <span className="inline-flex items-center gap-1 rounded-full border border-[#f5b7c2] bg-[#ffe4e8] px-2.5 py-0.5 text-[11px] font-bold text-[#a5152e]">
                          <ShieldAlert className="h-3 w-3" />
                          Eliminated
                        </span>
                      )}
                      {blockedPct === 100 && (
                        <span className="inline-flex items-center gap-1 rounded-full border border-[#9ad8be] bg-[#dcfce7] px-2.5 py-0.5 text-[11px] font-bold text-[#065f46]">
                          <ShieldCheck className="h-3 w-3" />
                          Unbroken
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-[#6b5e4e]">
                      {row.matches} trials · {breachPct}% breached
                      {utilPct !== null ? ` · ${utilPct}% helpful` : ""}
                    </div>
                  </div>
                </div>

                {/* Clean Block Rate Bar */}
                <div className="w-full sm:w-64">
                  <div className="mb-1 flex items-center justify-between text-xs font-semibold">
                    <span className="text-[#5c4f41]">Attacks Blocked</span>
                    <span
                      className={
                        blockedPct >= 75
                          ? "text-[#047857]"
                          : blockedPct > 25
                            ? "text-[#b45309]"
                            : "text-[#c81e3a]"
                      }
                    >
                      {blockedPct}%
                    </span>
                  </div>
                  <div className="h-3 w-full overflow-hidden rounded-full bg-[#efe2cc]">
                    <div
                      className={`h-full rounded-full transition-all duration-300 ${
                        blockedPct >= 75
                          ? "bg-[#047857]"
                          : blockedPct > 25
                            ? "bg-[#d97706]"
                            : "bg-[#c81e3a]"
                      }`}
                      style={{ width: `${Math.max(4, blockedPct)}%` }}
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
