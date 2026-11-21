import {
  ArrowRightLeft,
  Cat,
  Clock,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import type { LiveTurnSlot } from "../state/streamAggregator";
import type { ToolCall } from "../types/events";
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

  return (
    <article
      className="court-card rounded-xl p-4 shadow-md"
      data-testid={`turn-card-${slot.index}`}
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-[#23293a] pb-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded bg-[#191f2e] px-2 py-0.5 font-mono text-xs font-semibold text-slate-200">
            Turn {slot.index}
          </span>

          {attack && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-purple-500/35 bg-purple-500/10 px-2.5 py-0.5 text-xs font-medium text-purple-300">
              <Cat className="h-3.5 w-3.5" />
              <span className="font-mono">{attack.family}</span>
            </span>
          )}

          {isTacticSwitch && attack && (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-amber-500/50 bg-amber-500/15 px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wider text-amber-300"
              title={`Switched from ${prevFamily} to ${attack.family}`}
            >
              <ArrowRightLeft className="h-3 w-3" />
              TACTIC SWITCH
            </span>
          )}

          {attack?.mutators.map((mut) => (
            <span
              key={mut}
              className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-[#1c1917] px-2 py-0.5 font-mono text-[11px] text-amber-200"
              title="Mad Hatter Mutator"
            >
              <Sparkles className="h-2.5 w-2.5 text-amber-400" />
              {mut}
            </span>
          ))}
        </div>

        {reply && (
          <div className="flex items-center gap-2 text-xs text-slate-400">
            {reply.blocked_by && (
              <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/15 px-2.5 py-0.5 font-medium text-emerald-300">
                <ShieldCheck className="h-3.5 w-3.5" />
                Blocked by {reply.blocked_by}
              </span>
            )}
            <span className="inline-flex items-center gap-1 font-mono text-[11px] text-slate-400">
              <Clock className="h-3 w-3" />
              {reply.latency_ms}ms
            </span>
          </div>
        )}
      </div>

      {/* Cheshire Cat Attack */}
      {attack && (
        <div className="rounded-lg border border-[#23293a] bg-[#0b0d14] p-3">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-purple-300/90">
            Cheshire Cat · Attack
          </div>
          <p className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-slate-200">
            {attack.message}
          </p>
          {attack.document && <DrinkMePreview document={attack.document} />}
        </div>
      )}

      {/* Alice Reply or Thinking State */}
      <div className="mt-3 rounded-lg border border-[#23293a] bg-[#0f131d] p-3">
        <div className="mb-1 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-sky-300/90">
          <span>Alice · Target Reply</span>
          {canary &&
            reply &&
            reply.content.replace(/\s+/g, "").includes(canary.replace(/\s+/g, "")) && (
              <span className="rounded bg-rose-500/20 px-1.5 py-0.5 font-mono text-[10px] text-rose-300">
                Canary Exposed
              </span>
            )}
        </div>

        {!reply ? (
          <div className="flex items-center gap-2 py-2 text-xs italic text-slate-400">
            <span className="h-2 w-2 animate-pulse rounded-full bg-amber-400" />
            <span>Alice is thinking...</span>
          </div>
        ) : (
          <>
            <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-100">
              {reply.content}
            </p>

            {reply.tool_calls.length > 0 && (
              <div className="mt-2.5 flex flex-wrap gap-2">
                {reply.tool_calls.map((tc) => (
                  <div
                    key={tc.id}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-rose-500/50 bg-rose-950/40 px-2.5 py-1 font-mono text-xs text-rose-200"
                    data-testid="tool-call-pill"
                  >
                    <Wrench className="h-3.5 w-3.5 text-rose-400" />
                    <span>{formatToolCallSignature(tc)}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Queen's Verdict */}
      {verdict ? (
        <VerdictBanner verdict={verdict} />
      ) : reply ? (
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-[#23293a] bg-[#0b0d14] px-3 py-2 text-xs italic text-slate-400">
          <span className="h-2 w-2 animate-pulse rounded-full bg-rose-400" />
          <span>Queen of Hearts is ruling...</span>
        </div>
      ) : null}
    </article>
  );
}
