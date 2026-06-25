import { TraceDetail } from "../api";

type TraceViewerProps = {
  trace: TraceDetail | null;
};

function formatPayload(payload: Record<string, unknown>): string {
  const entries = Object.entries(payload).filter(([, value]) => value !== null && value !== undefined);
  if (entries.length === 0) return "بدون جزئیات";
  return entries
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`)
    .join(" · ");
}

export function TraceViewer({ trace }: TraceViewerProps) {
  if (!trace?.trace_id) return null;
  return (
    <aside className="trace-viewer" aria-label="Trace timeline">
      <div className="trace-viewer-header">
        <span>ردیابی درخواست</span>
        <code>{trace.trace_id}</code>
      </div>
      <ol>
        {trace.events.map((event, index) => {
          const eventName = event.event || "UNKNOWN_EVENT";
          return (
            <li key={`${eventName}-${index}`}>
              <div>
                <strong>{eventName}</strong>
                {event.duration_ms !== null && <span>{event.duration_ms} ms</span>}
              </div>
              <p>{formatPayload(event.payload)}</p>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}
