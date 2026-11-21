import { useCallback, useEffect, useRef, useState } from "react";
import type { CourtEvent, StreamConnectionMode } from "../types/events";
import { isStaticMode } from "./client";

export type ReplaySpeed = 1 | 2 | 4;

const COURT_EVENT_TYPES: CourtEvent["type"][] = [
  "run_started",
  "match_started",
  "attack",
  "reply",
  "verdict",
  "match_ended",
  "standings",
  "run_ended",
];

export interface UseCourtStreamOptions {
  runId: string | null;
  mode: "live" | "replay" | "static";
  initialEvents: CourtEvent[];
  serverReplayActive?: boolean;
  speed?: ReplaySpeed;
  autoPlayStatic?: boolean;
}

export interface UseCourtStreamResult {
  events: CourtEvent[];
  visibleEvents: CourtEvent[];
  connectionMode: StreamConnectionMode;
  error: string | null;
  // Replay / Scrubbing controls
  isReplaying: boolean;
  isPlaying: boolean;
  speed: ReplaySpeed;
  cursor: number;
  totalEvents: number;
  play: () => void;
  pause: () => void;
  restart: () => void;
  seek: (index: number) => void;
  setSpeed: (speed: ReplaySpeed) => void;
  startLocalReplay: () => void;
  stopLocalReplay: () => void;
}

function mergeEvent(prev: CourtEvent[], incoming: CourtEvent): CourtEvent[] {
  if (prev.some((e) => e.seq === incoming.seq && e.run_id === incoming.run_id)) {
    return prev;
  }
  return [...prev, incoming].sort((a, b) => a.seq - b.seq);
}

function mergeEvents(
  prev: CourtEvent[],
  incoming: CourtEvent[]
): CourtEvent[] {
  if (incoming.length === 0) return prev;
  const seen = new Set(prev.map((e) => `${e.run_id}:${e.seq}`));
  const additions = incoming.filter((e) => !seen.has(`${e.run_id}:${e.seq}`));
  if (additions.length === 0) return prev;
  return [...prev, ...additions].sort((a, b) => a.seq - b.seq);
}

