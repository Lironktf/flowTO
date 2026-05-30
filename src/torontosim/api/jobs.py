"""Async job runner (P06).

Long sim / optimizer / copilot calls run in a thread pool so the event loop
never blocks. Clients submit a job, get an id immediately, and poll
``/jobs/{id}`` (or receive WS progress). Deterministic results are unaffected —
this is purely about not blocking the loop.
"""

from __future__ import annotations

import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field


@dataclass
class Job:
    id: str
    state: str = "pending"  # pending | running | done | error
    progress: float = 0.0
    result: object = None
    error: str | None = None
    meta: dict = field(default_factory=dict)


class JobManager:
    def __init__(self, *, max_workers: int = 4):
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._jobs: dict[str, Job] = {}

    def submit(self, fn, *args, meta=None, **kwargs) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], meta=meta or {})
        self._jobs[job.id] = job

        def _run():
            job.state = "running"
            try:
                job.result = fn(*args, **kwargs)
                job.progress = 1.0
                job.state = "done"
            except Exception as exc:  # noqa: BLE001
                job.error = f"{exc!r}\n{traceback.format_exc()}"
                job.state = "error"

        self._pool.submit(_run)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)
