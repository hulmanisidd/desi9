import asyncio

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile,
)

from auth import get_current_user
from services import db_service, storage_service, task_queue, vton_service

router = APIRouter(prefix="/api/v1/user", tags=["user"])

ALLOWED_TYPES = {"image/jpeg", "image/png"}
MAX_BYTES = 10 * 1024 * 1024


async def process_baseline(user_id: str, baseline_url: str, data: bytes) -> dict:
    pose_maps = await asyncio.to_thread(vton_service.extract_pose_maps, data)
    db_service.set_baseline(user_id, baseline_url, pose_maps)
    return {
        "result_url": baseline_url,
        "metadata": {"pose_provider": pose_maps.get("provider")},
    }


@router.post("/upload-baseline")
async def upload_baseline(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Only image/jpeg or image/png allowed")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    user_id = user.get("sub", "anonymous")
    _, baseline_url = await asyncio.to_thread(
        storage_service.save_upload, data, file.content_type, "baseline"
    )
    job_id = task_queue.enqueue(
        background_tasks, "baseline_upload", user,
        process_baseline, user_id, baseline_url, data,
    )
    return {
        "status": "queued",
        "job_id": job_id,
        "message": "Processing pose estimation maps...",
    }