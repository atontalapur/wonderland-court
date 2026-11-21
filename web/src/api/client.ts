import type {
  HealthResponse,
  RunBundle,
  RunSummary,
  StaticManifest,
} from "../types/events";
import { loadStaticManifest, loadStaticRunBundle } from "./staticLoader";

export function isStaticMode(): boolean {
  return import.meta.env.VITE_STATIC_MODE === "true";
}

export async function fetchHealth(): Promise<HealthResponse> {
  if (isStaticMode()) {
    return { status: "ok", mode: "static", replay: false, active_run_id: null };
  }
  const res = await fetch("/api/health");
  if (!res.ok) {
    throw new Error(`Health check failed (${res.status})`);
  }
  return (await res.json()) as HealthResponse;
}

export async function fetchRuns(): Promise<StaticManifest> {
  if (isStaticMode()) {
    return loadStaticManifest();
  }
  const res = await fetch("/api/runs");
  if (!res.ok) {
    throw new Error(`Failed to fetch runs (${res.status})`);
  }
  const data = (await res.json()) as RunSummary[] | { runs: RunSummary[]; default_run_id?: string };
  if (Array.isArray(data)) {
    return { runs: data, default_run_id: data[0]?.run_id };
  }
  const runs = data.runs ?? [];
  return { runs, default_run_id: data.default_run_id ?? runs[0]?.run_id };
}

export async function fetchRunBundle(runId: string): Promise<RunBundle> {
  if (isStaticMode()) {
    return loadStaticRunBundle(runId);
  }
  const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/bundle`);
  if (!res.ok) {
    throw new Error(`Failed to fetch bundle for ${runId} (${res.status})`);
  }
  return (await res.json()) as RunBundle;
}
