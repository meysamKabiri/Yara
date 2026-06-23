import { useEffect, useState } from "react";
import { api, NaturalInputJobRecord } from "../../api";

type JobsState = {
  jobs: NaturalInputJobRecord[];
  isLoading: boolean;
  error: string | null;
};

export function useJobs(): JobsState {
  const [jobs, setJobs] = useState<NaturalInputJobRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadJobs() {
      try {
        const nextJobs = await api.listJobs();
        if (cancelled) return;
        setJobs(nextJobs);
        setError(null);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load jobs");
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    loadJobs();

    return () => {
      cancelled = true;
    };
  }, []);

  return { jobs, isLoading, error };
}
