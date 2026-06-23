import { JobEvent, JobState } from "../../api";
import { EventItem } from "./EventItem";

const MILESTONES = ["JOB_STARTED", "DOMAIN_ROUTER_START", "LLM_STARTED", "LLM_COMPLETED", "JOB_COMPLETED"];

function progressFor(events: JobEvent[], state: JobState): number {
  if (state === "DONE") return 100;
  if (state === "FAILED") return Math.max(8, Math.round((completedMilestones(events) / MILESTONES.length) * 100));
  if (!events.length) return state === "SUBMITTED" ? 8 : 0;
  return Math.min(95, Math.max(12, Math.round((completedMilestones(events) / MILESTONES.length) * 100)));
}

function completedMilestones(events: JobEvent[]): number {
  const names = new Set(events.map((event) => event.event));
  return MILESTONES.filter((name) => names.has(name)).length;
}

function stepStatus(step: string, events: JobEvent[], state: JobState): "done" | "active" | "pending" | "failed" {
  if (state === "FAILED" && step === MILESTONES[Math.min(completedMilestones(events), MILESTONES.length - 1)]) return "failed";
  const names = events.map((event) => event.event);
  if (names.includes(step)) return "done";
  const firstPendingIndex = MILESTONES.findIndex((name) => !names.includes(name));
  return MILESTONES[firstPendingIndex] === step ? "active" : "pending";
}

function stepLabel(step: string): string {
  if (step === "JOB_STARTED") return "Queue worker started";
  if (step === "DOMAIN_ROUTER_START") return "Domain routing";
  if (step === "LLM_STARTED") return "LLM processing";
  if (step === "LLM_COMPLETED") return "Interpretation prepared";
  if (step === "JOB_COMPLETED") return "Job completed";
  return step;
}

export function JobProgressPanel({
  state,
  events,
  connectionState,
}: {
  state: JobState;
  events: JobEvent[];
  connectionState?: string;
}) {
  const progress = progressFor(events, state);
  const latestEvent = events[events.length - 1] ?? null;

  return (
    <section className="job-progress-panel">
      <div className="job-progress-header">
        <div>
          <span className="eyebrow">Job progress</span>
          <h3>{state === "FAILED" ? "Processing failed" : state === "DONE" ? "Ready for confirmation" : "Processing your request..."}</h3>
        </div>
        <strong>{progress}%</strong>
      </div>
      <div className="job-progress-track" aria-label={`Job progress ${progress}%`}>
        <span style={{ width: `${progress}%` }} />
      </div>
      <div className="job-progress-connection">Live stream: {connectionState ?? "IDLE"}</div>
      <div className="job-step-list">
        {MILESTONES.map((step) => {
          const status = stepStatus(step, events, state);
          return (
            <div className={`job-step ${status}`} key={step}>
              <span>{status === "done" ? "✓" : status === "failed" ? "!" : status === "active" ? "⟳" : "○"}</span>
              <span>{stepLabel(step)}</span>
            </div>
          );
        })}
      </div>
      <div className="job-progress-events">
        {events.slice(-5).map((event) => (
          <EventItem
            key={`${event.sequence_number}-${event.event}-${event.created_at}`}
            event={event}
            isSelected={false}
            isLatest={latestEvent === event}
            isReplayActive={false}
            onSelect={() => undefined}
          />
        ))}
        {!events.length && <div className="jobs-empty-state">Waiting for the first live event...</div>}
      </div>
    </section>
  );
}
