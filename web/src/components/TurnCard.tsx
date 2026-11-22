import { ArrowRightLeft, ShieldCheck, Sparkles, Wrench } from "lucide-react";
import type { LiveTurnSlot } from "../state/streamAggregator";
import {
  buildAliceThought,
  buildAttackerThought,
  CHARACTERS,
  formatDefenseName,
  formatMutatorLabel,
  formatTacticLabel,
  pickAttackerCharacter,
} from "../theme/wonderland";
import type { ToolCall } from "../types/events";
import { CharacterAvatar } from "./CharacterAvatar";
import { DrinkMePreview } from "./DrinkMePreview";
import { VerdictBanner } from "./VerdictBanner";

interface TurnCardProps {
  slot: LiveTurnSlot;
  prevFamily?: string | null;
  canary?: string;
}

function formatToolCallSignature(tc: ToolCall): string {
  const entries = Object.entries(tc.arguments ?? {}).map(([k, v]) => {
    const rendered = typeof v === "string" ? v : JSON.stringify(v);
    return `${k}=${rendered}`;
  });
  return `${tc.name}(${entries.join(", ")})`;
}

export function TurnCard({ slot, prevFamily, canary }: TurnCardProps) {
  const attack = slot.attack;
  const reply = slot.reply;
  const verdict = slot.verdict;
  const isTacticSwitch = Boolean(
    attack && prevFamily && attack.family !== prevFamily
  );

  const attacker = pickAttackerCharacter(attack);
  const attackerThought = attack
    ? buildAttackerThought(attack, isTacticSwitch)
    : "Preparing the next trick…";
  const aliceThought = buildAliceThought(reply, verdict);

  const canaryLeaked = Boolean(
    canary &&
      reply &&
      reply.content.replace(/\s+/g, "").includes(canary.replace(/\s+/g, ""))
  );

  return (
    <article
      className="animate-page-in space-y-5"
      data-testid={`turn-card-${slot.index}`}
    >
      {/* Subtle Turn Banner */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#e9dcc6] pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-[#f2e7d3] px-3 py-1 font-editorial text-xs font-bold text-[#4a3b2c]">
            Turn {slot.index}
          </span>

          {attack && (
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold ${attacker.badgeClass}`}
            >
              <span>{attacker.suit}</span>
              <span>{formatTacticLabel(attack.family)}</span>
            </span>
          )}

          {isTacticSwitch && (
            <span className="inline-flex items-center gap-1 rounded-full border border-[#f5c26b] bg-[#fef3c7] px-2.5 py-0.5 text-[11px] font-bold text-[#92400e]">
              <ArrowRightLeft className="h-3 w-3" />
              New Tactic
            </span>
          )}

          {attack?.mutators.map((mut) => (
            <span
              key={mut}
              className="inline-flex items-center gap-1 rounded-full border border-[#a7f3d0] bg-[#ecfdf5] px-2.5 py-0.5 text-[11px] font-semibold text-[#065f46]"
            >
              <Sparkles className="h-3 w-3" />
              {formatMutatorLabel(mut)}
            </span>
          ))}
        </div>

        {reply?.blocked_by && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-[#9ad8be] bg-[#ecfdf5] px-3 py-1 text-xs font-semibold text-[#065f46]">
            <ShieldCheck className="h-3.5 w-3.5" />
            Blocked by {formatDefenseName(reply.blocked_by)}
          </span>
        )}
      </div>

      {/* 1. Attacker Row (Left Character + Thought Bubble + Speech Bubble) */}
      {attack && (
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:gap-5">
          <div className="md:w-28 md:pt-1">
            <CharacterAvatar character={attacker} size="md" />
          </div>

          <div className="flex-1 space-y-2.5">
            {/* Thought Bubble */}
            <div className="flex items-start gap-2">
              <div
                className={`thought-bubble inline-flex items-center gap-2 px-3.5 py-2 text-xs italic text-[#5c4f41] ${attacker.thoughtBorderClass}`}
                data-testid="attacker-thought"
              >
                <span aria-hidden="true">💭</span>
                <span>{attackerThought}</span>
              </div>
            </div>

            {/* Speech / Chat Bubble */}
            <div
              className={`speech-bubble-left rounded-2xl border-2 p-4 shadow-bubble ${attacker.bubbleClass}`}
            >
              <div
                className={`mb-1.5 text-xs font-bold ${attacker.accentTextClass}`}
              >
                {attacker.name} says:
              </div>
              <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
                {attack.message}
              </p>
              {attack.document && <DrinkMePreview document={attack.document} />}
            </div>
          </div>
        </div>
      )}

      {/* 2. Alice Row (Thought Bubble + Speech Bubble + Right Character) */}
      <div className="flex flex-col-reverse gap-3 md:flex-row md:items-start md:gap-5">
        <div className="flex-1 space-y-2.5">
          {/* Alice's Thought Bubble */}
          <div className="flex justify-start md:justify-end">
            <div
              className={`thought-bubble inline-flex items-center gap-2 px-3.5 py-2 text-xs italic text-[#42556b] ${CHARACTERS.alice.thoughtBorderClass}`}
              data-testid="alice-thought"
            >
              <span aria-hidden="true">💭</span>
              <span>{aliceThought}</span>
            </div>
          </div>

          {/* Alice's Speech / Chat Bubble */}
          <div
            className={`speech-bubble-right rounded-2xl border-2 p-4 shadow-bubble ${CHARACTERS.alice.bubbleClass}`}
          >
            <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-bold text-[#1e4568]">
                Alice replies:
              </span>
              {canaryLeaked && (
                <span className="rounded-full border border-[#f5b7c2] bg-[#ffe4e8] px-2 py-0.5 text-[11px] font-bold text-[#a5152e]">
                  Secret Revealed!
                </span>
              )}
            </div>

            {!reply ? (
              <div className="flex items-center gap-2 py-2 text-sm italic text-[#5c6f82]">
                <span className="h-2 w-2 animate-pulse rounded-full bg-[#2b5b84]" />
                <span>Alice is thinking...</span>
              </div>
            ) : (
              <>
                <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
                  {reply.content}
                </p>

                {reply.tool_calls.length > 0 && (
                  <div className="mt-3 space-y-1.5">
                    <div className="text-[11px] font-bold uppercase tracking-wider text-[#a5152e]">
                      Actions Alice Took:
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {reply.tool_calls.map((tc) => (
                        <div
                          key={tc.id}
                          className="inline-flex items-center gap-1.5 rounded-xl border border-[#f5b7c2] bg-[#fff1f2] px-3 py-1.5 font-mono text-xs font-semibold text-[#881326]"
                          data-testid="tool-call-pill"
                        >
                          <Wrench className="h-3.5 w-3.5 text-[#c81e3a]" />
                          <span>{formatToolCallSignature(tc)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        <div className="md:w-28 md:pt-1">
          <CharacterAvatar character={CHARACTERS.alice} size="md" />
        </div>
      </div>

      {/* 3. Queen of Hearts Verdict */}
      {verdict ? (
        <VerdictBanner verdict={verdict} />
      ) : reply ? (
        <div className="mt-4 flex items-center gap-3 rounded-2xl border border-[#e4d2b4] bg-[#faf4e8] px-4 py-3 text-sm italic text-[#6b5e4e]">
          <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-[#c81e3a]" />
          <span>The Queen of Hearts is deciding the verdict…</span>
        </div>
      ) : null}
    </article>
  );
}