export function useCourtStream({
  runId,
  mode,
  initialEvents,
  serverReplayActive = false,
  speed: initialSpeed = 2,
  autoPlayStatic = false,
}: UseCourtStreamOptions): UseCourtStreamResult {
  const [events, setEvents] = useState<CourtEvent[]>(initialEvents);
  const [connectionMode, setConnectionMode] = useState<StreamConnectionMode>(
    isStaticMode() || mode === "static"
      ? "static"
      : mode === "replay"
        ? "replaying"
        : "live"
  );
  const [error, setError] = useState<string | null>(null);

  // Local deterministic replay / scrubber state
  const [localReplayMode, setLocalReplayMode] = useState<boolean>(
    (mode === "static" && autoPlayStatic) || (mode === "replay" && !serverReplayActive)
  );
  const [isPlaying, setIsPlaying] = useState<boolean>(
    (mode === "static" && autoPlayStatic) || mode === "replay"
  );
  const [speed, setSpeedState] = useState<ReplaySpeed>(initialSpeed);
  const [cursor, setCursor] = useState<number>(initialEvents.length);

  const eventSourceRef = useRef<EventSource | null>(null);
  const lastSeqRef = useRef<number>(-1);
  const initialEventsRef = useRef<CourtEvent[]>(initialEvents);
  initialEventsRef.current = initialEvents;

  // Reset stream state when the selected run or top-level mode changes
  useEffect(() => {
    lastSeqRef.current = -1;
    setEvents([]);
    setError(null);
    if (mode === "static") {
      setConnectionMode("static");
      if (autoPlayStatic) {
        setLocalReplayMode(true);
        setCursor(0);
        setIsPlaying(true);
      } else {
        setLocalReplayMode(false);
        setCursor(0);
        setIsPlaying(false);
      }
    } else if (mode === "replay") {
      setConnectionMode("replaying");
      if (serverReplayActive) {
        setLocalReplayMode(false);
        setCursor(0);
        setIsPlaying(true);
      } else {
        setLocalReplayMode(true);
        setCursor(0);
        setIsPlaying(true);
      }
    } else {
      setConnectionMode("live");
      setLocalReplayMode(false);
      setCursor(0);
      setIsPlaying(false);
    }
  }, [runId, mode, serverReplayActive, autoPlayStatic]);

  // Merge initial snapshot events once fetched without wiping SSE arrivals
  useEffect(() => {
    if (initialEvents.length === 0) return;
    if (mode === "replay" && serverReplayActive) return;
    const matching = runId
      ? initialEvents.filter((e) => e.run_id === runId)
      : initialEvents;
    if (matching.length === 0) return;

    for (const ev of matching) {
      if (ev.seq > lastSeqRef.current) {
        lastSeqRef.current = ev.seq;
      }
    }
    setEvents((prev) => mergeEvents(prev, matching));
  }, [runId, mode, serverReplayActive, initialEvents]);

  const sseUrl =
    !runId || isStaticMode() || mode === "static"
      ? null
      : mode === "replay"
        ? serverReplayActive && !localReplayMode
          ? `/api/replay/stream?speed=${speed}&from_seq=${lastSeqRef.current}`
          : null
        : `/api/runs/${encodeURIComponent(runId)}/stream`;

  // SSE subscription (only depends on sseUrl and mode so live speed/localReplay toggles don't reconnect)
  useEffect(() => {
    if (!sseUrl) return;
    if (typeof EventSource === "undefined") {
      return;
    }

    const es = new EventSource(sseUrl);
    eventSourceRef.current = es;

    const handlePayload = (rawData: string) => {
      try {
        const parsed = JSON.parse(rawData) as CourtEvent;
        if (!parsed || typeof parsed.type !== "string") return;
        if (parsed.seq > lastSeqRef.current) {
          lastSeqRef.current = parsed.seq;
        }
        setEvents((prev) => mergeEvent(prev, parsed));
        setConnectionMode(mode === "replay" ? "replaying" : "live");
        setError(null);
      } catch {
        // Ignore non-JSON keepalive comments
      }
    };

    es.onopen = () => {
      setConnectionMode(mode === "replay" ? "replaying" : "live");
      setError(null);
    };

    es.onmessage = (msg) => {
      handlePayload(msg.data);
    };

    for (const evType of COURT_EVENT_TYPES) {
      es.addEventListener(evType, (ev) => {
        handlePayload((ev as MessageEvent<string>).data);
      });
    }

    es.onerror = () => {
      setConnectionMode("disconnected");
      setError("Stream connection interrupted — attempting reconnect…");
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [sseUrl, mode]);

  // Client-side replay ticker (Static Archive replay or paused/scrubbed Replay)
  useEffect(() => {
    if (!localReplayMode || !isPlaying) return;
    if (cursor >= events.length) {
      setIsPlaying(false);
      return;
    }

    const baseIntervalMs = speed === 4 ? 140 : speed === 2 ? 300 : 620;
    const timer = window.setTimeout(() => {
      setCursor((c) => Math.min(events.length, c + 1));
    }, baseIntervalMs);

    return () => window.clearTimeout(timer);
  }, [localReplayMode, isPlaying, cursor, events.length, speed]);

  const mergeSnapshotOnLocalTakeover = useCallback(() => {
    const snap = runId
      ? initialEventsRef.current.filter((e) => e.run_id === runId)
      : initialEventsRef.current;
    if (snap.length > 0) {
      setEvents((prev) => mergeEvents(prev, snap));
    }
    return Math.max(events.length, snap.length);
  }, [runId, events.length]);

  const play = useCallback(() => {
    let total = events.length;
    if (!localReplayMode) {
      total = mergeSnapshotOnLocalTakeover();
      setLocalReplayMode(true);
    }
    setCursor((c) => (c >= total ? 0 : c));
    setIsPlaying(true);
  }, [localReplayMode, events.length, mergeSnapshotOnLocalTakeover]);

  const pause = useCallback(() => {
    if (!localReplayMode && mode === "replay") {
      const pausedAt = events.length;
      mergeSnapshotOnLocalTakeover();
      setCursor(pausedAt);
      setLocalReplayMode(true);
    }
    setIsPlaying(false);
  }, [localReplayMode, mode, events.length, mergeSnapshotOnLocalTakeover]);

  const restart = useCallback(() => {
    mergeSnapshotOnLocalTakeover();
    setLocalReplayMode(true);
    setCursor(0);
    setIsPlaying(true);
  }, [mergeSnapshotOnLocalTakeover]);

  const seek = useCallback(
    (index: number) => {
      const total = mergeSnapshotOnLocalTakeover();
      const clamped = Math.max(0, Math.min(total, index));
      setLocalReplayMode(true);
      setIsPlaying(false);
      setCursor(clamped);
    },
    [mergeSnapshotOnLocalTakeover]
  );

  const setSpeed = useCallback((nextSpeed: ReplaySpeed) => {
    setSpeedState(nextSpeed);
  }, []);

  const startLocalReplay = useCallback(() => {
    mergeSnapshotOnLocalTakeover();
    setLocalReplayMode(true);
    setCursor(0);
    setIsPlaying(true);
  }, [mergeSnapshotOnLocalTakeover]);

  const stopLocalReplay = useCallback(() => {
    setLocalReplayMode(false);
    setIsPlaying(false);
    setCursor(events.length);
  }, [events.length]);

  const visibleEvents = localReplayMode ? events.slice(0, cursor) : events;
  const effectiveCursor = localReplayMode ? cursor : events.length;

  return {
    events,
    visibleEvents,
    connectionMode,
    error,
    isReplaying: mode === "replay" || localReplayMode,
    isPlaying,
    speed,
    cursor: effectiveCursor,
    totalEvents: events.length,
    play,
    pause,
    restart,
    seek,
    setSpeed,
    startLocalReplay,
    stopLocalReplay,
  };
}
