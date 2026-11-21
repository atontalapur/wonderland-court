import fs from "node:fs";
import path from "node:path";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { parseJsonlEvents } from "../api/staticLoader";
import { useCourtStream, type UseCourtStreamOptions } from "../api/sse";
import { CalibrationBadge } from "../components/CalibrationBadge";
import { CaterpillarPanel } from "../components/CaterpillarPanel";
import { CourtroomFeed } from "../components/CourtroomFeed";
import { LeaderboardTable } from "../components/LeaderboardTable";
import { ReplayControls } from "../components/ReplayControls";
import { TechniqueHeatmap } from "../components/TechniqueHeatmap";
import { TranscriptDrawer } from "../components/TranscriptDrawer";
import { TurnCard } from "../components/TurnCard";
import { aggregateEvents } from "../state/streamAggregator";
import type {
  CourtEvent,
  RemediationAdviceView,
  RetrialComparisonView,
  RunBundle,
} from "../types/events";

const FIXTURE_PATH = path.resolve(
  process.cwd(),
  "../fixtures/fake_run.jsonl"
);
const FAKE_RUN_JSONL = fs.readFileSync(FIXTURE_PATH, "utf-8");
const FAKE_EVENTS: CourtEvent[] = parseJsonlEvents(FAKE_RUN_JSONL);

