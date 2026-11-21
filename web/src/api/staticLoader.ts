import type {
  CourtEvent,
  RunBundle,
  RunSummary,
  StaticManifest,
} from "../types/events";

export function parseJsonlEvents(jsonlText: string): CourtEvent[] {
  const events: CourtEvent[] = [];
  for (const rawLine of jsonlText.split(/\r?\n/)) {
    const trimmed = rawLine.trim();
    if (!trimmed) continue;
    events.push(JSON.parse(trimmed) as CourtEvent);
  }
  return events.sort((a, b) => a.seq - b.seq);
}

export async function loadStaticManifest(): Promise<StaticManifest> {
  const res = await fetch("./data/manifest.json");
  if (!res.ok) {
    throw new Error(`Failed to load static manifest (${res.status})`);
  }
  const payload = (await res.json()) as StaticManifest | RunSummary[];
  if (Array.isArray(payload)) {
    return {
      runs: payload.map((r) => ({ ...r, source: "static" })),
      default_run_id: payload[0]?.run_id,
    };
  }
  const runs = (payload.runs ?? []).map((r) => ({ ...r, source: "static" as const }));
  return {
    runs,
    default_run_id: payload.default_run_id ?? runs[0]?.run_id,
  };
}

export async function loadStaticRunEvents(runId: string): Promise<CourtEvent[]> {
  const res = await fetch(`./data/runs/${encodeURIComponent(runId)}.events.jsonl`);
  if (!res.ok) {
    throw new Error(`Failed to load static events for ${runId} (${res.status})`);
  }
  const text = await res.text();
  return parseJsonlEvents(text);
}

export async function loadStaticRunBundle(runId: string): Promise<RunBundle> {
  const res = await fetch(`./data/runs/${encodeURIComponent(runId)}.json`);
  if (!res.ok) {
    throw new Error(`Failed to load static bundle for ${runId} (${res.status})`);
  }
  const bundle = (await res.json()) as RunBundle;
  let events = bundle.events ?? [];
  if (events.length === 0) {
    try {
      events = await loadStaticRunEvents(runId);
    } catch {
      events = [];
    }
  }
  return {
    ...bundle,
    summary: { ...bundle.summary, source: "static" },
    events,
  };
}
