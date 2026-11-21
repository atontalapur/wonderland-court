import {
  Activity,
  BarChart3,
  Heart,
  PlayCircle,
  Sparkles,
} from "lucide-react";
import type { ReactNode } from "react";
import type {
  CalibrationSummary,
  RunSummary,
  StreamConnectionMode,
} from "../types/events";
import { CalibrationBadge } from "./CalibrationBadge";

export type DashboardTab = "feed" | "leaderboard" | "caterpillar";

interface LayoutProps {
  runs: RunSummary[];
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
  connectionMode: StreamConnectionMode;
  calibration: CalibrationSummary | null;
  activeTab: DashboardTab;
  onTabChange: (tab: DashboardTab) => void;
  activeSummary: RunSummary | null;
  replayBar?: ReactNode;
  onTriggerReplay?: () => void;
  canTriggerReplay?: boolean;
  children: ReactNode;
}

function modeBadgeProps(mode: StreamConnectionMode) {
  switch (mode) {
    case "live":
      return {
        label: "LIVE",
        cls: "border-rose-500/50 bg-rose-500/15 text-rose-300",
        dot: "bg-rose-500 animate-pulse",
      };
    case "replaying":
      return {
        label: "REPLAY",
        cls: "border-amber-500/50 bg-amber-500/15 text-amber-300",
        dot: "bg-amber-400 animate-pulse",
      };
    case "static":
      return {
        label: "PUBLIC BENCHMARK",
        cls: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
        dot: "bg-emerald-400",
      };
    case "disconnected":
      return {
        label: "DISCONNECTED",
        cls: "border-slate-600 bg-slate-800/60 text-slate-300",
        dot: "bg-slate-400",
      };
  }
}

export function Layout({
  runs,
  selectedRunId,
  onSelectRun,
  connectionMode,
  calibration,
  activeTab,
  onTabChange,
  activeSummary,
  replayBar,
  onTriggerReplay,
  canTriggerReplay,
  children,
}: LayoutProps) {
  const modeMeta = modeBadgeProps(connectionMode);

  const tabs: { id: DashboardTab; label: string; Icon: typeof Activity }[] = [
    { id: "feed", label: "Courtroom Feed", Icon: Activity },
    { id: "leaderboard", label: "Leaderboard & Heatmap", Icon: BarChart3 },
    { id: "caterpillar", label: "Caterpillar Fix & Retrial", Icon: Sparkles },
  ];

  return (
    <div className="min-h-screen bg-[#0b0d14] text-slate-100">
      <header className="sticky top-0 z-30 border-b border-[#23293a] bg-[#0b0d14]/95 backdrop-blur">
        <div className="mx-auto max-w-7xl px-4 py-3.5 sm:px-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            {/* Wonderland Court Crest */}
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-rose-500/40 bg-rose-950/30 shadow-inner">
                <Heart className="h-5 w-5 fill-rose-500 text-rose-500" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="font-editorial text-xl font-bold tracking-tight text-white">
                    Wonderland Court
                  </h1>
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-bold tracking-wider ${modeMeta.cls}`}
                    data-testid="mode-pill"
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${modeMeta.dot}`} />
                    {modeMeta.label}
                  </span>
                </div>
                <p className="text-xs text-slate-400">
                  {activeSummary
                    ? `${activeSummary.targets.join(", ")} · ${activeSummary.matches} matches · ${activeSummary.leaks} leaks (${activeSummary.mode})`
                    : "AI Agent Adversarial Red-Team Arena"}
                </p>
              </div>
            </div>

            {/* Run Selector & Calibration */}
            <div className="flex flex-wrap items-center gap-2.5">
              {runs.length > 0 && (
                <label className="inline-flex items-center gap-2 text-xs text-slate-400">
                  <span>Run</span>
                  <select
                    aria-label="Select active run"
                    value={selectedRunId ?? ""}
                    onChange={(e) => onSelectRun(e.target.value)}
                    className="rounded-lg border border-[#23293a] bg-[#131722] px-2.5 py-1.5 font-mono text-xs text-slate-100 focus:border-amber-400 focus:outline-none"
                  >
                    {runs.map((r) => (
                      <option key={r.run_id} value={r.run_id}>
                        {r.run_id} ({r.leaks}/{r.matches} leaks)
                      </option>
                    ))}
                  </select>
                </label>
              )}

              {canTriggerReplay && onTriggerReplay && (
                <button
                  type="button"
                  onClick={onTriggerReplay}
                  className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-300 transition hover:bg-amber-500/20"
                >
                  <PlayCircle className="h-3.5 w-3.5" />
                  Replay Run
                </button>
              )}

              <CalibrationBadge calibration={calibration} />
            </div>
          </div>

          {/* Primary Navigation Tabs */}
          <nav
            className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-[#23293a]/70 pt-3"
            aria-label="Courtroom sections"
          >
            {tabs.map(({ id, label, Icon }) => {
              const active = activeTab === id;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => onTabChange(id)}
                  aria-current={active ? "page" : undefined}
                  className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs font-semibold transition ${
                    active
                      ? "border border-amber-500/40 bg-[#191f2e] text-amber-200 shadow-sm"
                      : "border border-transparent text-slate-400 hover:bg-[#131722] hover:text-slate-200"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  <span>{label}</span>
                </button>
              );
            })}
          </nav>

          {replayBar && <div className="mt-3">{replayBar}</div>}
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">{children}</main>
    </div>
  );
}
