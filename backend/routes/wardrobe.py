from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile,
)

from auth import get_current_user
from services import db_service, gemini_service, storage_service, task_queue
import asyncio

router = APIRouter(prefix="/api/v1/wardrobe", tags=["wardrobe"])

ALLOWED_TYPES = {"image/jpeg", "image/png"}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB


async def process_wardrobe_item(
    user_id: str, item_id: str, image_url: str, data: bytes, mime_type: str
) -> dict:
    # TODO (2.4): run rembg here and send the cleaned image to Gemini instead
    metadata = await gemini_service.extract_clothing_metadata(data, mime_type)
    db_service.add_wardrobe_item(
        user_id, {"item_id": item_id, "image_url": image_url, **metadata}
    )
    return {"result_url": image_url, "metadata": {"item_id": item_id, **metadata}}


@router.post("/upload")
async def upload_wardrobe_item(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Only image/jpeg or image/png allowed")
    data = await file.read()  # must read now: the upload closes after the response
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    user_id = user.get("sub", "anonymous")
    item_id, image_url = await asyncio.to_thread(
        storage_service.save_upload, data, file.content_type, "item"
    )
    job_id = task_queue.enqueue(
        background_tasks, "wardrobe_upload", user,
        process_wardrobe_item, user_id, item_id, image_url, data, file.content_type,
    )
    return {
        "status": "queued",
        "job_id": job_id,
        "message": "Processing background removal and tagging...",
    }