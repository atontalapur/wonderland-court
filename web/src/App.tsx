import { useEffect, useMemo, useState } from "react";
import {
  fetchHealth,
  fetchRunBundle,
  fetchRuns,
  isStaticMode,
} from "./api/client";
import { useCourtStream } from "./api/sse";
import { CaterpillarPanel } from "./components/CaterpillarPanel";
import { CourtroomFeed } from "./components/CourtroomFeed";
import { DefenseTradeoffPlot } from "./components/DefenseTradeoffPlot";
import { Layout, type DashboardTab } from "./components/Layout";
import { LeaderboardTable } from "./components/LeaderboardTable";
import { ReplayControls } from "./components/ReplayControls";
import {
  TechniqueHeatmap,
  type AggregatedCellView,
} from "./components/TechniqueHeatmap";
import { TranscriptDrawer } from "./components/TranscriptDrawer";
import { aggregateEvents } from "./state/streamAggregator";
import type { HealthResponse, RunBundle, RunSummary } from "./types/events";

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
  const [loading, setLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<DashboardTab>("feed");
  const [selectedMatchId, setSelectedMatchId] = useState<string | null>(null);
  const [followLive, setFollowLive] = useState<boolean>(true);
  const [drawer, setDrawer] = useState<DrawerState>({
    isOpen: false,
    title: "",
    matchIds: [],
  });

  // Load initial health + run list
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

        setRuns(manifest.runs);
        const initialId =
          health.active_run_id ??
          manifest.default_run_id ??
          manifest.runs[0]?.run_id ??
          null;
        setSelectedRunId(initialId);
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
    if (!selectedRunId) return;
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

  // Follow live active match
  useEffect(() => {
    if (followLive && aggregated.activeMatchId) {
      setSelectedMatchId(aggregated.activeMatchId);
    } else if (!selectedMatchId && aggregated.matches.length > 0) {
      setSelectedMatchId(aggregated.matches[0].match.match_id);
    }
  }, [followLive, aggregated.activeMatchId, aggregated.matches, selectedMatchId]);

  const activeSummary = aggregated.summary ?? bundle?.summary ?? null;
  const displayMatches = aggregated.matches;
  const displayStandings =
    aggregated.standings.length > 0
      ? aggregated.standings
      : bundle?.standings ?? [];
  const displayHeatmap = aggregated.heatmap ?? bundle?.heatmap ?? null;

  const handleOpenHeatmapCell = (cell: AggregatedCellView) => {
    setDrawer({
      isOpen: true,
      title: `${cell.defense} vs ${cell.family}`,
      subtitle: `${cell.scenarioLabel} · ${cell.leaks}/${cell.matches} leaks (${Math.round(cell.asr * 100)}% ASR)`,
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

  return (
    <Layout
      runs={runs}
      selectedRunId={selectedRunId}
      onSelectRun={(id) => {
        setSelectedMatchId(null);
        setSelectedRunId(id);
      }}
      connectionMode={
        stream.isReplaying && healthMode === "static"
          ? "replaying"
          : stream.connectionMode
      }
      calibration={bundle?.calibration ?? null}
      activeTab={activeTab}
      onTabChange={setActiveTab}
      activeSummary={activeSummary}
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
        <div className="mb-4 rounded-xl border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-xs text-rose-200">
          {loadError}
        </div>
      )}

      {stream.error && (
        <div className="mb-4 rounded-xl border border-amber-500/40 bg-amber-950/25 px-4 py-2.5 text-xs text-amber-200">
          {stream.error}
        </div>
      )}

      {loading && !bundle ? (
        <div className="court-card rounded-xl p-10 text-center text-sm text-slate-400">
          Summoning the Courtroom docket…
        </div>
      ) : (
        <>
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
            />
          )}

          {activeTab === "leaderboard" && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
                <div className="xl:col-span-7">
                  <LeaderboardTable standings={displayStandings} />
                </div>
                <div className="xl:col-span-5">
                  <DefenseTradeoffPlot standings={displayStandings} />
                </div>
              </div>

              <TechniqueHeatmap
                heatmap={displayHeatmap}
                onSelectCell={handleOpenHeatmapCell}
              />
            </div>
          )}

          {activeTab === "caterpillar" && (
            <CaterpillarPanel
              advice={bundle?.advice ?? null}
              retrial={bundle?.retrial ?? null}
              onInspectMatches={handleInspectMatches}
            />
          )}
        </>
      )}

      <TranscriptDrawer
        isOpen={drawer.isOpen}
        title={drawer.title}
        subtitle={drawer.subtitle}
        matchIds={drawer.matchIds}
        matches={displayMatches.length > 0 ? displayMatches : bundle?.matches ?? []}
        onClose={() => setDrawer((d) => ({ ...d, isOpen: false }))}
      />
    </Layout>
  );
}

export default App;
