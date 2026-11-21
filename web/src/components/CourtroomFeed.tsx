import { KeyRound, Shield, Target } from "lucide-react";
import type { LiveMatchState } from "../state/streamAggregator";
import { MatchSidebar } from "./MatchSidebar";
import { TurnCard } from "./TurnCard";

interface CourtroomFeedProps {
  matches: LiveMatchState[];
  selectedMatchId: string | null;
  onSelectMatch: (matchId: string) => void;
  followLive: boolean;
  onToggleFollowLive: () => void;
}

export function CourtroomFeed({
  matches,
  selectedMatchId,
  onSelectMatch,
  followLive,
  onToggleFollowLive,
}: CourtroomFeedProps) {
  const activeMatch =
    matches.find((m) => m.match.match_id === selectedMatchId) ?? matches[0] ?? null;

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
      <div className="lg:col-span-4 xl:col-span-3">
        <MatchSidebar
          matches={matches}
          selectedMatchId={activeMatch?.match.match_id ?? null}
          onSelectMatch={onSelectMatch}
          followLive={followLive}
          onToggleFollowLive={onToggleFollowLive}
        />
      </div>

      <section className="lg:col-span-8 xl:col-span-9">
        {!activeMatch ? (
          <div className="court-card flex min-h-[320px] flex-col items-center justify-center rounded-xl p-8 text-center">
            <p className="font-editorial text-lg text-slate-300">
              Awaiting the first match in the Courtroom…
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Turns, Drink Me payloads, and Queen verdicts will appear here in real time.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Match Dossier Header */}
            <div className="court-card rounded-xl p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-bold text-amber-300">
                      {activeMatch.match.match_id}
                    </span>
                    <span className="inline-flex items-center gap-1 rounded-md border border-[#23293a] bg-[#0b0d14] px-2 py-0.5 font-mono text-xs text-slate-200">
                      <Shield className="h-3.5 w-3.5 text-emerald-400" />
                      {activeMatch.match.defense}
                    </span>
                    <span className="rounded-md border border-[#23293a] bg-[#0b0d14] px-2 py-0.5 font-mono text-xs text-slate-300">
                      {activeMatch.match.scenario}
                    </span>
                    <span className="inline-flex items-center gap-1 font-mono text-xs text-slate-400">
                      <Target className="h-3.5 w-3.5" />
                      {activeMatch.match.target}
                    </span>
                  </div>

                  <p className="mt-2 text-sm text-slate-300">
                    <span className="font-semibold text-slate-200">
                      Objective:{" "}
                    </span>
                    {activeMatch.stakes.objective}
                  </p>
                </div>

                <div className="flex flex-col items-end gap-1.5">
                  <span
                    className={`rounded px-2.5 py-1 font-editorial text-xs font-bold tracking-wider ${
                      activeMatch.status === "running"
                        ? "border border-amber-500/40 bg-amber-500/15 text-amber-300"
                        : activeMatch.broken
                          ? "court-stamp-leak bg-rose-600/20 text-rose-300"
                          : "court-stamp-held bg-emerald-600/20 text-emerald-300"
                    }`}
                  >
                    {activeMatch.status === "running"
                      ? "IN TRIAL"
                      : activeMatch.broken
                        ? `♥︎ OFF WITH HER HEAD (T${activeMatch.broken_on_turn ?? "?"})`
                        : "♣︎ HELD"}
                  </span>

                  <div className="inline-flex items-center gap-1.5 font-mono text-[11px] text-slate-400">
                    <KeyRound className="h-3 w-3 text-amber-400" />
                    <span>Canary: {activeMatch.stakes.canary}</span>
                    <span>·</span>
                    <span>Seed #{activeMatch.match.seed}</span>
                  </div>
                </div>
              </div>

              {activeMatch.stakes.tool_rules.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2 border-t border-[#23293a] pt-2.5">
                  {activeMatch.stakes.tool_rules.map((rule, i) => (
                    <span
                      key={i}
                      className="rounded border border-[#23293a] bg-[#0b0d14] px-2 py-0.5 font-mono text-[11px] text-slate-400"
                    >
                      Rule: <span className="text-slate-200">{rule.tool}</span>{" "}
                      — {rule.description}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Turns Timeline */}
            <div className="space-y-4">
              {activeMatch.liveTurns.length === 0 ? (
                <div className="court-card rounded-xl p-6 text-center text-xs text-slate-400">
                  Match initialized — awaiting Turn 1 from Cheshire Cat…
                </div>
              ) : (
                activeMatch.liveTurns.map((slot, idx) => {
                  const prevFamily =
                    idx > 0
                      ? activeMatch.liveTurns[idx - 1].attack?.family ?? null
                      : null;
                  return (
                    <TurnCard
                      key={slot.index}
                      slot={slot}
                      prevFamily={prevFamily}
                      canary={activeMatch.stakes.canary}
                    />
                  );
                })
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
