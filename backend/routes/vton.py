from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from auth import get_current_user
from services import task_queue

router = APIRouter(prefix="/api/v1/vton", tags=["vton"])


class VtonRequest(BaseModel):
    item_ids: list[str] = Field(..., min_length=1)


@router.post("/generate")
async def generate_vton(
    body: VtonRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    # TODO (2.4): sequential OOTDiffusion rendering using body.item_ids
    job_id = task_queue.enqueue(background_tasks, "vton_generation", user)
    return {
        "status": "queued",
        "job_id": job_id,
        "message": "Rendering virtual try-on...",
    }