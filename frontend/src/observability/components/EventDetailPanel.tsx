import { JobEvent } from "../../api";

function formatDuration(value?: number | null): string {
  if (value == null) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(2)}s`;
  return `${Math.round(value)}ms`;
}

export function EventDetailPanel({ event }: { event: JobEvent | null }) {
  if (!event) {
    return (
      <aside className="observability-panel event-detail-panel">
        <span className="observability-kicker">Debug Inspector</span>
        <div className="event-detail-empty">Select an event to inspect its payload.</div>
      </aside>
    );
  }

  const eventName = event.event || "UNKNOWN_EVENT";
  const payload = {
    event: eventName,
    trace_id: event.trace_id,
    job_id: event.job_id ?? event.payload?.job_id,
    duration_ms: event.duration_ms,
    sequence_number: event.sequence_number,
    payload: event.payload,
  };

  return (
    <aside className="observability-panel event-detail-panel">
      <div className="observability-panel-header">
        <div>
          <span className="observability-kicker">Debug Inspector</span>
          <h2>{eventName}</h2>
        </div>
      </div>
      <dl className="event-detail-meta">
        <div>
          <dt>Trace</dt>
          <dd><code>{event.trace_id}</code></dd>
        </div>
        <div>
          <dt>Latency</dt>
          <dd>{formatDuration(event.duration_ms)}</dd>
        </div>
        <div>
          <dt>Sequence</dt>
          <dd>#{event.sequence_number ?? "—"}</dd>
        </div>
      </dl>
      <pre className="json-viewer">{JSON.stringify(payload, null, 2)}</pre>
    </aside>
  );
}
