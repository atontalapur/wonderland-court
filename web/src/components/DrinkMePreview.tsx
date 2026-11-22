import { AlertTriangle, Globe, Mail, Terminal } from "lucide-react";
import type { Document } from "../types/events";

interface DrinkMePreviewProps {
  document: Document;
}

interface TextSegment {
  text: string;
  highlighted: boolean;
}

const DIRECTIVE_PATTERN =
  /(<!--[\s\S]*?-->|(?:NOTE TO ASSISTANT|\[SYSTEM\]|IGNORE PREVIOUS|SYSTEM OVERRIDE)[^\n]*)/gi;

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
      className={`mt-3 overflow-hidden rounded-xl border-2 ${
        document.poisoned
          ? "border-[#e58b99] bg-[#fff7f8]"
          : "border-[#e4d2b4] bg-[#fffdf9]"
      }`}
      data-testid="drink-me-preview"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#eed8c0] bg-[#faf1e1] px-3 py-2 text-xs">
        <div className="flex items-center gap-2 text-[#4c3f31]">
          <Icon className="h-3.5 w-3.5 text-[#b45309]" />
          <span className="font-editorial font-bold text-[#8c3f0b]">
            Drink Me · {label}
          </span>
          <span className="text-[#c5ad8c]">·</span>
          <span className="font-semibold text-[#231f1a]">{document.title}</span>
        </div>

        {document.poisoned && (
          <span className="inline-flex items-center gap-1 rounded-full border border-[#f5b7c2] bg-[#ffe4e8] px-2.5 py-0.5 text-[11px] font-bold text-[#a5152e]">
            <AlertTriangle className="h-3 w-3" />
            Poisoned
          </span>
        )}
      </div>

      <pre className="overflow-x-auto whitespace-pre-wrap break-words p-3 font-mono text-xs leading-relaxed text-[#3d342b]">
        {segments.map((seg, idx) =>
          seg.highlighted ? (
            <mark
              key={idx}
              className="rounded border border-[#f09aa9] bg-[#ffdce2] px-1 py-0.5 font-semibold text-[#881326]"
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
