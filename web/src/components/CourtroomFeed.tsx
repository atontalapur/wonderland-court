import {
  ChevronLeft,
  ChevronRight,
  Layers,
  Shield,
  Sparkles,
} from "lucide-react";
import { useEffect, useState } from "react";
import type { LiveMatchState } from "../state/streamAggregator";
import {
  CHARACTERS,
  formatDefenseName,
  formatScenario,
} from "../theme/wonderland";
import { CharacterAvatar } from "./CharacterAvatar";
import { TurnCard } from "./TurnCard";

interface CourtroomFeedProps {
  matches: LiveMatchState[];
  selectedMatchId: string | null;
  onSelectMatch: (matchId: string) => void;
  followLive: boolean;
  onToggleFollowLive: () => void;
  onNextChapter?: () => void;
}

export function CourtroomFeed({
  matches,
  selectedMatchId,
  onSelectMatch,
  onNextChapter,
}: CourtroomFeedProps) {
  const activeIdx = Math.max(
    0,
    matches.findIndex((m) => m.match.match_id === selectedMatchId)
  );
  const activeMatch = matches[activeIdx] ?? matches[0] ?? null;

  const [turnIdx, setTurnIdx] = useState<number>(0);
  const [showAllTurns, setShowAllTurns] = useState<boolean>(false);

  // Reset turn step to 0 whenever the user switches to a different case
  useEffect(() => {
    setTurnIdx(0);
  }, [activeMatch?.match.match_id]);

  // Clamp turnIdx if turns array shrinks (e.g., during replay seek)
  const totalTurns = activeMatch?.liveTurns.length ?? 0;
  const safeTurnIdx =
    totalTurns > 0 ? Math.min(turnIdx, totalTurns - 1) : 0;

  if (!activeMatch) {
    return (
      <div className="storybook-card flex min-h-[340px] flex-col items-center justify-center rounded-3xl p-8 text-center">
        <CharacterAvatar character={CHARACTERS.rabbit} size="lg" showLabel={false} />
        <h2 className="mt-4 font-editorial text-xl font-bold text-[#231f1a]">
          The Courtroom is Preparing…
        </h2>
        <p className="mt-1.5 max-w-md text-sm text-[#6b5e4e]">
          The White Rabbit is gathering the first trial. Characters and chat
          bubbles will appear here as soon as the session begins.
        </p>
      </div>
    );
  }

  const scenarioMeta = formatScenario(activeMatch.match.scenario);
  const defenseLabel = formatDefenseName(activeMatch.match.defense);
  const isFirstCase = activeIdx === 0;
  const isLastCase = activeIdx >= matches.length - 1;
  const isFirstTurn = safeTurnIdx === 0;
  const isLastTurn = totalTurns === 0 || safeTurnIdx >= totalTurns - 1;

  const goToCase = (index: number) => {
    const target = matches[index];
    if (target) {
      onSelectMatch(target.match.match_id);
      setTurnIdx(0);
    }
  };

  const handlePrevClick = () => {
    if (!showAllTurns && !isFirstTurn) {
      setTurnIdx(safeTurnIdx - 1);
    } else if (!isFirstCase) {
      goToCase(activeIdx - 1);
    }
  };

  const handleNextClick = () => {
    if (!showAllTurns && !isLastTurn) {
      setTurnIdx(safeTurnIdx + 1);
    } else if (!isLastCase) {
      goToCase(activeIdx + 1);
    } else if (onNextChapter) {
      onNextChapter();
    }
  };

  const nextButtonLabel =
    !showAllTurns && !isLastTurn
      ? `Next Turn (${safeTurnIdx + 2} of ${totalTurns})`
      : !isLastCase
        ? `Next Trial (${activeIdx + 2} of ${matches.length})`
        : "See the Scoreboard";

  const prevButtonLabel =
    !showAllTurns && !isFirstTurn ? "Previous Turn" : "Previous Trial";

  const prevDisabled = (showAllTurns || isFirstTurn) && isFirstCase;

  return (
    <div className="space-y-5">
      {/* Compact Linear Case Picker Bar */}
      <div className="storybook-card flex flex-wrap items-center justify-between gap-3 rounded-2xl px-4 py-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={isFirstCase}
            onClick={() => goToCase(activeIdx - 1)}
            aria-label="Previous trial"
            className="inline-flex h-8 w-8 items-center justify-center rounded-xl border border-[#e4d2b4] bg-[#faf4e8] text-[#4a3b2c] transition hover:border-[#2b5b84] hover:text-[#2b5b84] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>

          <span className="font-editorial text-sm font-bold text-[#231f1a]">
            Trial {activeIdx + 1} of {matches.length}
          </span>

          <button
            type="button"
            disabled={isLastCase}
            onClick={() => goToCase(activeIdx + 1)}
            aria-label="Next trial"
            className="inline-flex h-8 w-8 items-center justify-center rounded-xl border border-[#e4d2b4] bg-[#faf4e8] text-[#4a3b2c] transition hover:border-[#2b5b84] hover:text-[#2b5b84] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>

        {/* Clickable Case Dots */}
        <div
          className="flex flex-wrap items-center gap-1.5"
          role="tablist"
          aria-label="Select trial"
        >
          {matches.map((m, idx) => {
            const selected = idx === activeIdx;
            const statusSymbol =
              m.status === "running" ? "…" : m.broken ? "♥" : "♣";
            const statusColor =
              m.status === "running"
                ? "text-[#b45309]"
                : m.broken
                  ? "text-[#c81e3a]"
                  : "text-[#047857]";

            return (
              <button
                key={m.match.match_id}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => goToCase(idx)}
                title={`${formatScenario(m.match.scenario).title} · ${formatDefenseName(m.match.defense)}`}
                className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold transition ${
                  selected
                    ? "bg-[#2b5b84] text-white shadow-sm"
                    : "border border-[#e4d2b4] bg-[#faf4e8] text-[#5c4f41] hover:border-[#cfb489]"
                }`}
              >
                <span>{idx + 1}</span>
                <span className={selected ? "text-white/90" : statusColor}>
                  {statusSymbol}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Main Storybook Trial Stage */}
      <section className="storybook-card overflow-hidden rounded-3xl">
        {/* Case Header Banner */}
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#e9dcc6] bg-[#faf4e8]/70 px-5 py-4 sm:px-7">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-lg" aria-hidden="true">
                {scenarioMeta.emoji}
              </span>
              <h2 className="font-editorial text-xl font-bold text-[#231f1a]">
                {scenarioMeta.title}
              </h2>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-[#b7cfe8] bg-[#eff6ff] px-3 py-0.5 text-xs font-semibold text-[#1e4568]">
                <Shield className="h-3.5 w-3.5" />
                {defenseLabel}
              </span>
            </div>
            <p className="mt-1 text-sm text-[#5c4f41]">
              {activeMatch.stakes.objective}
            </p>
          </div>

          <span
            className={`rounded-xl px-3 py-1.5 font-editorial text-xs font-bold tracking-wide ${
              activeMatch.status === "running"
                ? "border border-[#f5c26b] bg-[#fef3c7] text-[#92400e]"
                : activeMatch.broken
                  ? "court-stamp-leak bg-[#ffe2e7] text-[#a5152e]"
                  : "court-stamp-held bg-[#dcfce7] text-[#065f46]"
            }`}
          >
            {activeMatch.status === "running"
              ? "In Session"
              : activeMatch.broken
                ? "♥ Breached"
                : "♣ Alice Held"}
          </span>
        </div>

        {/* Character Conversation Area */}
        <div className="p-5 sm:p-7">
          {totalTurns === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-center">
              <CharacterAvatar
                character={CHARACTERS.cheshire}
                size="md"
                showLabel={false}
              />
              <p className="mt-3 font-editorial text-base font-bold text-[#3a3026]">
                Awaiting Turn 1…
              </p>
              <p className="mt-1 text-xs text-[#6b5e4e]">
                The Cheshire Cat is preparing an opening trick.
              </p>
            </div>
          ) : showAllTurns ? (
            <div className="space-y-8">
              {activeMatch.liveTurns.map((slot, idx) => (
                <div
                  key={slot.index}
                  className={
                    idx > 0 ? "border-t-2 border-dashed border-[#e9dcc6] pt-8" : ""
                  }
                >
                  <TurnCard
                    slot={slot}
                    prevFamily={
                      idx > 0
                        ? activeMatch.liveTurns[idx - 1].attack?.family ?? null
                        : null
                    }
                    canary={activeMatch.stakes.canary}
                  />
                </div>
              ))}
            </div>
          ) : (
            <TurnCard
              key={`${activeMatch.match.match_id}-${activeMatch.liveTurns[safeTurnIdx].index}`}
              slot={activeMatch.liveTurns[safeTurnIdx]}
              prevFamily={
                safeTurnIdx > 0
                  ? activeMatch.liveTurns[safeTurnIdx - 1].attack?.family ?? null
                  : null
              }
              canary={activeMatch.stakes.canary}
            />
          )}
        </div>

        {/* Linear Bottom Stepper Footer */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#e9dcc6] bg-[#faf4e8]/80 px-5 py-4 sm:px-7">
          <button
            type="button"
            disabled={prevDisabled}
            onClick={handlePrevClick}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[#dec8a4] bg-[#fffdf9] px-4 py-2 text-sm font-semibold text-[#4a3b2c] transition hover:border-[#2b5b84] hover:text-[#2b5b84] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronLeft className="h-4 w-4" />
            <span>{prevButtonLabel}</span>
          </button>

          {/* Center Turn Stepper + Show All Toggle */}
          <div className="flex flex-wrap items-center gap-2">
            {totalTurns > 1 && !showAllTurns && (
              <div className="flex items-center gap-1">
                {activeMatch.liveTurns.map((slot, idx) => (
                  <button
                    key={slot.index}
                    type="button"
                    onClick={() => setTurnIdx(idx)}
                    className={`rounded-full px-2.5 py-1 text-xs font-semibold transition ${
                      idx === safeTurnIdx
                        ? "bg-[#2b5b84] text-white"
                        : "bg-[#efe2cc] text-[#5c4f41] hover:bg-[#e4d2b4]"
                    }`}
                  >
                    Turn {slot.index}
                  </button>
                ))}
              </div>
            )}

            {totalTurns > 1 && (
              <button
                type="button"
                onClick={() => setShowAllTurns((v) => !v)}
                className="inline-flex items-center gap-1 rounded-full border border-[#dec8a4] bg-[#fffdf9] px-2.5 py-1 text-xs font-medium text-[#6b5e4e] transition hover:border-[#b49464] hover:text-[#231f1a]"
              >
                <Layers className="h-3 w-3" />
                {showAllTurns ? "One turn at a time" : "Show all turns"}
              </button>
            )}
          </div>

          <button
            type="button"
            onClick={handleNextClick}
            className="inline-flex items-center gap-2 rounded-xl bg-[#2b5b84] px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-[#1e4568]"
          >
            {isLastTurn && isLastCase && <Sparkles className="h-4 w-4" />}
            <span>{nextButtonLabel}</span>
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </section>
    </div>
  );
}
