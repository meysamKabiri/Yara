import { useEffect, useMemo, useState } from "react";
import { JobEvent } from "../../api";
import { TraceTimeline } from "../../components/TraceTimeline";
import { EventDetailPanel } from "../components/EventDetailPanel";
import { EventTimeline } from "../components/EventTimeline";
import { JobStatusBadge } from "../components/JobStatusBadge";
import { useJobEvents } from "../hooks/useJobEvents";

type FilterMode = "ALL" | "ERROR" | "LLM" | "EXECUTION";

function durationTotal(events: JobEvent[]): number {
  return events.reduce((sum, event) => sum + (event.duration_ms ?? 0), 0);
}

function formatDuration(value: number): string {
  if (!value) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(2)}s`;
  return `${Math.round(value)}ms`;
}

export function JobDetailPage({
  jobId,
  onBack,
}: {
  jobId: string;
  onBack: () => void;
}) {
  const { job, events, isLoading, error } = useJobEvents(jobId);
  const [selectedEvent, setSelectedEvent] = useState<JobEvent | null>(null);
  const [filter, setFilter] = useState<FilterMode>("ALL");
  const [replayIndex, setReplayIndex] = useState<number | null>(null);

  useEffect(() => {
    if (!selectedEvent && events.length) setSelectedEvent(events[events.length - 1] ?? null);
  }, [events, selectedEvent]);

  const totalDuration = useMemo(() => durationTotal(events), [events]);

  function replayExecution() {
    if (!events.length) return;
    setReplayIndex(0);
    events.forEach((event, index) => {
      window.setTimeout(() => {
        setReplayIndex(index);
        setSelectedEvent(event);
      }, index * 260);
    });
    window.setTimeout(() => setReplayIndex(null), events.length * 260 + 500);
  }

  return (
    <div className="observability-page" dir="ltr">
      <header className="observability-page-header">
        <button type="button" className="observability-back" onClick={onBack}>Back</button>
        <div>
          <span className="observability-kicker">Job Trace</span>
          <h1><code>{jobId}</code></h1>
          <p>Replay, inspect, and debug the full lifecycle from queue pickup to persisted result.</p>
        </div>
        {job && <JobStatusBadge status={job.status} />}
      </header>

      <section className="job-detail-summary">
        <div>
          <span>Trace</span>
          <code>{job?.trace_id ?? "—"}</code>
        </div>
        <div>
          <span>Events</span>
          <strong>{events.length}</strong>
        </div>
        <div>
          <span>Total latency</span>
          <strong>{formatDuration(totalDuration)}</strong>
        </div>
      </section>

      {error && <div className="observability-error">{error}</div>}
      {isLoading && !events.length ? <div className="observability-panel jobs-loading">Loading timeline...</div> : null}

      <div className="job-detail-grid">
        <EventTimeline
          events={events}
          selectedEvent={selectedEvent}
          filter={filter}
          replayIndex={replayIndex}
          onFilterChange={setFilter}
          onSelectEvent={setSelectedEvent}
          onReplay={replayExecution}
        />
        <EventDetailPanel event={selectedEvent} />
      </div>

      <TraceTimeline traceId={job?.trace_id ?? null} />
    </div>
  );
}
