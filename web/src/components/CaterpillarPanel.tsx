import { Check, Copy, Loader2, Sparkles, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { CHARACTERS, formatDefenseName } from "../theme/wonderland";
import type {
  RemediationAdviceView,
  RetrialComparisonView,
} from "../types/events";
import { CharacterAvatar } from "./CharacterAvatar";
import { FailureClusters } from "./FailureClusters";
import { RetrialDiffCard } from "./RetrialDiffCard";

interface CaterpillarPanelProps {
  advice: RemediationAdviceView | null;
  retrial: RetrialComparisonView | null;
  onInspectMatches: (
    matchIds: string[],
    title: string,
    subtitle?: string
  ) => void;
  studioEnabled?: boolean;
  canRunActions?: boolean;
  advising?: boolean;
  retrying?: boolean;
  onAskCaterpillar?: () => Promise<void>;
  onRunRetrial?: (defense?: string) => Promise<void>;
}

export function CaterpillarPanel({
  advice,
  retrial,
  onInspectMatches,
  studioEnabled = false,
  canRunActions = false,
  advising = false,
  retrying = false,
  onAskCaterpillar,
  onRunRetrial,
}: CaterpillarPanelProps) {
  const [copied, setCopied] = useState(false);
  const copyTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (copyTimerRef.current !== null) {
        window.clearTimeout(copyTimerRef.current);
      }
    };
  }, []);

  const handleCopyYaml = async () => {
    if (!advice) return;
    try {
      await navigator.clipboard.writeText(advice.config_patch_yaml);
      setCopied(true);
      if (copyTimerRef.current !== null) {
        window.clearTimeout(copyTimerRef.current);
      }
      copyTimerRef.current = window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="caterpillar-panel">
      {!advice ? (
        <div
          className="storybook-card flex flex-col items-center gap-5 rounded-3xl p-7 sm:flex-row sm:items-start"
          data-testid="caterpillar-empty-state"
        >
          <CharacterAvatar character={CHARACTERS.caterpillar} size="lg" />

          <div className="flex-1 space-y-3">
            <div className="speech-bubble-left rounded-2xl border-2 border-[#a7dfd8] bg-[#f2fbfa] p-5 text-[#143330] shadow-bubble">
              <h2 className="font-editorial text-lg font-bold">
                “Who are you… and how shall we harden Alice?”
              </h2>
              <p className="mt-2 text-sm leading-relaxed text-[#2d4e4a]">
                {studioEnabled && canRunActions
                  ? "Click below and I will group every breach from this trial, diagnose the root causes, and write a hardened defense shield for Alice."
                  : "No advice scroll has been written for this run yet. Run court advise to group every failure and generate a hardened defense patch."}
              </p>

              {studioEnabled && canRunActions && onAskCaterpillar && (
                <button
                  type="button"
                  disabled={advising}
                  onClick={() => void onAskCaterpillar()}
                  className="mt-4 inline-flex items-center gap-2 rounded-xl bg-[#0f766e] px-5 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-[#115e59] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {advising ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      <span>Caterpillar is analyzing…</span>
                    </>
                  ) : (
                    <>
                      <Sparkles className="h-4 w-4" />
                      <span>Ask the Caterpillar for Advice</span>
                    </>
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      ) : (
        <>
          {/* Caterpillar Speech Recommendation */}
          <div className="storybook-card overflow-hidden rounded-3xl">
            <div className="flex flex-col gap-5 border-b border-[#e9dcc6] bg-[#faf4e8]/60 p-6 sm:flex-row sm:items-start">
              <CharacterAvatar character={CHARACTERS.caterpillar} size="md" />

              <div className="flex-1 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-[#0f766e]">
                      <Wrench className="h-3.5 w-3.5" />
                      Caterpillar’s Recommendation
                    </div>
                    <h2 className="mt-0.5 font-editorial text-2xl font-bold text-[#231f1a]">
                      Use{" "}
                      <span className="text-[#2b5b84]">
                        {formatDefenseName(advice.recommended_defense)}
                      </span>
                    </h2>
                  </div>

                  <button
                    type="button"
                    onClick={handleCopyYaml}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-[#d6be96] bg-[#fffdf9] px-3.5 py-2 text-xs font-semibold text-[#3a3026] transition hover:border-[#2b5b84] hover:text-[#2b5b84]"
                  >
                    {copied ? (
                      <>
                        <Check className="h-3.5 w-3.5 text-[#047857]" />
                        <span className="text-[#047857]">Copied!</span>
                      </>
                    ) : (
                      <>
                        <Copy className="h-3.5 w-3.5" />
                        <span>Copy YAML</span>
                      </>
                    )}
                  </button>
                </div>

                <div className="speech-bubble-left rounded-2xl border-2 border-[#a7dfd8] bg-[#f2fbfa] p-4 text-sm leading-relaxed text-[#143330]">
                  “{advice.rationale}”
                </div>
              </div>
            </div>

            <div className="bg-[#fffdf9] p-5">
              <div className="mb-2 text-xs font-bold uppercase tracking-wider text-[#6b5e4e]">
                Recommended Configuration Patch
              </div>
              <pre
                className="overflow-x-auto rounded-2xl border border-[#e4d2b4] bg-[#faf4e8] p-4 font-mono text-xs leading-relaxed text-[#2b241d]"
                data-testid="yaml-patch-block"
              >
                {advice.config_patch_yaml}
              </pre>
            </div>
          </div>

          <FailureClusters
            clusters={advice.clusters}
            onInspectMatches={onInspectMatches}
          />
        </>
      )}

      <RetrialDiffCard
        retrial={retrial}
        studioEnabled={studioEnabled && canRunActions}
        retrying={retrying}
        recommendedDefense={advice?.recommended_defense}
        onRunRetrial={onRunRetrial}
      />
    </div>
  );
}
