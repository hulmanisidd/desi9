import asyncio
import os

from services import db_service


async def run_job(job_id: str, fn, *args) -> None:
    """Run fn in the background and record queued -> processing -> completed/failed.

    fn may be async or a normal blocking function (rembg, diffusion, etc. run in
    a worker thread so they never block the event loop). It should return a dict
    like {"result_url": "...", "metadata": {...}}.
    """
    db_service.update_job(job_id, status="processing")
    try:
        if asyncio.iscoroutinefunction(fn):
            result = await fn(*args)
        else:
            result = await asyncio.to_thread(fn, *args)
    except Exception as exc:
        db_service.update_job(job_id, status="failed", error=str(exc))
        return

    result = result or {}
    db_service.update_job(
        job_id,
        status="completed",
        result_url=result.get("result_url"),
        metadata=result.get("metadata"),
    )


async def placeholder_task(job_type: str) -> dict:
    """Stand-in for real work until Modules 2.3/2.4 replace it."""
    await asyncio.sleep(float(os.getenv("STUB_TASK_DELAY", "2")))
    return {
        "result_url": f"https://example.com/placeholder_{job_type}.png",
        "metadata": {"category": "top", "color": "navy"},
    }


def enqueue(background_tasks, job_type: str, user: dict, fn=None, *args) -> str:
    """Create a job row, schedule the work, and return the job_id."""
    job_id = db_service.create_job(job_type, user.get("sub", "anonymous"))
    if fn is None:
        fn, args = placeholder_task, (job_type,)
    background_tasks.add_task(run_job, job_id, fn, *args)
    return job_id