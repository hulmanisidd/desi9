from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile,
)

from auth import get_current_user
from services import db_service, gemini_service, storage_service, task_queue
import asyncio

router = APIRouter(prefix="/api/v1/wardrobe", tags=["wardrobe"])

ALLOWED_TYPES = {"image/jpeg", "image/png"}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB


from services import (
    db_service, gemini_service, storage_service, task_queue, vton_service,
)


import time, logging
log = logging.getLogger("wardrobe")

async def process_wardrobe_item(user_id, item_id, data, mime_type):
    t = time.perf_counter()
    cleaned = await asyncio.to_thread(vton_service.remove_background, data)
    log.warning("rembg: %.1fs, %d KB out", time.perf_counter() - t, len(cleaned) // 1024)

    t = time.perf_counter()
    _, image_url = await asyncio.to_thread(
        storage_service.save_upload, cleaned, "image/png", "item", item_id
    )
    log.warning("storage: %.1fs", time.perf_counter() - t)

    t = time.perf_counter()
    metadata = await gemini_service.extract_clothing_metadata(cleaned, "image/png")
    log.warning("gemini: %.1fs", time.perf_counter() - t)

    db_service.add_wardrobe_item(
        user_id, {"item_id": item_id, "image_url": image_url, **metadata}
    )
    return {"result_url": image_url, "metadata": {"item_id": item_id, **metadata}}
@router.get("/items")
def get_wardrobe(user: dict = Depends(get_current_user)):
    user_id = user.get("sub", "anonymous")
    return {"items": db_service.list_wardrobe_items(user_id)}
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
    # Keep the untouched original; the cleaned PNG is saved by the background task
    item_id, _ = await asyncio.to_thread(
        storage_service.save_upload, data, file.content_type, "raw"
    )
    job_id = task_queue.enqueue(
        background_tasks, "wardrobe_upload", user,
        process_wardrobe_item, user_id, item_id, data, file.content_type,
    )
    return {
        "status": "queued",
        "job_id": job_id,
        "message": "Processing background removal and tagging...",
    }