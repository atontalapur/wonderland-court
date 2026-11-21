import { X } from "lucide-react";
import { useEffect, useState } from "react";
import type { LiveMatchState } from "../state/streamAggregator";
import type { MatchTranscript } from "../types/events";
import { TurnCard } from "./TurnCard";

type AnyMatch = LiveMatchState | MatchTranscript;

interface TranscriptDrawerProps {
  isOpen: boolean;
  title: string;
  subtitle?: string;
  matchIds: string[];
  matches: AnyMatch[];
  onClose: () => void;
}

function toLiveSlots(match: AnyMatch) {
  if ("liveTurns" in match) {
    return match.liveTurns;
  }
  return match.turns.map((t) => ({
    index: t.index,
    attack: t.attack,
    reply: t.reply,
    verdict: t.verdict,
  }));
}

export function TranscriptDrawer({
  isOpen,
  title,
  subtitle,
  matchIds,
  matches,
  onClose,
}: TranscriptDrawerProps) {
  const [activeId, setActiveId] = useState<string | null>(matchIds[0] ?? null);

  useEffect(() => {
    setActiveId(matchIds[0] ?? null);
  }, [matchIds, isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const matched = matches.filter((m) => matchIds.includes(m.match.match_id));
  const current =
    matched.find((m) => m.match.match_id === activeId) ?? matched[0] ?? null;
  const slots = current ? toLiveSlots(current) : [];

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/70 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-testid="transcript-drawer"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex h-full w-full max-w-3xl flex-col border-l border-[#23293a] bg-[#0b0d14] shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-[#23293a] bg-[#131722] px-5 py-4">
          <div>
            <h2 className="font-editorial text-lg font-bold text-slate-100">
              {title}
            </h2>
            {subtitle && (
              <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>
            )}
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close transcript drawer"
            className="rounded-lg border border-[#23293a] bg-[#0b0d14] p-1.5 text-slate-400 transition hover:border-slate-500 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {matched.length > 1 && (
          <div className="flex flex-wrap gap-1.5 border-b border-[#23293a] bg-[#0f121b] px-5 py-2.5">
            {matched.map((m) => {
              const selected = m.match.match_id === current?.match.match_id;
              return (
                <button
                  key={m.match.match_id}
                  type="button"
                  onClick={() => setActiveId(m.match.match_id)}
                  className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 font-mono text-xs transition ${
                    selected
                      ? "border-amber-500/60 bg-amber-500/15 text-amber-200"
                      : "border-[#23293a] bg-[#131722] text-slate-300 hover:border-slate-500"
                  }`}
                >
                  <span>{m.match.match_id}</span>
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      m.broken ? "bg-rose-500" : "bg-emerald-500"
                    }`}
                  />
                </button>
              );
            })}
          </div>
        )}

        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          {!current ? (
            <div className="court-card rounded-xl p-6 text-center text-sm text-slate-400">
              Transcript not found for selected match IDs:{" "}
              <span className="font-mono">{matchIds.join(", ")}</span>
            </div>
          ) : (
            <>
              <div className="court-card rounded-xl p-4 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2 font-mono">
                    <span className="font-bold text-amber-300">
                      {current.match.match_id}
                    </span>
                    <span className="text-slate-400">·</span>
                    <span className="text-slate-200">
                      {current.match.defense}
                    </span>
                    <span className="text-slate-400">·</span>
                    <span className="text-slate-300">
                      {current.match.scenario}
                    </span>
                    <span className="text-slate-400">·</span>
                    <span className="text-slate-400">
                      seed {current.match.seed}
                    </span>
                  </div>

                  <span
                    className={`rounded px-2 py-0.5 font-editorial text-xs font-bold ${
                      current.broken
                        ? "court-stamp-leak bg-rose-600/20 text-rose-300"
                        : "court-stamp-held bg-emerald-600/20 text-emerald-300"
                    }`}
                  >
                    {current.broken
                      ? `♥︎ OFF WITH HER HEAD (T${current.broken_on_turn ?? "?"})`
                      : "♣︎ HELD"}
                  </span>
                </div>

                <p className="mt-2 text-slate-300">
                  <span className="font-semibold text-slate-200">
                    Objective:{" "}
                  </span>
                  {current.stakes.objective}
                </p>
                <p className="mt-1 font-mono text-[11px] text-slate-400">
                  Canary: {current.stakes.canary}
                </p>
              </div>

              {slots.map((slot, idx) => (
                <TurnCard
                  key={slot.index}
                  slot={slot}
                  prevFamily={
                    idx > 0 ? slots[idx - 1].attack?.family ?? null : null
                  }
                  canary={current.stakes.canary}
                />
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
