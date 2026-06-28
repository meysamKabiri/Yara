from typing import Any


class FakeQueue:
    """Test double for RQ Queue that records enqueue calls.

    - Supports the full RQ-compatible keyword signature used in production:
          queue.enqueue(func, args=..., job_id=..., meta=...)
      as well as positional args for simple cases.
    - Stores every enqueue invocation in .jobs for later assertion.
    - Does NOT execute jobs synchronously (use ImmediateQueue for that).
    """

    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    def enqueue(
        self,
        func: str,
        *,
        args: tuple | None = None,
        kwargs: dict[str, Any] | None = None,
        job_id: str | None = None,
        meta: dict[str, Any] | None = None,
        **extra: Any,
    ) -> None:
        entry: dict[str, Any] = {
            "func": func,
            "args": args,
            "kwargs": kwargs,
            "job_id": job_id,
            "meta": meta,
        }
        if extra:
            entry["extra"] = extra
        self.jobs.append(entry)

    @property
    def last_job(self) -> dict[str, Any] | None:
        return self.jobs[-1] if self.jobs else None

    def assert_meta_is_valid(self, job_index: int = -1) -> None:
        """Assert that stored meta is None or a dict."""
        job = self.jobs[job_index]
        assert job["meta"] is None or isinstance(
            job["meta"], dict
        ), f"meta must be None or dict, got {type(job['meta'])}"
