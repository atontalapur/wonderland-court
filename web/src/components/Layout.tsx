import {
  ChevronRight,
  Loader2,
  PlayCircle,
  Sparkles,
  Swords,
  Trophy,
  Wand2,
} from "lucide-react";
import type { ReactNode } from "react";
import type {
  CalibrationSummary,
  RunSummary,
  StreamConnectionMode,
  StudioJob,
} from "../types/events";

export type DashboardTab = "setup" | "feed" | "leaderboard" | "caterpillar";

interface LayoutProps {
  runs: RunSummary[];
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
  connectionMode: StreamConnectionMode;
  calibration: CalibrationSummary | null;
  activeTab: DashboardTab;
  onTabChange: (tab: DashboardTab) => void;
  activeSummary: RunSummary | null;
  studioEnabled?: boolean;
  activeJob?: StudioJob | null;
  replayBar?: ReactNode;
  onTriggerReplay?: () => void;
  canTriggerReplay?: boolean;
  children: ReactNode;
}

export function Layout({
  runs,
  selectedRunId,
  onSelectRun,
  connectionMode,
  activeTab,
  onTabChange,
  activeSummary,
  studioEnabled = false,
  activeJob = null,
  replayBar,
  onTriggerReplay,
  canTriggerReplay,
  children,
}: LayoutProps) {
  const steps: {
    id: DashboardTab;
    label: string;
    Icon: typeof Swords;
  }[] = studioEnabled
    ? [
        { id: "setup", label: "Choose Alice", Icon: Wand2 },
        { id: "feed", label: "Watch the Trial", Icon: Swords },
        { id: "leaderboard", label: "Scoreboard", Icon: Trophy },
        { id: "caterpillar", label: "Caterpillar's Fix", Icon: Sparkles },
      ]
    : [
        { id: "feed", label: "Watch the Trial", Icon: Swords },
        { id: "leaderboard", label: "Scoreboard", Icon: Trophy },
        { id: "caterpillar", label: "Caterpillar's Fix", Icon: Sparkles },
      ];

  const activeIndex = steps.findIndex((s) => s.id === activeTab);
  const jobPct =
    activeJob && activeJob.progress_total > 0
      ? Math.round((activeJob.progress_done / activeJob.progress_total) * 100)
      : 0;

  return (
    <div className="min-h-screen text-[#231f1a]">
      <header className="sticky top-0 z-30 border-b border-[#e4d2b4] bg-[#fffdf9]/95 backdrop-blur">
        <div className="mx-auto max-w-5xl px-4 py-3.5 sm:px-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            {/* Wonderland Court Storybook Crest */}
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl border-2 border-[#e58b99] bg-[#fff1f2] font-editorial text-lg font-bold text-[#c81e3a] shadow-sm">
                ♥
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="font-editorial text-xl font-bold tracking-tight text-[#231f1a]">
                    Wonderland Court
                  </h1>
                  {connectionMode === "live" && (
                    <span
                      className="inline-flex items-center gap-1 rounded-full border border-[#f5b7c2] bg-[#fff1f2] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-[#a5152e]"
                      data-testid="mode-pill"
                    >
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#c81e3a]" />
                      Live
                    </span>
                  )}
                  {connectionMode === "replaying" && (
                    <span
                      className="inline-flex items-center gap-1 rounded-full border border-[#f5c26b] bg-[#fef3c7] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-[#92400e]"
                      data-testid="mode-pill"
                    >
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#d97706]" />
                      Replay
                    </span>
                  )}
                </div>
                {activeSummary ? (
                  <p className="text-xs text-[#6b5e4e]">
                    {activeSummary.matches} trials ·{" "}
                    {activeSummary.matches - activeSummary.leaks} held ·{" "}
                    {activeSummary.leaks} breached
                  </p>
                ) : (
                  <p className="text-xs text-[#6b5e4e]">
                    Local AI Adversarial Storybook Arena
                  </p>
                )}
              </div>
            </div>

            {/* Compact Controls */}
            <div className="flex flex-wrap items-center gap-2">
              {runs.length > 0 && (
                <select
                  aria-label="Select active run"
                  value={selectedRunId ?? ""}
                  onChange={(e) => onSelectRun(e.target.value)}
                  className="rounded-xl border border-[#dec8a4] bg-[#faf4e8] px-3 py-1.5 text-xs font-semibold text-[#3a3026] transition hover:border-[#b49464] focus:border-[#2b5b84] focus:outline-none"
                >
                  {runs.map((r) => (
                    <option key={r.run_id} value={r.run_id}>
                      {r.run_id} ({r.leaks}/{r.matches} breached)
                    </option>
                  ))}
                </select>
              )}

              {canTriggerReplay && onTriggerReplay && activeTab !== "setup" && (
                <button
                  type="button"
                  onClick={onTriggerReplay}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-[#e4d2b4] bg-[#fffdf9] px-3 py-1.5 text-xs font-semibold text-[#6b4f2b] transition hover:border-[#d97706] hover:bg-[#fef3c7]/50"
                >
                  <PlayCircle className="h-3.5 w-3.5 text-[#b45309]" />
                  Replay
                </button>
              )}
            </div>
          </div>

          {/* Linear Storybook Stepper */}
          <nav
            className="mt-3.5 flex items-center gap-1.5 overflow-x-auto border-t border-[#efe2cc] pt-3"
            aria-label="Courtroom steps"
          >
            {steps.map(({ id, label, Icon }, idx) => {
              const active = activeTab === id;
              const completed = idx < activeIndex;
              return (
                <div key={id} className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => onTabChange(id)}
                    aria-current={active ? "step" : undefined}
                    className={`inline-flex items-center gap-2 whitespace-nowrap rounded-full px-3.5 py-1.5 text-xs font-semibold transition ${
                      active
                        ? "bg-[#2b5b84] text-white shadow-sm"
                        : completed
                          ? "border border-[#b7cfe8] bg-[#eff6ff] text-[#1e4568] hover:bg-[#dbeafe]"
                          : "border border-[#e4d2b4] bg-[#faf4e8] text-[#5c4f41] hover:border-[#cfb489] hover:text-[#231f1a]"
                    }`}
                  >
                    <span
                      className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold ${
                        active
                          ? "bg-white/20 text-white"
                          : completed
                            ? "bg-[#2b5b84] text-white"
                            : "bg-[#e8dac2] text-[#5c4f41]"
                      }`}
                    >
                      {idx + 1}
                    </span>
                    <Icon className="h-3.5 w-3.5" />
                    <span>{label}</span>
                  </button>

                  {idx < steps.length - 1 && (
                    <ChevronRight
                      className="h-4 w-4 shrink-0 text-[#cfb489]"
                      aria-hidden="true"
                    />
                  )}
                </div>
              );
            })}
          </nav>

          {/* Live Local Job Progress Bar */}
          {activeJob && activeJob.status === "running" && (
            <div
              className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#b7cfe8] bg-[#eff6ff] px-4 py-2.5 text-xs text-[#1e4568]"
              data-testid="studio-job-banner"
            >
              <div className="flex items-center gap-2 font-semibold">
                <Loader2 className="h-4 w-4 animate-spin text-[#2b5b84]" />
                <span>{activeJob.message}</span>
              </div>
              {activeJob.progress_total > 0 && (
                <div className="flex items-center gap-2.5">
                  <div className="h-2 w-32 overflow-hidden rounded-full bg-[#dbeafe]">
                    <div
                      className="h-full rounded-full bg-[#2b5b84] transition-all duration-300"
                      style={{ width: `${Math.max(6, jobPct)}%` }}
                    />
                  </div>
                  <span className="font-mono font-bold">
                    {activeJob.progress_done}/{activeJob.progress_total}
                  </span>
                </div>
              )}
            </div>
          )}

          {replayBar && <div className="mt-3">{replayBar}</div>}
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-6 sm:px-6">{children}</main>
    </div>
  );
}
