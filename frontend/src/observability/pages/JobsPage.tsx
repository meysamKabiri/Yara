import { JobTable } from "../components/JobTable";
import { useJobs } from "../hooks/useJobs";

export function JobsPage({ onOpenJob }: { onOpenJob: (jobId: string) => void }) {
  const { jobs, isLoading, error } = useJobs();

  return (
    <div className="observability-page" dir="ltr">
      <header className="observability-page-header">
        <div>
          <span className="observability-kicker">Observability</span>
          <h1>Jobs</h1>
          <p>Monitor natural input jobs, status transitions, and trace-linked execution output.</p>
        </div>
      </header>
      {error && <div className="observability-error">{error}</div>}
      {isLoading && !jobs.length ? (
        <div className="observability-panel jobs-loading">Loading jobs...</div>
      ) : (
        <JobTable jobs={jobs} onOpenJob={onOpenJob} />
      )}
    </div>
  );
}
