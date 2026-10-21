from fastapi import APIRouter, BackgroundTasks, Depends

from auth import get_current_user
from services import task_queue

router = APIRouter(prefix="/api/v1/outfits", tags=["outfits"])


@router.post("/recommend")
async def recommend_outfits(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    # TODO (2.3): check cache, then run Gemini recommendation via call_with_backoff
    job_id = task_queue.enqueue(background_tasks, "outfit_recommendation", user)
    return {
        "status": "queued",
        "job_id": job_id,
        "message": "Generating style recommendations...",
    }