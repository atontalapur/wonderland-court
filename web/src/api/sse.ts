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

  // Sync when runId or initialEvents change
  useEffect(() => {
    setEvents(initialEvents);
    setError(null);
    if (mode === "static") {
      setConnectionMode("static");
      if (autoPlayStatic) {
        setLocalReplayMode(true);
        setCursor(0);
        setIsPlaying(true);
      } else {
        setLocalReplayMode(false);
        setCursor(initialEvents.length);
        setIsPlaying(false);
      }
    } else if (mode === "replay") {
      setConnectionMode("replaying");
      if (serverReplayActive) {
        setLocalReplayMode(false);
        setEvents([]);
        setCursor(0);
        setIsPlaying(true);
      } else {
        setLocalReplayMode(true);
        setCursor(0);
        setIsPlaying(true);
      }
    } else {
      setLocalReplayMode(false);
      setCursor(initialEvents.length);
      setIsPlaying(false);
    }
  }, [runId, mode, initialEvents, serverReplayActive, autoPlayStatic]);

  // SSE subscription for live or server-replay mode
  useEffect(() => {
    if (!runId) return;
    if (isStaticMode() || mode === "static") return;
    if (mode === "replay" && (!serverReplayActive || localReplayMode)) return;

    const url =
      mode === "replay"
        ? `/api/replay/stream?speed=${speed}`
        : `/api/runs/${encodeURIComponent(runId)}/stream`;

    if (typeof EventSource === "undefined") {
      return;
    }

    const es = new EventSource(url);
    eventSourceRef.current = es;

    const handlePayload = (rawData: string) => {
      try {
        const parsed = JSON.parse(rawData) as CourtEvent;
        if (!parsed || typeof parsed.type !== "string") return;
        setEvents((prev) => {
          const next = mergeEvent(prev, parsed);
          setCursor(next.length);
          return next;
        });
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
  }, [runId, mode, speed, serverReplayActive, localReplayMode]);

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

  const play = useCallback(() => {
    if (!localReplayMode) {
      setLocalReplayMode(true);
    }
    setCursor((c) => (c >= events.length ? 0 : c));
    setIsPlaying(true);
  }, [localReplayMode, events.length]);

  const pause = useCallback(() => {
    if (!localReplayMode && mode === "replay") {
      setLocalReplayMode(true);
    }
    setIsPlaying(false);
  }, [localReplayMode, mode]);

  const restart = useCallback(() => {
    setLocalReplayMode(true);
    setCursor(0);
    setIsPlaying(true);
  }, []);

  const seek = useCallback(
    (index: number) => {
      const clamped = Math.max(0, Math.min(events.length, index));
      setLocalReplayMode(true);
      setIsPlaying(false);
      setCursor(clamped);
    },
    [events.length]
  );

  const setSpeed = useCallback((nextSpeed: ReplaySpeed) => {
    setSpeedState(nextSpeed);
  }, []);

  const startLocalReplay = useCallback(() => {
    setLocalReplayMode(true);
    setCursor(0);
    setIsPlaying(true);
  }, []);

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
