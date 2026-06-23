import { useCallback } from "react";
import { JobEvent, NaturalInputJobRecord } from "../../api";
import { useJobEventStream } from "./useJobEventStream";
import { useNaturalInputJob } from "./useNaturalInputJob";

type JobEventsState = {
  job: NaturalInputJobRecord | null;
  events: JobEvent[];
  isLoading: boolean;
  error: string | null;
  connectionState: string;
};

export function useJobEvents(jobId: string): JobEventsState {
  const jobState = useNaturalInputJob(jobId);
  const refreshJob = useCallback(() => {
    void jobState.refresh();
  }, [jobState.refresh]);
  const stream = useJobEventStream(jobId, refreshJob, jobState.status);

  return {
    job: jobState.job,
    events: stream.events,
    isLoading: jobState.isLoading && !stream.events.length,
    error: jobState.error ?? stream.error,
    connectionState: stream.connectionState,
  };
}
