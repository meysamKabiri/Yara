import { JobEvent } from "../../api";
import { EventItem } from "./EventItem";

type FilterMode = "ALL" | "ERROR" | "LLM" | "EXECUTION";

function matchesFilter(event: JobEvent, filter: FilterMode): boolean {
  const eventName = event.event || "";
  if (filter === "ALL") return true;
  if (filter === "ERROR") return eventName.includes("ERROR") || eventName.includes("FAILED");
  if (filter === "LLM") return eventName.includes("LLM") || eventName.includes("DOMAIN");
  return eventName.includes("EXECUTION") || eventName.includes("DB_WRITE");
}

export function EventTimeline({
  events,
  selectedEvent,
  filter,
  replayIndex,
  onFilterChange,
  onSelectEvent,
  onReplay,
}: {
  events: JobEvent[];
  selectedEvent: JobEvent | null;
  filter: FilterMode;
  replayIndex: number | null;
  onFilterChange: (filter: FilterMode) => void;
  onSelectEvent: (event: JobEvent) => void;
  onReplay: () => void;
}) {
  const visibleEvents = events.filter((event) => matchesFilter(event, filter));
  const latestEvent = events.length ? events[events.length - 1] : undefined;

  return (
    <section className="observability-panel timeline-panel">
      <div className="observability-panel-header">
        <div>
          <span className="observability-kicker">Event Timeline</span>
          <h2>Execution flow</h2>
        </div>
        <button type="button" className="observability-small-button" onClick={onReplay} disabled={!events.length}>
          Replay execution
        </button>
      </div>
      <div className="event-filter-row" role="tablist" aria-label="Event filters">
        {(["ALL", "ERROR", "LLM", "EXECUTION"] as FilterMode[]).map((item) => (
          <button key={item} type="button" className={filter === item ? "active" : ""} onClick={() => onFilterChange(item)}>
            {item}
          </button>
        ))}
      </div>
      <div className="timeline-list">
        {visibleEvents.map((event) => (
          <EventItem
            key={`${event.sequence_number}-${event.event || "UNKNOWN_EVENT"}-${event.created_at}`}
            event={event}
            isSelected={selectedEvent === event}
            isLatest={latestEvent === event}
            isReplayActive={replayIndex === (event.sequence_number ?? 0) - 1}
            onSelect={() => onSelectEvent(event)}
          />
        ))}
      </div>
      {!visibleEvents.length && <div className="jobs-empty-state">No matching events.</div>}
    </section>
  );
}
