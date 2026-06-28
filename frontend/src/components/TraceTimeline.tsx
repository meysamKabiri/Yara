import { useEffect, useState } from "react";
import { api, MetricTraceEvent, TraceMetricsResponse } from "../api";

function formatDuration(value: number | null): string {
  if (value == null) return "\u2014";
  if (value >= 1000) return `${(value / 1000).toFixed(2)}s`;
  return `${Math.round(value)}ms`;
}

function formatTimestamp(ts: string): string {
  const d = new Date(ts);
  const time = new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(d);
  const ms = String(d.getMilliseconds()).padStart(3, "0");
  return `${time}.${ms}`;
}

function isFailed(eventGroup?: string | null): boolean {
  return eventGroup === "FAILED" || eventGroup === "ERROR";
}

function isSlow(durationMs: number | null): boolean {
  return durationMs != null && durationMs > 100;
}

const GROUP_LABELS: Record<string, string> = {
  JOB: "Job",
  DOMAIN_ROUTER: "Domain Router",
  LLM: "LLM",
  EXECUTION_ENGINE: "Execution Engine",
  DB: "DB Events",
};

export function TraceTimeline({ traceId }: { traceId: string | null }) {
  const [data, setData] = useState<TraceMetricsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedPayloads, setExpandedPayloads] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!traceId) {
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.getTraceMetrics(traceId)
      .then((result) => { if (!cancelled) setData(result); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load trace"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [traceId]);

  const grouped: [string, MetricTraceEvent[]][] = (() => {
    if (!data) return [];
    const map = new Map<string, MetricTraceEvent[]>();
    for (const event of data.events) {
      const g = event.event_group || "OTHER";
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(event);
    }
    const order = ["JOB", "DOMAIN_ROUTER", "LLM", "EXECUTION_ENGINE", "DB", "OTHER"];
    return order.filter((k) => map.has(k)).map((k) => [k, map.get(k)!]);
  })();

  if (loading) {
    return <div className="trace-timeline-panel observability-panel"><div className="jobs-loading">Loading trace...</div></div>;
  }
  if (error) {
    return <div className="trace-timeline-panel observability-panel"><div className="observability-error">{error}</div></div>;
  }
  if (!data || !data.events.length) {
    return <div className="trace-timeline-panel observability-panel"><div className="jobs-empty-state">No trace events recorded.</div></div>;
  }

  return (
    <div className="trace-timeline-panel observability-panel">
      <div className="observability-panel-header">
        <div>
          <span className="observability-kicker">Persisted Trace</span>
          <h2>Execution timeline</h2>
        </div>
        <code className="trace-timeline-trace-id">{data.trace_id}</code>
      </div>
      <div className="trace-timeline-body">
        {grouped.map(([group, events]) => (
          <div key={group} className="trace-timeline-group">
            <div className="trace-timeline-group-header">
              <span className="trace-timeline-group-label">{GROUP_LABELS[group] ?? group}</span>
              <span className="trace-timeline-group-count">{events.length}</span>
            </div>
            <div className="trace-timeline-items">
              {events.map((event) => {
                const eventName = event.event_name || "UNKNOWN_EVENT";
                const eventGroup = event.event_group || "OTHER";
                const eventIndex = event.event_index ?? 0;
                const key = `${eventIndex}-${eventName}`;
                const isExpanded = expandedPayloads.has(key);
                const hasPayload = event.payload && Object.keys(event.payload).length > 0;
                const failed = isFailed(eventGroup);
                const slow = isSlow(event.duration_ms);

                return (
                  <div
                    key={key}
                    className={`trace-timeline-item ${failed ? "failed" : ""} ${slow ? "slow" : ""}`}
                  >
                    <div className="trace-timeline-item-line" />
                    <div className="trace-timeline-item-content">
                      <div className="trace-timeline-item-header">
                        <span className={`trace-timeline-event-dot ${failed ? "failed" : slow ? "slow" : ""}`} />
                        <span className="trace-timeline-event-name">{eventName}</span>
                        <span className="trace-timeline-event-duration">{formatDuration(event.duration_ms)}</span>
                        <span className="trace-timeline-event-timestamp">{formatTimestamp(event.timestamp)}</span>
                      </div>
                      {hasPayload && (
                        <button
                          type="button"
                          className="trace-timeline-payload-toggle"
                          onClick={() => {
                            setExpandedPayloads((prev) => {
                              const next = new Set(prev);
                              if (next.has(key)) next.delete(key);
                              else next.add(key);
                              return next;
                            });
                          }}
                        >
                          {isExpanded ? "Hide payload" : "Show payload"}
                        </button>
                      )}
                      {hasPayload && isExpanded && (
                        <pre className="trace-timeline-payload">{JSON.stringify(event.payload, null, 2)}</pre>
                      )}
                    </div>
                    <div className="trace-timeline-item-meta">
                      {slow && <span className="trace-timeline-badge slow-badge">slow</span>}
                      {failed && <span className="trace-timeline-badge failed-badge">failed</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
