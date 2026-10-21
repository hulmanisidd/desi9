from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth import get_current_user
from routes import jobs, outfits, user, vton, wardrobe

app = FastAPI(title="desI9 API", version="0.1.0")

from fastapi.staticfiles import StaticFiles
from services.storage_service import upload_dir

app.mount("/uploads", StaticFiles(directory=upload_dir()), name="uploads")

# Local dev origins: VS Code Live Server, common dev ports, and file:// ("null")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
        "null",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Every endpoint requires a valid JWT
auth_dep = [Depends(get_current_user)]
app.include_router(wardrobe.router, dependencies=auth_dep)
app.include_router(user.router, dependencies=auth_dep)
app.include_router(outfits.router, dependencies=auth_dep)
app.include_router(jobs.router, dependencies=auth_dep)
app.include_router(vton.router, dependencies=auth_dep)


@app.get("/health")
def health():
    return {"status": "ok"}