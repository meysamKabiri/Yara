import { JobEvent } from "../../api";

function formatDuration(value?: number | null): string {
  if (value == null) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(2)}s`;
  return `${Math.round(value)}ms`;
}

function formatTimestamp(event: JobEvent): string {
  const value = event.timestamp ?? event.created_at;
  if (value == null) return "—";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function eventTone(eventName: string): string {
  if (eventName.includes("ERROR") || eventName.includes("FAILED")) return "error";
  if (eventName.includes("COMPLETED") || eventName.includes("SUCCESS")) return "success";
  if (eventName.includes("START") || eventName.includes("LLM") || eventName.includes("EXECUTION")) return "processing";
  return "idle";
}

export function EventItem({
  event,
  isSelected,
  isLatest,
  isReplayActive,
  onSelect,
}: {
  event: JobEvent;
  isSelected: boolean;
  isLatest: boolean;
  isReplayActive: boolean;
  onSelect: () => void;
}) {
  const tone = eventTone(event.event);
  return (
    <button
      type="button"
      className={`event-item ${tone} ${isSelected ? "selected" : ""} ${isLatest ? "latest" : ""} ${isReplayActive ? "replay-active" : ""}`}
      onClick={onSelect}
    >
      <span className="event-dot" aria-hidden="true" />
      <span className="event-main">
        <span className="event-name">{event.event}</span>
        <span className="event-meta">#{event.sequence_number ?? "—"} · {formatTimestamp(event)}</span>
      </span>
      <span className="event-duration">{formatDuration(event.duration_ms)}</span>
    </button>
  );
}
