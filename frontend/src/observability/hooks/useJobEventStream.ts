import { useEffect, useRef, useState } from "react";
import { api, JobEvent, JobStatus, normalizeTraceEvent } from "../../api";

type ConnectionState = "IDLE" | "CONNECTING" | "OPEN" | "CLOSED" | "ERROR";

type JobEventStreamState = {
  events: JobEvent[];
  latestEvent: JobEvent | null;
  connectionState: ConnectionState;
  error: string | null;
};

const MAX_RECONNECT_ATTEMPTS = 5;

function websocketUrl(jobId: string): string {
  const base = import.meta.env.VITE_WS_BASE_URL || "ws://localhost:8000";
  return `${base}/ws/jobs/${encodeURIComponent(jobId)}`;
}

function eventKey(event: JobEvent): string {
  return [
    event.sequence_number ?? "",
    event.event,
    event.created_at,
    event.duration_ms ?? "",
  ].join(":");
}

function withSequence(events: JobEvent[]): JobEvent[] {
  return events.map((event, index) => ({
    ...event,
    sequence_number: event.sequence_number ?? index + 1,
  }));
}

function isTerminalEvent(event: JobEvent): boolean {
  return event.event === "JOB_COMPLETED" || event.event === "ERROR_OCCURRED" || event.event === "JOB_FORCE_FAILED";
}

function isTerminalStatus(status?: JobStatus | null): boolean {
  return status === "DONE" || status === "FAILED";
}

export function useJobEventStream(
  jobId: string | null,
  onRefresh?: () => void,
  jobStatus?: JobStatus | null,
): JobEventStreamState {
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [connectionState, setConnectionState] = useState<ConnectionState>("IDLE");
  const [error, setError] = useState<string | null>(null);
  const reconnectAttempts = useRef(0);

  useEffect(() => {
    if (!jobId) {
      setEvents([]);
      setConnectionState("IDLE");
      setError(null);
      return;
    }
    const activeJobId = jobId;

    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let closedByEffect = false;
    let terminalSeen = isTerminalStatus(jobStatus);

    async function loadHistoricalEvents() {
      try {
        const historicalEvents = await api.listJobEvents(activeJobId);
        if (!closedByEffect) setEvents(withSequence(historicalEvents));
      } catch {
        if (!closedByEffect) setError("Could not load existing job events");
      }
    }

    function appendEvents(nextEvents: JobEvent[]) {
      setEvents((current) => {
        const seen = new Set(current.map(eventKey));
        const merged = [...current];
        nextEvents.forEach((event) => {
          const key = eventKey(event);
          if (!seen.has(key)) {
            seen.add(key);
            merged.push(event);
          }
        });
        return withSequence(merged);
      });
    }

    function connect() {
      if (closedByEffect || terminalSeen) return;
      setConnectionState("CONNECTING");
      socket = new WebSocket(websocketUrl(activeJobId));

      socket.onopen = () => {
        reconnectAttempts.current = 0;
        setConnectionState("OPEN");
        setError(null);
      };

      socket.onmessage = (message) => {
        try {
          const parsed = JSON.parse(message.data);
          const payload = Array.isArray(parsed) ? parsed : [parsed];
          const nextEvents = payload
            .map((item, index) => {
              const event = normalizeTraceEvent(item, events.length + index);
              return { ...event, job_id: event.job_id ?? activeJobId };
            });
          appendEvents(nextEvents);
          if (nextEvents.some(isTerminalEvent)) {
            terminalSeen = true;
            onRefresh?.();
            socket?.close();
          }
        } catch {
          setError("Received an invalid job event payload");
        }
      };

      socket.onerror = () => {
        setConnectionState("ERROR");
        setError("Job event stream connection failed");
      };

      socket.onclose = () => {
        if (closedByEffect) return;
        setConnectionState("CLOSED");
        if (terminalSeen || isTerminalStatus(jobStatus)) return;
        reconnectAttempts.current += 1;
        void loadHistoricalEvents();
        onRefresh?.();
        if (reconnectAttempts.current >= MAX_RECONNECT_ATTEMPTS) {
          setError("Job event stream stopped after repeated reconnect attempts");
          return;
        }
        const delay = Math.min(1000 * reconnectAttempts.current, 5000);
        reconnectTimer = window.setTimeout(connect, delay);
      };
    }

    setEvents([]);
    void loadHistoricalEvents();
    connect();

    return () => {
      closedByEffect = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [jobId, onRefresh, jobStatus]);

  return {
    events,
    latestEvent: events[events.length - 1] ?? null,
    connectionState,
    error,
  };
}
