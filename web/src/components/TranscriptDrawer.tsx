import { X } from "lucide-react";
import { useEffect, useState } from "react";
import type { LiveMatchState } from "../state/streamAggregator";
import { formatDefenseName, formatScenario } from "../theme/wonderland";
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
      className="fixed inset-0 z-50 flex justify-end bg-[#231f1a]/45 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-testid="transcript-drawer"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex h-full w-full max-w-3xl flex-col border-l-2 border-[#e4d2b4] bg-[#faf4e8] shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-[#e4d2b4] bg-[#fffdf9] px-6 py-4">
          <div>
            <h2 className="font-editorial text-lg font-bold text-[#231f1a]">
              {title}
            </h2>
            {subtitle && (
              <p className="mt-0.5 text-xs text-[#6b5e4e]">{subtitle}</p>
            )}
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close transcript drawer"
            className="rounded-xl border border-[#dec8a4] bg-[#faf4e8] p-1.5 text-[#5c4f41] transition hover:border-[#2b5b84] hover:text-[#2b5b84]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {matched.length > 1 && (
          <div className="flex flex-wrap gap-1.5 border-b border-[#e9dcc6] bg-[#faf4e8] px-6 py-2.5">
            {matched.map((m, idx) => {
              const selected = m.match.match_id === current?.match.match_id;
              return (
                <button
                  key={m.match.match_id}
                  type="button"
                  onClick={() => setActiveId(m.match.match_id)}
                  className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition ${
                    selected
                      ? "bg-[#2b5b84] text-white"
                      : "border border-[#dec8a4] bg-[#fffdf9] text-[#5c4f41] hover:border-[#2b5b84]"
                  }`}
                >
                  <span>Trial {idx + 1}</span>
                  <span>{m.broken ? "♥" : "♣"}</span>
                </button>
              );
            })}
          </div>
        )}

        <div className="flex-1 space-y-6 overflow-y-auto p-6">
          {!current ? (
            <div className="storybook-card rounded-2xl p-6 text-center text-sm text-[#6b5e4e]">
              Trial transcript not found.
            </div>
          ) : (
            <>
              <div className="storybook-card rounded-2xl p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2 text-sm font-bold text-[#231f1a]">
                    <span>{formatScenario(current.match.scenario).title}</span>
                    <span className="text-[#c5ad8c]">·</span>
                    <span className="text-[#2b5b84]">
                      {formatDefenseName(current.match.defense)}
                    </span>
                  </div>

                  <span
                    className={`rounded-lg px-2.5 py-0.5 font-editorial text-xs font-bold ${
                      current.broken
                        ? "court-stamp-leak bg-[#ffe2e7] text-[#a5152e]"
                        : "court-stamp-held bg-[#dcfce7] text-[#065f46]"
                    }`}
                  >
                    {current.broken ? "♥ Breached" : "♣ Alice Held"}
                  </span>
                </div>

                <p className="mt-1.5 text-xs text-[#5c4f41]">
                  {current.stakes.objective}
                </p>
              </div>

              <div className="storybook-card space-y-8 rounded-3xl p-5">
                {slots.map((slot, idx) => (
                  <div
                    key={slot.index}
                    className={
                      idx > 0
                        ? "border-t-2 border-dashed border-[#e9dcc6] pt-8"
                        : ""
                    }
                  >
                    <TurnCard
                      slot={slot}
                      prevFamily={
                        idx > 0 ? slots[idx - 1].attack?.family ?? null : null
                      }
                      canary={current.stakes.canary}
                    />
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
