import { NaturalInputJobRecord } from "../../api";
import { JobStatusBadge } from "./JobStatusBadge";

function formatDate(value?: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDuration(value?: number | null): string {
  if (value == null) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(2)}s`;
  return `${Math.round(value)}ms`;
}

function jobDuration(job: NaturalInputJobRecord): number | null {
  if (job.duration_ms != null) return job.duration_ms;
  const total = job.events_summary?.reduce((sum, event) => sum + (event.duration_ms ?? 0), 0) ?? 0;
  return total > 0 ? total : null;
}

export function JobTable({
  jobs,
  onOpenJob,
}: {
  jobs: NaturalInputJobRecord[];
  onOpenJob: (jobId: string) => void;
}) {
  return (
    <div className="jobs-table-wrap">
      <table className="jobs-table">
        <thead>
          <tr>
            <th>job_id</th>
            <th>Status</th>
            <th>Duration</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.job_id} onClick={() => onOpenJob(job.job_id)} tabIndex={0}>
              <td><code>{job.job_id}</code></td>
              <td><JobStatusBadge status={job.status} /></td>
              <td>{formatDuration(jobDuration(job))}</td>
              <td>{formatDate(job.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!jobs.length && <div className="jobs-empty-state">No jobs recorded yet.</div>}
    </div>
  );
}
