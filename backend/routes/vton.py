import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user
from services import db_service, storage_service, task_queue, vton_service

router = APIRouter(prefix="/api/v1/vton", tags=["vton"])

# Render order: top (or dress) first, then bottom, then layers on top
CATEGORY_ORDER = {
    "dress": 0, "top": 0, "bottom": 1, "outerwear": 2, "footwear": 3, "accessory": 4,
}


class VtonRequest(BaseModel):
    item_ids: list[str] = Field(..., min_length=1)


async def run_vton(baseline_url: str, items: list[dict]) -> dict:
    current = await asyncio.to_thread(storage_service.load_upload, baseline_url)
    steps = []
    for item in sorted(items, key=lambda i: CATEGORY_ORDER.get(i["category"], 9)):
        garment = await asyncio.to_thread(storage_service.load_upload, item["image_url"])
        # Each result becomes the baseline for the next garment
        current = await asyncio.to_thread(
            vton_service.render_garment, current, garment, item["category"]
        )
        _, url = await asyncio.to_thread(
            storage_service.save_upload, current, "image/png", "vton"
        )
        steps.append(
            {"item_id": item["item_id"], "category": item["category"], "image_url": url}
        )
    return {"result_url": steps[-1]["image_url"], "metadata": {"steps": steps}}


@router.post("/generate")
async def generate_vton(
    body: VtonRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    user_id = user.get("sub", "anonymous")
    profile = db_service.get_user(user_id)
    if not profile or not profile.get("baseline_url"):
        raise HTTPException(status_code=400, detail="Upload a baseline photo first")

    items = []
    for item_id in dict.fromkeys(body.item_ids):  # de-duplicate, keep order
        item = db_service.get_wardrobe_item(user_id, item_id)
        if item is None:  # same 404 for missing and someone else's
            raise HTTPException(status_code=404, detail=f"Item {item_id} not found")
        items.append(item)

    job_id = task_queue.enqueue(
        background_tasks, "vton_generation", user,
        run_vton, profile["baseline_url"], items,
    )
    return {
        "status": "queued",
        "job_id": job_id,
        "message": "Rendering virtual try-on...",
    }