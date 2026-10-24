"""desI9 GPU server: runs OOTDiffusion on Colab and exposes POST /tryon.

Runs inside the Python 3.10 venv (/content/venv310). See README section 4.
"""
import hmac
import io
import logging
import os
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path("/content/OOTDiffusion")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "run"))  # utils_ootd lives here
os.chdir(PROJECT_ROOT / "run")  # the repo loads ../checkpoints/... relative to the cwd

import torch
import uvicorn
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps

from utils_ootd import get_mask_location
from preprocess.openpose.run_openpose import OpenPose
from preprocess.humanparsing.run_parsing import Parsing
from ootd.inference_ootd_dc import OOTDiffusionDC

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tryon")

API_KEY = os.getenv("VTON_REMOTE_KEY", "")
if not API_KEY:
    raise RuntimeError("VTON_REMOTE_KEY is not set")

GPU_ID = 0
NUM_STEPS = int(os.getenv("OOTD_STEPS", "20"))
IMAGE_SCALE = float(os.getenv("OOTD_SCALE", "2.0"))

# Same mappings as run_ootd.py
CATEGORY_NAMES = ["upperbody", "lowerbody", "dress"]
CATEGORY_UTILS = ["upper_body", "lower_body", "dresses"]

log.info("Loading models...")
openpose_model = OpenPose(GPU_ID)
parsing_model = Parsing(GPU_ID)
model = OOTDiffusionDC(GPU_ID)
log.info("Models loaded.")

gpu_lock = threading.Lock()
app = FastAPI()


def to_rgb(data: bytes) -> Image.Image:
    """Decode and flatten any transparency onto white (RGBA cutouts would turn black)."""
    im = Image.open(io.BytesIO(data))
    im.load()
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        return bg
    return im.convert("RGB")


def run_tryon(baseline: Image.Image, garment: Image.Image, idx: int) -> Image.Image:
    cloth_img = garment.resize((768, 1024))
    model_img = baseline.resize((768, 1024))
    keypoints = openpose_model(model_img.resize((384, 512)))
    model_parse, _ = parsing_model(model_img.resize((384, 512)))

    mask, mask_gray = get_mask_location("dc", CATEGORY_UTILS[idx], model_parse, keypoints)
    mask = mask.resize((768, 1024), Image.NEAREST)
    mask_gray = mask_gray.resize((768, 1024), Image.NEAREST)
    masked_vton_img = Image.composite(mask_gray, model_img, mask)

    with torch.no_grad():
        images = model(
            model_type="dc",
            category=CATEGORY_NAMES[idx],
            image_garm=cloth_img,
            image_vton=masked_vton_img,
            mask=mask,
            image_ori=model_img,
            num_samples=1,
            num_steps=NUM_STEPS,
            image_scale=IMAGE_SCALE,
            seed=-1,
        )
    return images[0]


@app.get("/health")
def health():
    return {"status": "ok", "cuda": torch.cuda.is_available()}


@app.post("/tryon")
def tryon(
    baseline: UploadFile = File(...),
    garment: UploadFile = File(...),
    category: str = Form(...),
    x_api_key: str | None = Header(default=None),
):
    if not x_api_key or not hmac.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="invalid api key")

    category = category.strip().lower()
    if category not in CATEGORY_NAMES:
        raise HTTPException(status_code=400, detail="category must be upperbody, lowerbody or dress")
    idx = CATEGORY_NAMES.index(category)

    try:
        baseline_img = to_rgb(baseline.file.read())
        garment_img = to_rgb(garment.file.read())
    except Exception:
        raise HTTPException(status_code=400, detail="could not read image")

    try:
        with gpu_lock:
            result = run_tryon(baseline_img, garment_img, idx)
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        log.exception("CUDA out of memory")
        raise HTTPException(status_code=500, detail="gpu out of memory")
    except Exception as exc:
        log.exception("render failed")
        raise HTTPException(status_code=500, detail=f"render failed: {type(exc).__name__}")

    buf = io.BytesIO()
    result.convert("RGB").save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
