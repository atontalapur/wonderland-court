import { AlertTriangle, Globe, Mail, Terminal } from "lucide-react";
import type { Document } from "../types/events";

interface DrinkMePreviewProps {
  document: Document;
}

interface TextSegment {
  text: string;
  highlighted: boolean;
}

const DIRECTIVE_PATTERN = /(<!--[\s\S]*?-->|(?:NOTE TO ASSISTANT|\[SYSTEM\]|IGNORE PREVIOUS|SYSTEM OVERRIDE)[^\n]*)/gi;

function splitHighlightedSegments(body: string): TextSegment[] {
  const segments: TextSegment[] = [];
  let lastIndex = 0;
  const regex = new RegExp(DIRECTIVE_PATTERN.source, "gi");
  let match: RegExpExecArray | null = regex.exec(body);

  while (match !== null) {
    if (match.index > lastIndex) {
      segments.push({
        text: body.slice(lastIndex, match.index),
        highlighted: false,
      });
    }
    segments.push({
      text: match[0],
      highlighted: true,
    });
    lastIndex = match.index + match[0].length;
    match = regex.exec(body);
  }

  if (lastIndex < body.length) {
    segments.push({
      text: body.slice(lastIndex),
      highlighted: false,
    });
  }

  return segments.length > 0 ? segments : [{ text: body, highlighted: false }];
}

function kindMeta(kind: Document["kind"]) {
  switch (kind) {
    case "email":
      return { label: "Email", Icon: Mail };
    case "web_page":
      return { label: "Web Page", Icon: Globe };
    case "tool_output":
      return { label: "Tool Output", Icon: Terminal };
  }
}

export function DrinkMePreview({ document }: DrinkMePreviewProps) {
  const { label, Icon } = kindMeta(document.kind);
  const segments = splitHighlightedSegments(document.body);

  return (
    <div
      className={`mt-3 overflow-hidden rounded-lg border ${
        document.poisoned
          ? "border-rose-500/40 bg-[#150e17]"
          : "border-[#23293a] bg-[#0b0d14]"
      }`}
      data-testid="drink-me-preview"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#23293a]/80 bg-[#0f131d] px-3 py-2 text-xs">
        <div className="flex items-center gap-2 text-slate-300">
          <Icon className="h-3.5 w-3.5 text-amber-400" />
          <span className="font-semibold uppercase tracking-wider text-amber-300">
            Drink Me · {label}
          </span>
          <span className="text-slate-500">·</span>
          <span className="font-medium text-slate-200">{document.title}</span>
          <span className="font-mono text-[11px] text-slate-500">
            ({document.id})
          </span>
        </div>

        {document.poisoned && (
          <span className="inline-flex items-center gap-1 rounded-full border border-rose-500/50 bg-rose-500/15 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-rose-300">
            <AlertTriangle className="h-3 w-3" />
            Poisoned
          </span>
        )}
      </div>

      <pre className="overflow-x-auto whitespace-pre-wrap break-words p-3 font-mono text-xs leading-relaxed text-slate-300">
        {segments.map((seg, idx) =>
          seg.highlighted ? (
            <mark
              key={idx}
              className="rounded border border-rose-500/40 bg-rose-500/20 px-1 py-0.5 text-rose-200"
            >
              {seg.text}
            </mark>
          ) : (
            <span key={idx}>{seg.text}</span>
          )
        )}
      </pre>
    </div>
  );
}
