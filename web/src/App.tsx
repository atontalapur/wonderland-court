import { ChevronLeft, ChevronRight, RotateCcw, Wand2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchHealth,
  fetchRunBundle,
  fetchRuns,
  fetchStudioJob,
  fetchStudioOptions,
  isStaticMode,
  runStudioAdvise,
  startStudioRetrial,
  startStudioTrial,
} from "./api/client";
import { useCourtStream } from "./api/sse";
import { CaterpillarPanel } from "./components/CaterpillarPanel";
import { CourtroomFeed } from "./components/CourtroomFeed";
import { Layout, type DashboardTab } from "./components/Layout";
import { LeaderboardTable } from "./components/LeaderboardTable";
import { ReplayControls } from "./components/ReplayControls";
import {
  TechniqueHeatmap,
  type AggregatedCellView,
} from "./components/TechniqueHeatmap";
import { TranscriptDrawer } from "./components/TranscriptDrawer";
import { TrialSetupPanel } from "./components/TrialSetupPanel";
import { aggregateEvents } from "./state/streamAggregator";
import { formatDefenseName, formatTacticLabel } from "./theme/wonderland";
import type {
  HealthResponse,
  RunBundle,
  RunSummary,
  StartTrialPayload,
  StudioJob,
  StudioOptions,
} from "./types/events";

export const LIVE_RUNS_POLL_MS = 2000;

interface DrawerState {
  isOpen: boolean;
  title: string;
  subtitle?: string;
  matchIds: string[];
}

