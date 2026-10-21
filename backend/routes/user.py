from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile

from auth import get_current_user
from services import task_queue

router = APIRouter(prefix="/api/v1/user", tags=["user"])


@router.post("/upload-baseline")
async def upload_baseline(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    # TODO (2.4): save image, run pose extraction
    job_id = task_queue.enqueue(background_tasks, "baseline_upload", user)
    return {
        "status": "queued",
        "job_id": job_id,
        "message": "Processing pose estimation maps...",
    }