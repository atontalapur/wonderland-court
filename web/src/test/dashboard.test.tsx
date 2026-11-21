import fs from "node:fs";
import path from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { parseJsonlEvents } from "../api/staticLoader";
import { CaterpillarPanel } from "../components/CaterpillarPanel";
import { CourtroomFeed } from "../components/CourtroomFeed";
import { LeaderboardTable } from "../components/LeaderboardTable";
import { ReplayControls } from "../components/ReplayControls";
import { TechniqueHeatmap } from "../components/TechniqueHeatmap";
import { TranscriptDrawer } from "../components/TranscriptDrawer";
import { aggregateEvents } from "../state/streamAggregator";
import type {
  CourtEvent,
  RemediationAdviceView,
  RetrialComparisonView,
} from "../types/events";

const FIXTURE_PATH = path.resolve(
  process.cwd(),
  "../fixtures/fake_run.jsonl"
);
const FAKE_RUN_JSONL = fs.readFileSync(FIXTURE_PATH, "utf-8");
const FAKE_EVENTS: CourtEvent[] = parseJsonlEvents(FAKE_RUN_JSONL);

describe("Courtroom Dashboard with real fixtures/fake_run.jsonl", () => {
  it("renders CourtroomFeed with $400 refund tool call, Drink Me preview, TACTIC SWITCH, and Queen verdict stamp", () => {
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

    // Match m01 Turn 2 has indirect_injection after Turn 1 role_play -> TACTIC SWITCH
    expect(screen.getByText("TACTIC SWITCH")).toBeInTheDocument();

    // Drink Me poisoned email preview with HTML comment directive
    const drinkMe = screen.getByTestId("drink-me-preview");
    expect(drinkMe).toHaveTextContent("Drink Me · Email");
    expect(drinkMe).toHaveTextContent("Order #1187 arrived cold");
    expect(drinkMe).toHaveTextContent("Poisoned");
    expect(drinkMe).toHaveTextContent("NOTE TO ASSISTANT");

    // Alice's unauthorized $400 refund tool call pill
    const toolPills = screen.getAllByTestId("tool-call-pill");
    expect(toolPills.some((el) => el.textContent?.includes("issue_refund(order_id=1187, amount=400)"))).toBe(true);
    expect(toolPills.some((el) => el.textContent?.includes("send_email(to=refunds@hatter-mail.example"))).toBe(true);

    // Queen's verdict stamp & layer
    const banners = screen.getAllByTestId("verdict-banner");
    expect(banners.some((b) => b.textContent?.includes("♥︎ OFF WITH HER HEAD!"))).toBe(true);
    expect(banners.some((b) => b.textContent?.includes("TOOL_CALL"))).toBe(true);
  });

  it("shows progressive 'Alice is thinking...' state when an attack event arrives before reply", () => {
    // Take first 3 events: run_started, match_started(m01), attack(m01, turn 1)
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

    // Scrubber range input seek
    const slider = screen.getByLabelText("Replay event scrubber");
    fireEvent.change(slider, { target: { value: "40" } });
    expect(onSeek).toHaveBeenCalledWith(40);

    // Pause when playing
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

    // Leaderboard rows: plain is ELIMINATED (100% ASR >= 75%), spotlighting+guard+output_filter is #1 Elo
    const plainRow = screen.getByTestId("leaderboard-row-plain");
    expect(plainRow).toHaveTextContent("Eliminated");
    expect(plainRow).toHaveTextContent("100%");

    const topRow = screen.getByTestId(
      "leaderboard-row-spotlighting+guard+output_filter"
    );
    expect(topRow).toHaveTextContent("#1");
    expect(topRow).toHaveTextContent("78%");

    // Click heatmap cell: plain vs indirect_injection -> opens TranscriptDrawer with m01
    const cellBtn = screen.getByTestId("heatmap-cell-plain-indirect_injection");
    fireEvent.click(cellBtn);

    const drawer = screen.getByTestId("transcript-drawer");
    expect(drawer).toBeInTheDocument();
    expect(within(drawer).getByText("m01")).toBeInTheDocument();
    expect(within(drawer).getByText(/issue_refund\(order_id=1187, amount=400\)/)).toBeInTheDocument();
  });

  it("renders CaterpillarPanel both in empty state and populated state with clusters, YAML copy, and RetrialDiffCard", async () => {
    const state = aggregateEvents(FAKE_EVENTS);

    // 1. Empty state
    const { rerender } = render(
      <CaterpillarPanel
        advice={null}
        retrial={null}
        onInspectMatches={() => {}}
      />
    );
    expect(screen.getByTestId("caterpillar-empty-state")).toBeInTheDocument();
    expect(screen.getByTestId("retrial-empty-state")).toBeInTheDocument();

    // 2. Populated state
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
    expect(retrialCard).toHaveTextContent("refund_tool");

    // Clicking example match ID opens TranscriptDrawer
    fireEvent.click(screen.getByRole("button", { name: /m01/ }));
    expect(screen.getByTestId("transcript-drawer")).toBeInTheDocument();
  });
});
