import { JobStatus } from "../../api";

const labels: Record<JobStatus, string> = {
  PENDING: "PENDING",
  RUNNING: "RUNNING",
  DONE: "DONE",
  FAILED: "FAILED",
};

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return <span className={`job-status-badge ${status.toLowerCase()}`}>{labels[status]}</span>;
}
