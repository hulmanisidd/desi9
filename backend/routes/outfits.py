from fastapi import APIRouter, BackgroundTasks, Depends

from auth import get_current_user
from services import db_service, gemini_service, task_queue

router = APIRouter(prefix="/api/v1/outfits", tags=["outfits"])


def _attach_item_details(outfits: list[dict], items: list[dict]) -> list[dict]:
    by_id = {i["item_id"]: i for i in items}
    return [
        {
            **outfit,
            "items": [
                {
                    "item_id": i,
                    "image_url": by_id[i]["image_url"],
                    "category": by_id[i]["category"],
                }
                for i in outfit["item_ids"]
            ],
        }
        for outfit in outfits
    ]


async def generate_recommendations(user_id: str) -> dict:
    cached = db_service.get_cached_outfits(user_id)
    if cached is not None:
        return {"metadata": {"outfits": cached, "cached": True}}

    items = db_service.list_wardrobe_items(user_id)
    if len(items) < 2:
        raise ValueError("Add at least 2 items to your wardrobe before requesting outfits")

    version = db_service.version_of(items)
    outfits = _attach_item_details(await gemini_service.recommend_outfits(items), items)
    db_service.set_cached_outfits(user_id, outfits, version)
    return {"metadata": {"outfits": outfits, "cached": False}}


@router.post("/recommend")
async def recommend_outfits(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    job_id = task_queue.enqueue(
        background_tasks, "outfit_recommendation", user,
        generate_recommendations, user.get("sub", "anonymous"),
    )
    return {
        "status": "queued",
        "job_id": job_id,
        "message": "Generating style recommendations...",
    }