describe("Wonderland Court Storybook Dashboard with real fixtures/fake_run.jsonl", () => {
  it("steps linearly through turns with character thought/chat bubbles, Drink Me preview, tool calls, and Queen verdict", () => {
    const state = aggregateEvents(FAKE_EVENTS);

    render(
      <CourtroomFeed
        matches={state.matches}
        selectedMatchId="m01"
        onSelectMatch={() => {}}
        followLive={false}
        onToggleFollowLive={() => {}}
      />
    );

    // Starts focused on Turn 1 with Cheshire Cat & Alice thought bubbles
    expect(screen.getByTestId("turn-card-1")).toBeInTheDocument();
    expect(screen.getByTestId("attacker-thought")).toBeInTheDocument();
    expect(screen.getByTestId("alice-thought")).toBeInTheDocument();

    // Linear click to Turn 2 (Mad Hatter's poisoned Drink Me email + tactic switch + $400 refund)
    fireEvent.click(screen.getByRole("button", { name: /Next Turn/i }));

    expect(screen.getByTestId("turn-card-2")).toBeInTheDocument();
    expect(screen.getByText("New Tactic")).toBeInTheDocument();

    const drinkMe = screen.getByTestId("drink-me-preview");
    expect(drinkMe).toHaveTextContent("Drink Me · Email");
    expect(drinkMe).toHaveTextContent("Order #1187 arrived cold");
    expect(drinkMe).toHaveTextContent("Poisoned");
    expect(drinkMe).toHaveTextContent("NOTE TO ASSISTANT");

    const toolPills = screen.getAllByTestId("tool-call-pill");
    expect(
      toolPills.some((el) =>
        el.textContent?.includes("issue_refund(order_id=1187, amount=400)")
      )
    ).toBe(true);
    expect(
      toolPills.some((el) =>
        el.textContent?.includes("send_email(to=refunds@hatter-mail.example")
      )
    ).toBe(true);

    const banner = screen.getByTestId("verdict-banner");
    expect(banner).toHaveTextContent("♥ OFF WITH HER HEAD!");
  });

  it("shows progressive 'Alice is thinking...' state when an attack event arrives before reply", () => {
    const partialState = aggregateEvents(FAKE_EVENTS.slice(0, 3));

    render(
      <CourtroomFeed
        matches={partialState.matches}
        selectedMatchId="m01"
        onSelectMatch={() => {}}
        followLive={true}
        onToggleFollowLive={() => {}}
      />
    );

    expect(screen.getByText("Alice is thinking...")).toBeInTheDocument();
  });

  it("controls ReplayControls play/pause, restart, speed toggles, progress counter, and scrubber bar", () => {
    const onPlay = vi.fn();
    const onPause = vi.fn();
    const onRestart = vi.fn();
    const onSeek = vi.fn();
    const onSpeedChange = vi.fn();

    const { rerender } = render(
      <ReplayControls
        isPlaying={false}
        speed={2}
        cursor={12}
        totalEvents={FAKE_EVENTS.length}
        onPlay={onPlay}
        onPause={onPause}
        onRestart={onRestart}
        onSeek={onSeek}
        onSpeedChange={onSpeedChange}
      />
    );

    expect(screen.getByTestId("replay-progress")).toHaveTextContent(
      `Event 12 / ${FAKE_EVENTS.length}`
    );

    fireEvent.click(screen.getByRole("button", { name: "Play replay" }));
    expect(onPlay).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Restart replay" }));
    expect(onRestart).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "4x" }));
    expect(onSpeedChange).toHaveBeenCalledWith(4);

    const slider = screen.getByLabelText("Replay event scrubber");
    fireEvent.change(slider, { target: { value: "40" } });
    expect(onSeek).toHaveBeenCalledWith(40);

    rerender(
      <ReplayControls
        isPlaying={true}
        speed={4}
        cursor={40}
        totalEvents={FAKE_EVENTS.length}
        onPlay={onPlay}
        onPause={onPause}
        onRestart={onRestart}
        onSeek={onSeek}
        onSpeedChange={onSpeedChange}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Pause replay" }));
    expect(onPause).toHaveBeenCalledTimes(1);
  });

  it("renders LeaderboardTable and opens TranscriptDrawer when clicking a TechniqueHeatmap cell", () => {
    const state = aggregateEvents(FAKE_EVENTS);

    function Harness() {
      const [drawerMatchIds, setDrawerMatchIds] = useState<string[] | null>(null);
      return (
        <>
          <LeaderboardTable standings={state.standings} />
          <TechniqueHeatmap
            heatmap={state.heatmap}
            onSelectCell={(cell) => setDrawerMatchIds(cell.match_ids)}
          />
          <TranscriptDrawer
            isOpen={drawerMatchIds !== null}
            title="Inspect Cell Transcripts"
            matchIds={drawerMatchIds ?? []}
            matches={state.matches}
            onClose={() => setDrawerMatchIds(null)}
          />
        </>
      );
    }

    render(<Harness />);

    const plainRow = screen.getByTestId("leaderboard-row-plain");
    expect(plainRow).toHaveTextContent("Eliminated");
    expect(plainRow).toHaveTextContent("100% breached");

    const topRow = screen.getByTestId(
      "leaderboard-row-spotlighting+guard+output_filter"
    );
    expect(topRow).toHaveTextContent("#1");
    expect(topRow).toHaveTextContent("78% helpful");

    const cellBtn = screen.getByTestId("heatmap-cell-plain-indirect_injection");
    fireEvent.click(cellBtn);

    const drawer = screen.getByTestId("transcript-drawer");
    expect(drawer).toBeInTheDocument();
    expect(
      within(drawer).getByText(/issue_refund\(order_id=1187, amount=400\)/)
    ).toBeInTheDocument();
  });

  it("renders CaterpillarPanel in empty and populated states with YAML copy and RetrialDiffCard", async () => {
    const state = aggregateEvents(FAKE_EVENTS);

    const { rerender } = render(
      <CaterpillarPanel
        advice={null}
        retrial={null}
        onInspectMatches={() => {}}
      />
    );
    expect(screen.getByTestId("caterpillar-empty-state")).toBeInTheDocument();
    expect(screen.getByTestId("retrial-empty-state")).toBeInTheDocument();

    const advice: RemediationAdviceView = {
      run_id: "fake-run-0001",
      target_kind: "model",
      clusters: [
        {
          cluster_id: "c1",
          family_label: "Indirect Prompt Injection via Customer Email",
          technique_family: "indirect_injection",
          scenario: "refund_tool",
          count: 1,
          example_match_ids: ["m01"],
          root_cause_summary:
            "Untrusted HTML comment directives inside customer emails overrode refund limits.",
        },
      ],
      recommended_defense: "spotlighting+guard+output_filter",
      config_patch_yaml:
        "defense: spotlighting+guard+output_filter\ntool_rules:\n  - issue_refund.max_value: 50\n",
      rationale:
        "Spotlighting isolates untrusted email content while guard blocks injected overrides.",
    };

    const retrial: RetrialComparisonView = {
      baseline_run_id: "fake-run-0001",
      retrial_run_id: "fake-run-0002",
      matched_seeds: [2751, 3317, 4915],
      baseline_asr: 0.375,
      retrial_asr: 0.0,
      asr_delta: -0.375,
      baseline_utility: 0.89,
      retrial_utility: 0.86,
      per_scenario_diff: {
        refund_tool: { baseline_asr: 0.25, retrial_asr: 0.0 },
        vault: { baseline_asr: 0.5, retrial_asr: 0.0 },
      },
    };

    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: { writeText: writeTextMock },
    });

    function PopulatedHarness() {
      const [drawerIds, setDrawerIds] = useState<string[] | null>(null);
      return (
        <>
          <CaterpillarPanel
            advice={advice}
            retrial={retrial}
            onInspectMatches={(ids) => setDrawerIds(ids)}
          />
          <TranscriptDrawer
            isOpen={drawerIds !== null}
            title="Cluster Transcript"
            matchIds={drawerIds ?? []}
            matches={state.matches}
            onClose={() => setDrawerIds(null)}
          />
        </>
      );
    }

    rerender(<PopulatedHarness />);

    expect(
      screen.getByText("Indirect Prompt Injection via Customer Email")
    ).toBeInTheDocument();
    expect(screen.getByTestId("yaml-patch-block")).toHaveTextContent(
      "defense: spotlighting+guard+output_filter"
    );

    fireEvent.click(screen.getByRole("button", { name: "Copy YAML" }));
    expect(writeTextMock).toHaveBeenCalledWith(advice.config_patch_yaml);
    await screen.findByText("Copied!");

    const retrialCard = screen.getByTestId("retrial-diff-card");
    expect(retrialCard).toHaveTextContent("ASR Δ -37.5%");
    expect(retrialCard).toHaveTextContent("The Refund Ledger");

    fireEvent.click(screen.getByRole("button", { name: /m01/ }));
    expect(screen.getByTestId("transcript-drawer")).toBeInTheDocument();
  });

  it("computes fallback standings from match_ended events when no standings event is present", () => {
    const withoutStandings = FAKE_EVENTS.filter((e) => e.type !== "standings");
    const state = aggregateEvents(withoutStandings);
    expect(state.standings.length).toBeGreaterThan(0);
    expect(state.standings[0].elo).toBeGreaterThanOrEqual(
      state.standings[state.standings.length - 1].elo
    );
  });

  it("renders untrusted HTML/script payloads safely without executing or injecting DOM tags", () => {
    const xssPayload =
      '<script>window.__xss=1</script><img src=x onerror="alert(1)">';
    const baseState = aggregateEvents(FAKE_EVENTS);
    const sampleSlot = baseState.matches[0].liveTurns[0];
    const poisonedSlot = {
      ...sampleSlot,
      attack: sampleSlot.attack
        ? {
            ...sampleSlot.attack,
            message: xssPayload,
            document: {
              id: "doc-xss",
              kind: "email" as const,
              title: xssPayload,
              body: `<!-- ${xssPayload} --> Hello`,
              poisoned: true,
            },
          }
        : undefined,
      reply: sampleSlot.reply
        ? { ...sampleSlot.reply, content: xssPayload }
        : undefined,
      verdict: sampleSlot.verdict
        ? { ...sampleSlot.verdict, reason: xssPayload }
        : undefined,
    };

    const { container } = render(<TurnCard slot={poisonedSlot} />);
    expect(container.querySelectorAll("script")).toHaveLength(0);
    expect(container.querySelectorAll('img[src="x"]')).toHaveLength(0);
    expect(container.textContent).toContain("<script>window.__xss=1</script>");
  });

  it("dismisses CalibrationBadge popover on Escape key and outside click", () => {
    render(
      <div>
        <span data-testid="outside-target">outside</span>
        <CalibrationBadge
          calibration={{
            run_id: "run-1",
            total_exact_checked: 13,
            llm_evaluated: 8,
            agreement_count: 5,
            agreement_rate: 0.625,
            false_positives: 1,
            false_negatives: 2,
          }}
        />
      </div>
    );

    const btn = screen.getByRole("button", {
      name: /Judge Calibration: 63% \(5\/8\)/,
    });
    fireEvent.click(btn);
    expect(screen.getByText("Queen Judge Calibration")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      screen.queryByText("Queen Judge Calibration")
    ).not.toBeInTheDocument();

    fireEvent.click(btn);
    expect(screen.getByText("Queen Judge Calibration")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId("outside-target"));
    expect(
      screen.queryByText("Queen Judge Calibration")
    ).not.toBeInTheDocument();
  });
});

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((ev: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<
    string,
    Array<(ev: MessageEvent<string>) => void>
  >();

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(
    type: string,
    handler: (ev: MessageEvent<string>) => void
  ): void {
    const existing = this.listeners.get(type) ?? [];
    existing.push(handler);
    this.listeners.set(type, existing);
  }

  emit(type: string, payload: unknown): void {
    const ev = { data: JSON.stringify(payload) } as MessageEvent<string>;
    for (const fn of this.listeners.get(type) ?? []) {
      fn(ev);
    }
  }

  close(): void {
    this.closed = true;
  }
}

function StreamHarness({ options }: { options: UseCourtStreamOptions }) {
  const stream = useCourtStream(options);
  return (
    <div>
      <div data-testid="event-count">{stream.events.length}</div>
      <div data-testid="visible-count">{stream.visibleEvents.length}</div>
      <div data-testid="cursor">{stream.cursor}</div>
      <div data-testid="is-replaying">{String(stream.isReplaying)}</div>
      <button type="button" onClick={stream.startLocalReplay}>
        StartReplay
      </button>
      <button type="button" onClick={stream.pause}>
        Pause
      </button>
      <button type="button" onClick={() => stream.setSpeed(4)}>
        Speed4
      </button>
    </div>
  );
}

describe("useCourtStream & App lifecycle guarantees", () => {
  afterEach(() => {
    MockEventSource.instances = [];
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("merges late initialEvents without dropping SSE events or reconnecting live EventSource on replay toggles", () => {
    vi.stubGlobal("EventSource", MockEventSource);
    const ev0 = FAKE_EVENTS[0];
    const ev1 = FAKE_EVENTS[1];
    const ev2 = FAKE_EVENTS[2];

    const { rerender, unmount } = render(
      <StreamHarness
        options={{
          runId: ev0.run_id,
          mode: "live",
          initialEvents: [],
        }}
      />
    );

    expect(MockEventSource.instances).toHaveLength(1);
    const es = MockEventSource.instances[0];

    act(() => {
      es.emit(ev2.type, ev2);
    });
    expect(screen.getByTestId("event-count")).toHaveTextContent("1");

    rerender(
      <StreamHarness
        options={{
          runId: ev0.run_id,
          mode: "live",
          initialEvents: [ev0, ev1],
        }}
      />
    );

    expect(screen.getByTestId("event-count")).toHaveTextContent("3");
    expect(MockEventSource.instances).toHaveLength(1);
    expect(es.closed).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Speed4" }));
    fireEvent.click(screen.getByRole("button", { name: "StartReplay" }));
    expect(MockEventSource.instances).toHaveLength(1);
    expect(es.closed).toBe(false);

    unmount();
    expect(es.closed).toBe(true);
  });

  it("pauses server-replay mode at the current streamed event count instead of resetting to 0", () => {
    vi.stubGlobal("EventSource", MockEventSource);
    const ev0 = FAKE_EVENTS[0];
    const ev1 = FAKE_EVENTS[1];

    render(
      <StreamHarness
        options={{
          runId: ev0.run_id,
          mode: "replay",
          serverReplayActive: true,
          initialEvents: [],
        }}
      />
    );

    const es = MockEventSource.instances[0];
    act(() => {
      es.emit(ev0.type, ev0);
      es.emit(ev1.type, ev1);
    });

    expect(screen.getByTestId("visible-count")).toHaveTextContent("2");
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(screen.getByTestId("cursor")).toHaveTextContent("2");
    expect(screen.getByTestId("visible-count")).toHaveTextContent("2");
  });

  it("clears stale standings on run switch and avoids flashing completed standings at replay cursor 0", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    const agg = aggregateEvents(FAKE_EVENTS);
    const bundle1: RunBundle = {
      summary: agg.summary!,
      events: FAKE_EVENTS,
      matches: agg.matches,
      standings: agg.standings,
      heatmap: agg.heatmap!,
      calibration: null,
      advice: null,
      retrial: null,
    };
    const emptyRunSummary = {
      ...bundle1.summary,
      run_id: "pending-run",
      matches: 0,
      leaks: 0,
      status: "running" as const,
    };
    const emptyBundle: RunBundle = {
      summary: emptyRunSummary,
      events: [],
      standings: [],
      matches: [],
      heatmap: {
        run_id: "pending-run",
        defenses: [],
        families: [],
        scenarios: [],
        cells: [],
      },
      calibration: null,
      advice: null,
      retrial: null,
    };

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/health") {
          return {
            ok: true,
            json: async () => ({
              status: "ok",
              mode: "replay",
              replay: true,
              active_run_id: bundle1.summary.run_id,
            }),
          };
        }
        if (url === "/api/runs") {
          return {
            ok: true,
            json: async () => ({
              runs: [bundle1.summary, emptyRunSummary],
              default_run_id: bundle1.summary.run_id,
            }),
          };
        }
        if (url.includes("pending-run/bundle")) {
          return { ok: true, json: async () => emptyBundle };
        }
        return { ok: true, json: async () => bundle1 };
      })
    );

    render(<App />);
    await screen.findByText(/8 trials · 5 held · 3 breached/);

    fireEvent.click(screen.getByRole("button", { name: /Scoreboard/i }));
    expect(screen.queryByTestId("leaderboard-row-plain")).not.toBeInTheDocument();

    const selector = screen.getByLabelText("Select active run");
    fireEvent.change(selector, { target: { value: "pending-run" } });
    await waitFor(() => {
      expect(
        screen.queryByTestId("leaderboard-row-plain")
      ).not.toBeInTheDocument();
    });
  });
});
