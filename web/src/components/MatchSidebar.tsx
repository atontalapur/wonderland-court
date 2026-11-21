import { Radio } from "lucide-react";
import { useState } from "react";
import type { LiveMatchState } from "../state/streamAggregator";

interface MatchSidebarProps {
  matches: LiveMatchState[];
  selectedMatchId: string | null;
  onSelectMatch: (matchId: string) => void;
  followLive: boolean;
  onToggleFollowLive: () => void;
}

type MatchFilter = "all" | "broken" | "held" | "running";

export function MatchSidebar({
  matches,
  selectedMatchId,
  onSelectMatch,
  followLive,
  onToggleFollowLive,
}: MatchSidebarProps) {
  const [filter, setFilter] = useState<MatchFilter>("all");

  const filtered = matches.filter((m) =>
    filter === "all" ? true : m.status === filter
  );

  return (
    <aside className="court-card flex h-full flex-col rounded-xl">
      <div className="border-b border-[#23293a] p-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-editorial text-base font-semibold text-slate-100">
            Trial Docket ({matches.length})
          </h2>
          <button
            type="button"
            onClick={onToggleFollowLive}
            aria-pressed={followLive}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold transition ${
              followLive
                ? "border-rose-500/50 bg-rose-500/15 text-rose-300"
                : "border-[#23293a] bg-[#0b0d14] text-slate-400 hover:text-slate-200"
            }`}
          >
            <Radio
              className={`h-3 w-3 ${followLive ? "animate-pulse text-rose-400" : ""}`}
            />
            Follow Live
          </button>
        </div>

        <div className="mt-2.5 flex flex-wrap gap-1">
          {(["all", "broken", "held", "running"] as MatchFilter[]).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={`rounded-md px-2 py-0.5 text-[11px] font-medium capitalize transition ${
                filter === f
                  ? "bg-[#23293a] text-white"
                  : "text-slate-400 hover:bg-[#191f2e] hover:text-slate-200"
              }`}
            >
              {f === "broken" ? "Off With Her Head" : f}
            </button>
          ))}
        </div>
      </div>

      <div className="max-h-[680px] flex-1 space-y-1.5 overflow-y-auto p-2">
        {filtered.length === 0 ? (
          <div className="px-3 py-6 text-center text-xs text-slate-500">
            No matches match this filter yet.
          </div>
        ) : (
          filtered.map((m) => {
            const active = m.match.match_id === selectedMatchId;
            return (
              <button
                key={m.match.match_id}
                type="button"
                onClick={() => onSelectMatch(m.match.match_id)}
                className={`w-full rounded-lg border p-2.5 text-left transition ${
                  active
                    ? "border-amber-500/60 bg-[#191f2e]"
                    : "border-[#23293a]/70 bg-[#0b0d14]/70 hover:border-[#313a52] hover:bg-[#131722]"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-bold text-slate-200">
                    {m.match.match_id}
                  </span>

                  {m.status === "running" ? (
                    <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 text-[10px] font-bold uppercase text-amber-300">
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" />
                      LIVE
                    </span>
                  ) : m.broken ? (
                    <span className="rounded-full border border-rose-500/50 bg-rose-500/15 px-2 py-0.5 text-[10px] font-bold uppercase text-rose-300">
                      OFF WITH HER HEAD
                    </span>
                  ) : (
                    <span className="rounded-full border border-emerald-500/40 bg-emerald-500/15 px-2 py-0.5 text-[10px] font-bold uppercase text-emerald-300">
                      HELD
                    </span>
                  )}
                </div>

                <div className="mt-1.5 truncate font-mono text-xs text-slate-300">
                  {m.match.defense}
                </div>

                <div className="mt-1.5 flex flex-wrap items-center justify-between gap-1 text-[11px]">
                  <span className="rounded border border-[#23293a] bg-[#131722] px-1.5 py-0.5 font-mono text-slate-400">
                    {m.match.scenario}
                  </span>

                  {m.broken && m.broken_on_turn !== null ? (
                    <span className="font-mono text-rose-300">
                      Broken T{m.broken_on_turn}
                    </span>
                  ) : (
                    <span className="font-mono text-slate-500">
                      {m.liveTurns.length}/{m.match.max_turns} turns
                    </span>
                  )}
                </div>
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}
