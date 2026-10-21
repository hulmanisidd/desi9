from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from services import db_service

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("/status/{job_id}")
async def get_job_status(job_id: str, user: dict = Depends(get_current_user)):
    job = db_service.get_job(job_id)
    # Same 404 for "missing" and "someone else's" so job ids can't be probed
    if job is None or job["user_id"] != user.get("sub", "anonymous"):
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "result_url": job["result_url"],
        "metadata": job["metadata"],
        "error": job["error"],
    }