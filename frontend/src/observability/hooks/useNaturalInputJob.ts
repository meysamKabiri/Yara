import { useCallback, useEffect, useState } from "react";
import { api, JobState, NaturalInputJobRecord, PendingInterpretation } from "../../api";

type NaturalInputJobState = {
  job: NaturalInputJobRecord | null;
  status: NaturalInputJobRecord["status"] | null;
  state: JobState;
  result: NaturalInputJobRecord["result"];
  interpretations: PendingInterpretation[];
  traceId: string | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<NaturalInputJobRecord | null>;
};

export function toJobState(status?: NaturalInputJobRecord["status"] | null, hasJob = false): JobState {
  if (!hasJob || !status) return "IDLE";
  if (status === "PENDING") return "SUBMITTED";
  if (status === "RUNNING") return "PROCESSING";
  if (status === "DONE") return "DONE";
  return "FAILED";
}

function interpretationsFromResult(result: NaturalInputJobRecord["result"]): PendingInterpretation[] {
  if (!result || typeof result !== "object") return [];
  const interpretations = result.interpretations;
  return Array.isArray(interpretations) ? interpretations as PendingInterpretation[] : [];
}

function isTerminalStatus(status?: NaturalInputJobRecord["status"] | null): boolean {
  return status === "DONE" || status === "FAILED";
}

export function useNaturalInputJob(jobId: string | null): NaturalInputJobState {
  const [job, setJob] = useState<NaturalInputJobRecord | null>(null);
  const [isLoading, setIsLoading] = useState(Boolean(jobId));
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (): Promise<NaturalInputJobRecord | null> => {
    if (!jobId) {
      setJob(null);
      setIsLoading(false);
      return null;
    }
    setIsLoading(true);
    try {
      const nextJob = await api.getNaturalInputJob(jobId);
      setJob(nextJob);
      setError(null);
      return nextJob;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load natural input job");
      return null;
    } finally {
      setIsLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    let cancelled = false;
    let pollTimer: number | null = null;
    if (!jobId) {
      setJob(null);
      setIsLoading(false);
      setError(null);
      return;
    }
    const activeJobId = jobId;

    async function poll() {
      setIsLoading(true);
      try {
        const nextJob = await api.getNaturalInputJob(activeJobId);
        if (cancelled) return;
        setJob(nextJob);
        setError(null);
        if (!isTerminalStatus(nextJob.status)) {
          pollTimer = window.setTimeout(poll, 1200);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load natural input job");
          pollTimer = window.setTimeout(poll, 2000);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void poll();

    return () => {
      cancelled = true;
      if (pollTimer !== null) window.clearTimeout(pollTimer);
    };
  }, [jobId]);

  return {
    job,
    status: job?.status ?? null,
    state: toJobState(job?.status, Boolean(jobId)),
    result: job?.result ?? null,
    interpretations: interpretationsFromResult(job?.result ?? null),
    traceId: job?.trace_id ?? null,
    isLoading,
    error,
    refresh,
  };
}