export function App() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [bundle, setBundle] = useState<RunBundle | null>(null);
  const [healthMode, setHealthMode] = useState<"live" | "replay" | "static">(
    isStaticMode() ? "static" : "live"
  );
  const [studioEnabled, setStudioEnabled] = useState<boolean>(false);
  const [studioOptions, setStudioOptions] = useState<StudioOptions | null>(null);
  const [activeJob, setActiveJob] = useState<StudioJob | null>(null);
  const [advising, setAdvising] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<DashboardTab>("feed");
  const [selectedMatchId, setSelectedMatchId] = useState<string | null>(null);
  const [followLive, setFollowLive] = useState<boolean>(true);
  const userPickedRunRef = useRef<boolean>(false);
  const [drawer, setDrawer] = useState<DrawerState>({
    isOpen: false,
    title: "",
    matchIds: [],
  });

  const refreshRunsAndBundle = useCallback(async (targetRunId?: string | null) => {
    const manifest = await fetchRuns();
    setRuns(manifest.runs);
    const idToLoad =
      targetRunId ?? manifest.default_run_id ?? manifest.runs[0]?.run_id ?? null;
    if (idToLoad) {
      setSelectedRunId(idToLoad);
      const nextBundle = await fetchRunBundle(idToLoad);
      setBundle(nextBundle);
    }
  }, []);

  // Load initial health + run list + studio options
  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        setLoading(true);
        const [health, manifest] = await Promise.all([
          fetchHealth().catch(
            (): HealthResponse => ({
              status: "ok",
              mode: isStaticMode() ? "static" : "live",
              replay: false,
              active_run_id: null,
              studio_enabled: false,
            })
          ),
          fetchRuns(),
        ]);
        if (cancelled) return;

        if (health.mode === "replay" || health.replay) {
          setHealthMode("replay");
        } else if (health.mode === "static" || isStaticMode()) {
          setHealthMode("static");
        } else {
          setHealthMode("live");
        }

        const isStudio = Boolean(health.studio_enabled && !isStaticMode());
        setStudioEnabled(isStudio);

        setRuns(manifest.runs);
        const initialId =
          health.active_run_id ??
          manifest.default_run_id ??
          manifest.runs[0]?.run_id ??
          null;
        setSelectedRunId(initialId);

        if (isStudio) {
          fetchStudioOptions()
            .then((opts) => {
              if (!cancelled) {
                setStudioOptions(opts);
                if (opts.active_job) {
                  setActiveJob(opts.active_job);
                }
              }
            })
            .catch(() => {
              // studio options optional fallback
            });

          // If no saved runs exist yet on this laptop, open straight to Choose Alice
          if (manifest.runs.length === 0) {
            setActiveTab("setup");
          }
        }

        setLoadError(null);
      } catch (err) {
        if (!cancelled) {
          setLoadError(
            err instanceof Error ? err.message : "Failed to load Courtroom runs"
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  // Load bundle whenever selectedRunId changes
  useEffect(() => {
    if (!selectedRunId) {
      setBundle(null);
      return;
    }
    setBundle(null);
    let cancelled = false;
    async function loadBundle() {
      try {
        const nextBundle = await fetchRunBundle(selectedRunId!);
        if (!cancelled) {
          setBundle(nextBundle);
          setLoadError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(
            err instanceof Error ? err.message : "Failed to load run bundle"
          );
        }
      }
    }
    loadBundle();
    return () => {
      cancelled = true;
    };
  }, [selectedRunId]);

  // Poll /api/runs in live mode so runs started externally appear automatically
  useEffect(() => {
    if (healthMode !== "live" || isStaticMode()) return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const manifest = await fetchRuns();
        if (cancelled) return;
        setRuns(manifest.runs);
        const newestId = manifest.default_run_id ?? manifest.runs[0]?.run_id ?? null;
        if (newestId && !userPickedRunRef.current) {
          setSelectedRunId((prev) => (prev === newestId ? prev : newestId));
        }
      } catch {
        // ignore transient polling errors
      }
    }, LIVE_RUNS_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [healthMode]);

  // Poll active studio job until completion/failure
  useEffect(() => {
    if (!activeJob || activeJob.status !== "running") return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const latest = await fetchStudioJob(activeJob.job_id);
        if (cancelled) return;
        setActiveJob(latest);
        if (latest.run_id && latest.run_id !== selectedRunId) {
          setSelectedRunId(latest.run_id);
        }
        if (latest.status !== "running") {
          window.clearInterval(timer);
          await refreshRunsAndBundle(latest.run_id ?? selectedRunId);
        }
      } catch {
        // ignore transient poll hiccups
      }
    }, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeJob, selectedRunId, refreshRunsAndBundle]);

  const initialEvents = useMemo(() => bundle?.events ?? [], [bundle]);

  const stream = useCourtStream({
    runId: selectedRunId,
    mode: healthMode,
    initialEvents,
    serverReplayActive: healthMode === "replay",
  });

  const aggregated = useMemo(
    () =>
      aggregateEvents(stream.visibleEvents, {
        source: bundle?.summary.source ?? (isStaticMode() ? "static" : "jsonl"),
        knownStandings: bundle?.standings,
      }),
    [stream.visibleEvents, bundle]
  );

  useEffect(() => {
    if (
      followLive &&
      (stream.isReplaying || healthMode === "live") &&
      aggregated.activeMatchId &&
      aggregated.summary?.status === "running"
    ) {
      setSelectedMatchId(aggregated.activeMatchId);
    } else if (!selectedMatchId && aggregated.matches.length > 0) {
      setSelectedMatchId(aggregated.matches[0].match.match_id);
    }
  }, [
    followLive,
    stream.isReplaying,
    healthMode,
    aggregated.activeMatchId,
    aggregated.summary?.status,
    aggregated.matches,
    selectedMatchId,
  ]);

  const activeSummary = aggregated.summary ?? bundle?.summary ?? null;
  const displayMatches = aggregated.matches;
  const allowBundleFallback = !stream.isReplaying && stream.totalEvents === 0;
  const displayStandings =
    aggregated.standings.length > 0
      ? aggregated.standings
      : allowBundleFallback
        ? (bundle?.standings ?? [])
        : [];
  const displayHeatmap =
    aggregated.heatmap ?? (allowBundleFallback ? (bundle?.heatmap ?? null) : null);

  const handleStartTrial = async (payload: StartTrialPayload) => {
    setLoadError(null);
    const job = await startStudioTrial(payload);
    setActiveJob(job);
    if (job.run_id) {
      setSelectedMatchId(null);
      setFollowLive(true);
      setSelectedRunId(job.run_id);
      const manifest = await fetchRuns().catch(() => null);
      if (manifest) setRuns(manifest.runs);
    }
    setActiveTab("feed");
  };

  const handleAskCaterpillar = async () => {
    if (!selectedRunId) return;
    setAdvising(true);
    setLoadError(null);
    try {
      await runStudioAdvise(selectedRunId);
      const nextBundle = await fetchRunBundle(selectedRunId);
      setBundle(nextBundle);
    } catch (err) {
      setLoadError(
        err instanceof Error ? err.message : "Caterpillar advice failed"
      );
    } finally {
      setAdvising(false);
    }
  };

  const handleRunRetrial = async (defense?: string) => {
    if (!selectedRunId) return;
    setLoadError(null);
    try {
      const job = await startStudioRetrial(selectedRunId, defense);
      setActiveJob(job);
    } catch (err) {
      setLoadError(
        err instanceof Error ? err.message : "Failed to start retrial"
      );
    }
  };

  const handleOpenHeatmapCell = (cell: AggregatedCellView) => {
    setDrawer({
      isOpen: true,
      title: `${formatDefenseName(cell.defense)} vs ${formatTacticLabel(cell.family)}`,
      subtitle: `${cell.scenarioLabel} · ${cell.leaks} of ${cell.matches} breached`,
      matchIds: cell.match_ids,
    });
  };

  const handleInspectMatches = (
    matchIds: string[],
    title: string,
    subtitle?: string
  ) => {
    setDrawer({
      isOpen: true,
      title,
      subtitle,
      matchIds,
    });
  };

  const showReplayBar = stream.isReplaying && stream.totalEvents > 0;
  const isRetrying =
    activeJob?.kind === "retrial" && activeJob.status === "running";

  return (
    <Layout
      runs={runs}
      selectedRunId={selectedRunId}
      onSelectRun={(id) => {
        userPickedRunRef.current = true;
        setSelectedMatchId(null);
        setDrawer((d) => ({ ...d, isOpen: false }));
        setSelectedRunId(id);
        if (activeTab === "setup") {
          setActiveTab("feed");
        }
      }}
      connectionMode={
        stream.isReplaying ? "replaying" : stream.connectionMode
      }
      calibration={bundle?.calibration ?? null}
      activeTab={activeTab}
      onTabChange={setActiveTab}
      activeSummary={activeSummary}
      studioEnabled={studioEnabled}
      activeJob={activeJob}
      canTriggerReplay={!stream.isReplaying && stream.totalEvents > 0}
      onTriggerReplay={stream.startLocalReplay}
      replayBar={
        showReplayBar ? (
          <ReplayControls
            isPlaying={stream.isPlaying}
            speed={stream.speed}
            cursor={stream.cursor}
            totalEvents={stream.totalEvents}
            onPlay={stream.play}
            onPause={stream.pause}
            onRestart={stream.restart}
            onSeek={stream.seek}
            onSpeedChange={stream.setSpeed}
            onExitReplay={
              healthMode !== "replay" ? stream.stopLocalReplay : undefined
            }
          />
        ) : undefined
      }
    >
      {loadError && (
        <div className="mb-4 rounded-2xl border border-[#f5b7c2] bg-[#fff1f2] px-4 py-3 text-xs font-medium text-[#a5152e]">
          {loadError}
        </div>
      )}

      {activeJob?.status === "failed" && activeJob.error && (
        <div className="mb-4 rounded-2xl border border-[#f5b7c2] bg-[#fff1f2] px-4 py-3 text-xs font-medium text-[#a5152e]">
          {activeJob.error}
        </div>
      )}

      {stream.error && (
        <div className="mb-4 rounded-2xl border border-[#f5c26b] bg-[#fef3c7] px-4 py-2.5 text-xs font-medium text-[#92400e]">
          {stream.error}
        </div>
      )}

      {loading && !bundle && activeTab !== "setup" ? (
        <div className="storybook-card rounded-3xl p-12 text-center font-editorial text-base text-[#5c4f41]">
          Opening the Wonderland Court storybook…
        </div>
      ) : (
        <>
          {activeTab === "setup" && studioEnabled && (
            <TrialSetupPanel
              options={studioOptions}
              activeJob={activeJob}
              hasExistingRuns={runs.length > 0}
              onStartTrial={handleStartTrial}
              onSkipToExisting={() => setActiveTab("feed")}
            />
          )}

          {activeTab === "feed" && (
            <CourtroomFeed
              matches={displayMatches}
              selectedMatchId={selectedMatchId}
              onSelectMatch={(id) => {
                setFollowLive(false);
                setSelectedMatchId(id);
              }}
              followLive={followLive}
              onToggleFollowLive={() => setFollowLive((f) => !f)}
              onNextChapter={() => setActiveTab("leaderboard")}
            />
          )}

          {activeTab === "leaderboard" && (
            <div className="space-y-6">
              <LeaderboardTable standings={displayStandings} />

              <TechniqueHeatmap
                heatmap={displayHeatmap}
                onSelectCell={handleOpenHeatmapCell}
              />

              <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setActiveTab("feed")}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-[#dec8a4] bg-[#fffdf9] px-4 py-2.5 text-sm font-semibold text-[#4a3b2c] transition hover:border-[#2b5b84] hover:text-[#2b5b84]"
                >
                  <ChevronLeft className="h-4 w-4" />
                  Back to Trials
                </button>

                <button
                  type="button"
                  onClick={() => setActiveTab("caterpillar")}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#2b5b84] px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-[#1e4568]"
                >
                  <span>Next: Caterpillar’s Fix</span>
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}

          {activeTab === "caterpillar" && (
            <div className="space-y-6">
              <CaterpillarPanel
                advice={bundle?.advice ?? null}
                retrial={bundle?.retrial ?? null}
                onInspectMatches={handleInspectMatches}
                studioEnabled={studioEnabled}
                canRunActions={Boolean(selectedRunId)}
                advising={advising}
                retrying={isRetrying}
                onAskCaterpillar={handleAskCaterpillar}
                onRunRetrial={handleRunRetrial}
              />

              <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setActiveTab("leaderboard")}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-[#dec8a4] bg-[#fffdf9] px-4 py-2.5 text-sm font-semibold text-[#4a3b2c] transition hover:border-[#2b5b84] hover:text-[#2b5b84]"
                >
                  <ChevronLeft className="h-4 w-4" />
                  Back to Scoreboard
                </button>

                {studioEnabled ? (
                  <button
                    type="button"
                    onClick={() => setActiveTab("setup")}
                    className="inline-flex items-center gap-2 rounded-xl bg-[#c81e3a] px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-[#a5152e]"
                  >
                    <Wand2 className="h-4 w-4" />
                    <span>Test Another Model</span>
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      if (displayMatches[0]) {
                        setSelectedMatchId(displayMatches[0].match.match_id);
                      }
                      setActiveTab("feed");
                    }}
                    className="inline-flex items-center gap-2 rounded-xl bg-[#2b5b84] px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-[#1e4568]"
                  >
                    <RotateCcw className="h-4 w-4" />
                    <span>Start Over from Trial 1</span>
                  </button>
                )}
              </div>
            </div>
          )}
        </>
      )}

      <TranscriptDrawer
        isOpen={drawer.isOpen}
        title={drawer.title}
        subtitle={drawer.subtitle}
        matchIds={drawer.matchIds}
        matches={
          displayMatches.length > 0 ? displayMatches : (bundle?.matches ?? [])
        }
        onClose={() => setDrawer((d) => ({ ...d, isOpen: false }))}
      />
    </Layout>
  );
}

export default App;
