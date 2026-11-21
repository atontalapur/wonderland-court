import { Check, Copy, Sparkles, Wrench } from "lucide-react";
import { useState } from "react";
import type {
  RemediationAdviceView,
  RetrialComparisonView,
} from "../types/events";
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
}

function renderYamlLine(line: string, index: number) {
  const trimmed = line.trim();
  if (trimmed.startsWith("#")) {
    return (
      <div key={index} className="text-slate-500">
        {line}
      </div>
    );
  }
  const colonIdx = line.indexOf(":");
  if (colonIdx > 0 && !trimmed.startsWith("-")) {
    const keyPart = line.slice(0, colonIdx + 1);
    const valPart = line.slice(colonIdx + 1);
    return (
      <div key={index}>
        <span className="text-sky-300">{keyPart}</span>
        <span className="text-amber-200">{valPart}</span>
      </div>
    );
  }
  if (trimmed.startsWith("- ")) {
    const dashIdx = line.indexOf("- ");
    return (
      <div key={index}>
        <span className="text-emerald-400">{line.slice(0, dashIdx + 2)}</span>
        <span className="text-amber-200">{line.slice(dashIdx + 2)}</span>
      </div>
    );
  }
  return <div key={index}>{line}</div>;
}

export function CaterpillarPanel({
  advice,
  retrial,
  onInspectMatches,
}: CaterpillarPanelProps) {
  const [copied, setCopied] = useState(false);

  const handleCopyYaml = async () => {
    if (!advice) return;
    try {
      await navigator.clipboard.writeText(advice.config_patch_yaml);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="caterpillar-panel">
      {!advice ? (
        <div
          className="court-card rounded-xl p-6"
          data-testid="caterpillar-empty-state"
        >
          <div className="flex items-start gap-3">
            <Sparkles className="mt-0.5 h-5 w-5 text-amber-400" />
            <div>
              <h2 className="font-editorial text-lg font-bold text-slate-100">
                Caterpillar Remediation Advisor
              </h2>
              <p className="mt-1 text-xs leading-relaxed text-slate-400">
                No Caterpillar remediation advice is attached to this run yet.
                Run{" "}
                <code className="rounded bg-[#0b0d14] px-1.5 py-0.5 font-mono text-amber-300">
                  court advise
                </code>{" "}
                to deduplicate failure families and generate a hardened{" "}
                <code className="rounded bg-[#0b0d14] px-1.5 py-0.5 font-mono text-slate-200">
                  court.yaml
                </code>{" "}
                defense stack.
              </p>
            </div>
          </div>
        </div>
      ) : (
        <>
          {/* Recommended Defense + YAML Patch */}
          <div className="court-card overflow-hidden rounded-xl">
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-[#23293a] p-5">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Wrench className="h-4 w-4 text-emerald-400" />
                  <span className="text-xs font-semibold uppercase tracking-wider text-emerald-400">
                    Caterpillar Recommendation
                  </span>
                  <span className="rounded border border-[#23293a] bg-[#0b0d14] px-2 py-0.5 font-mono text-[11px] text-slate-400">
                    target_kind: {advice.target_kind}
                  </span>
                </div>

                <h2 className="mt-1.5 font-editorial text-xl font-bold text-slate-100">
                  Recommended Stack:{" "}
                  <span className="font-mono text-amber-300">
                    {advice.recommended_defense}
                  </span>
                </h2>
                <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-slate-300">
                  {advice.rationale}
                </p>
              </div>

              <button
                type="button"
                onClick={handleCopyYaml}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#23293a] bg-[#191f2e] px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-amber-400/60 hover:text-amber-200"
              >
                {copied ? (
                  <>
                    <Check className="h-3.5 w-3.5 text-emerald-400" />
                    <span className="text-emerald-300">Copied!</span>
                  </>
                ) : (
                  <>
                    <Copy className="h-3.5 w-3.5" />
                    <span>Copy YAML</span>
                  </>
                )}
              </button>
            </div>

            <div className="bg-[#0b0d14] p-4">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                config_patch_yaml
              </div>
              <pre
                className="overflow-x-auto rounded-lg border border-[#23293a] bg-[#07090e] p-4 font-mono text-xs leading-relaxed"
                data-testid="yaml-patch-block"
              >
                {advice.config_patch_yaml
                  .split(/\r?\n/)
                  .map((line, idx) => renderYamlLine(line, idx))}
              </pre>
            </div>
          </div>

          <FailureClusters
            clusters={advice.clusters}
            onInspectMatches={onInspectMatches}
          />
        </>
      )}

      <RetrialDiffCard retrial={retrial} />
    </div>
  );
}
