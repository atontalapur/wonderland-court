import type {
  HealthResponse,
  RemediationAdviceView,
  RunBundle,
  RunSummary,
  StartTrialPayload,
  StaticManifest,
  StudioJob,
  StudioOptions,
} from "../types/events";
import { loadStaticManifest, loadStaticRunBundle } from "./staticLoader";

export function isStaticMode(): boolean {
  return import.meta.env.VITE_STATIC_MODE === "true";
}

async function parseErrorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: string };
    if (data.detail) return data.detail;
  } catch {
    // ignore non-json error bodies
  }
  return `${fallback} (${res.status})`;
}

export async function fetchHealth(): Promise<HealthResponse> {
  if (isStaticMode()) {
    return {
      status: "ok",
      mode: "static",
      replay: false,
      active_run_id: null,
      studio_enabled: false,
    };
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
  const data = (await res.json()) as
    | RunSummary[]
    | { runs: RunSummary[]; default_run_id?: string };
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

export async function fetchStudioOptions(): Promise<StudioOptions> {
  const res = await fetch("/api/studio/options");
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to load local studio options"));
  }
  return (await res.json()) as StudioOptions;
}

export async function startStudioTrial(
  payload: StartTrialPayload
): Promise<StudioJob> {
  const res = await fetch("/api/studio/trials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to start trial"));
  }
  return (await res.json()) as StudioJob;
}

export async function fetchStudioJob(jobId: string): Promise<StudioJob> {
  const res = await fetch(`/api/studio/jobs/${encodeURIComponent(jobId)}`);
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to check job status"));
  }
  return (await res.json()) as StudioJob;
}

export async function runStudioAdvise(
  runId: string
): Promise<RemediationAdviceView> {
  const res = await fetch(
    `/api/studio/runs/${encodeURIComponent(runId)}/advise`,
    { method: "POST" }
  );
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Caterpillar advice failed"));
  }
  return (await res.json()) as RemediationAdviceView;
}

export async function startStudioRetrial(
  runId: string,
  defense?: string
): Promise<StudioJob> {
  const res = await fetch(
    `/api/studio/runs/${encodeURIComponent(runId)}/retrial`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ defense: defense ?? null }),
    }
  );
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to start retrial"));
  }
  return (await res.json()) as StudioJob;
}
