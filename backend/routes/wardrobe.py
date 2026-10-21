from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile

from auth import get_current_user
from services import task_queue

router = APIRouter(prefix="/api/v1/wardrobe", tags=["wardrobe"])


@router.post("/upload")
async def upload_wardrobe_item(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    # TODO (2.3/2.4): save to storage, then pass real work (rembg + Gemini tagging) as fn
    job_id = task_queue.enqueue(background_tasks, "wardrobe_upload", user)
    return {
        "status": "queued",
        "job_id": job_id,
        "message": "Processing background removal and tagging...",
    }