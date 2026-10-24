# desI9: AI Virtual Wardrobe and Virtual Try-On (Web MVP)

Upload photos of your clothes, upload a full-body photo of yourself, get AI outfit recommendations, and see them rendered on you.

- **Frontend:** vanilla HTML/CSS/JS (`frontend/`)
- **Backend:** Python FastAPI (`backend/`)
- **Tagging and recommendations:** Google Gemini API
- **Storage and database:** Supabase (Storage + Postgres), with an in-memory fallback for local dev and tests
- **Try-on renderer:** OOTDiffusion on a free Colab T4 GPU, reached through an ngrok tunnel (or a built-in mock renderer for everyday development)

```
desi9/
  frontend/          index.html, css/style.css, js/api.js, js/ui.js
  backend/           main.py, auth.py, routes/, services/, tests/
  colab/server.py    GPU server for real try-on renders (runs on Colab)
```

## How it works

1. `POST /api/v1/wardrobe/upload` queues a job: background removal (rembg), then Gemini tagging.
2. `POST /api/v1/user/upload-baseline` stores your full-body photo.
3. `POST /api/v1/outfits/recommend` queues Gemini outfit pairings (cached until the wardrobe changes).
4. `POST /api/v1/vton/generate` with `{"item_ids": [...]}` renders garments one at a time; each result becomes the next baseline.
5. `GET /api/v1/jobs/status/{job_id}` is the polling endpoint for all of the above.
6. `GET /api/v1/wardrobe/items` lists the user's wardrobe.

All endpoints need `Authorization: Bearer <JWT>`. JSON keys are `snake_case`.

---

## 1. Prerequisites

- Python 3.11
- Git
- A Gemini API key (https://aistudio.google.com)
- A Supabase project (optional for local dev, required for persistent storage)
- For real try-on renders only: a Google account (Colab) and a free ngrok account

## 2. Backend setup

From the repo root (Windows PowerShell shown; use `source venv/bin/activate` on macOS/Linux):

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
cd backend
pip install -r requirements.txt
copy .env.example .env
```

Edit `backend/.env` (never commit this file). Variables:

| Variable | Purpose |
|---|---|
| `JWT_SECRET` | Secret used to verify HS256 JWTs |
| `GEMINI_API_KEY` | Gemini API key (check the exact name in `.env.example` / `gemini_service.py`) |
| `GEMINI_MODEL` | Gemini model name, if configurable (model names change often) |
| `DATABASE_URL` | Supabase Postgres connection string. Must end in `/postgres`. If unset, the in-memory fallback is used |
| `SUPABASE_URL` | Supabase project URL |
| Supabase service key | Key used for Storage uploads (exact name: see `.env.example`) |
| `VTON_PROVIDER` | `mock` (default for dev) or `remote` (real renders on Colab) |
| `VTON_REMOTE_URL` | ngrok URL of the Colab server (remote only) |
| `VTON_REMOTE_KEY` | Shared API key between backend and Colab server (remote only) |
| `VTON_REMOTE_TIMEOUT` | Seconds to wait for one render (use 600) |

Notes:

- `load_dotenv()` does not override variables already set in your terminal. If a setting seems ignored, run `Get-ChildItem Env: | Where-Object Name -like "VTON*"` and `Remove-Item Env:<NAME>`.
- Without `DATABASE_URL`, data lives in memory and is lost on restart. Tests always use this fallback.

### Supabase setup (skip for in-memory dev)

1. Create a project and copy the Postgres connection string into `DATABASE_URL`.
2. In **Storage**, create a bucket named `desi9-images` and mark it **Public**. (A private bucket makes image URLs return "Bucket not found".)
3. Create the tables. The reference schema below was reconstructed from `services/db_service.py`; if you have a SQL file in the repo, use that instead.

```sql
create table if not exists jobs (
  job_id text primary key, job_type text, user_id text,
  status text not null default 'queued', result_url text,
  metadata jsonb, error text,
  created_at timestamptz default now(), updated_at timestamptz default now()
);
create table if not exists wardrobe_items (
  item_id text primary key, user_id text not null, image_url text not null,
  category text, sub_category text, color text, fabric text,
  created_at timestamptz default now()
);
create table if not exists users (
  user_id text primary key, baseline_url text, pose_maps jsonb,
  updated_at timestamptz default now()
);
create table if not exists outfit_cache (
  user_id text primary key, version text, outfits jsonb,
  updated_at timestamptz default now()
);
```

### Run the backend

```powershell
cd backend
uvicorn main:app --port 8000
```

Do **not** use `--reload` when testing uploads or renders: saving a file restarts the server and kills running background jobs.

Interactive docs: http://localhost:8000/docs

### Run the tests

```powershell
cd backend
pytest -q
```

### Create a dev JWT

The backend verifies HS256 tokens signed with `JWT_SECRET`. To mint a 30-day dev token:

```powershell
cd backend
python -c "import os,time,jwt; from dotenv import load_dotenv; load_dotenv(); print(jwt.encode({'sub': 'dev-user', 'iat': int(time.time()), 'exp': int(time.time())+30*86400}, os.environ['JWT_SECRET'], algorithm='HS256'))"
```

In Swagger's **Authorize** box, paste the raw token only (no `Bearer`).

## 3. Frontend setup

1. Confirm `frontend/js/api.js` has `const USE_MOCK = false;` and `BASE_URL = "http://localhost:8000/api/v1"`.
2. Serve the frontend over HTTP (opening `index.html` as a file breaks CORS):

```powershell
cd frontend
python -m http.server 5500
```

3. Open http://localhost:5500, open the browser console (F12), and store your token:

```js
localStorage.setItem('jwtToken', '<your token>'); location.reload();
```

4. Walk through the flow: upload a baseline photo, upload a few clothes, click recommend, select an outfit, generate.

The backend CORS settings must allow `http://localhost:5500`.

Tip: use photos of garments laid flat or worn, without hangers. Large camera photos are slower to process.

## 4. Real try-on renders (Colab GPU)

The mock renderer pastes garment cutouts onto your photo. For real draping you need OOTDiffusion, which needs a GPU. Free Colab sessions idle out and wipe `/content`, so you repeat this setup each time.

### One-time: Colab secrets

In Colab (key icon in the left sidebar), add two secrets and enable notebook access for each:

- `VTON_REMOTE_KEY`: a random key. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"` and put the same value in `backend/.env`.
- `NGROK_TOKEN`: your authtoken from https://dashboard.ngrok.com/get-started/your-authtoken

### Each session

1. Set the runtime to **T4 GPU**. The notebook's Python is 3.13, but OOTDiffusion needs Python 3.10, so everything runs in a uv venv.
2. Install and clone:

```python
!pip install -q uv pyngrok huggingface_hub
!git clone https://github.com/levihsu/OOTDiffusion /content/OOTDiffusion
!uv venv --python 3.10 /content/venv310
!uv pip install --python /content/venv310/bin/python torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2
%cd /content/OOTDiffusion
!uv pip install --python /content/venv310/bin/python -r requirements.txt
!uv pip install --python /content/venv310/bin/python fastapi uvicorn python-multipart huggingface_hub==0.25.2 setuptools wheel
!uv pip install --python /content/venv310/bin/python --no-build-isolation basicsr
```

The repo's requirements list is incomplete. If a later step reports a missing module, install it with the same `uv pip install --python ...` pattern.

3. Download the weights (several GB):

```python
from huggingface_hub import snapshot_download
snapshot_download(repo_id="levihsu/OOTDiffusion", local_dir="/content/ootd_hf", allow_patterns=["checkpoints/*"])
snapshot_download(repo_id="openai/clip-vit-large-patch14",
                  local_dir="/content/OOTDiffusion/checkpoints/clip-vit-large-patch14",
                  allow_patterns=["*.json", "*.txt", "model.safetensors"])
```

```
!mkdir -p /content/OOTDiffusion/checkpoints
!cp -rn /content/ootd_hf/checkpoints/. /content/OOTDiffusion/checkpoints/
```

`/content/OOTDiffusion/checkpoints` should now contain `ootd`, `humanparsing`, `openpose` and `clip-vit-large-patch14`.

4. Upload `colab/server.py` from this repo to `/content/server.py` (Files panel), or paste it with `%%writefile /content/server.py`.

5. Launch the server:

```python
import os, subprocess, time, requests
from google.colab import userdata

!pkill -f /content/server.py
env = os.environ.copy()
env["VTON_REMOTE_KEY"] = userdata.get("VTON_REMOTE_KEY")
logf = open("/content/server.log", "w")
proc = subprocess.Popen(["/content/venv310/bin/python", "/content/server.py"],
                        env=env, cwd="/content/OOTDiffusion/run",
                        stdout=logf, stderr=subprocess.STDOUT)
for _ in range(150):
    if proc.poll() is not None:
        print("server exited early:"); print(open("/content/server.log").read()[-3000:]); break
    try:
        if requests.get("http://127.0.0.1:8000/health", timeout=2).ok:
            print("server is up"); break
    except Exception:
        pass
    time.sleep(2)
```

6. Open the tunnel (if `set_auth_token` says the token is already set, skip that call):

```python
from pyngrok import ngrok
ngrok.kill()
tunnel = ngrok.connect("http://127.0.0.1:8000")
print(tunnel.public_url)
```

7. Set these in `backend/.env`, then restart uvicorn (no `--reload`):

```
VTON_PROVIDER=remote
VTON_REMOTE_URL=<the ngrok URL>
VTON_REMOTE_KEY=<same key as the Colab secret>
VTON_REMOTE_TIMEOUT=600
```

8. Verify the GPU server directly:

```powershell
curl.exe "<ngrok-url>/health" -H "ngrok-skip-browser-warning: true"
```

Expect `{"status":"ok","cuda":true}`. A real render takes about 1 minute per garment. To confirm a render was real, run `!tail -n 20 /content/server.log` in Colab and look for a `POST /tryon` line and sampling progress bars. A job that finishes in seconds was the mock.

When you are done with real renders, set `VTON_PROVIDER=mock` again.

## 5. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Images show "Bucket not found" | The Supabase bucket doesn't exist or isn't public |
| `Invalid or expired token` | Token expired, or `JWT_SECRET` differs from the one that signed it |
| Uploads stuck on "Processing" | Check the uvicorn terminal. Causes: Gemini errors or a stale model name, slow rembg on large photos, or `--reload` killed the job |
| Try-on looks like a flat overlay | `VTON_PROVIDER` is `mock`, or a terminal variable overrides `.env` |
| Try-on job fails with "Server disconnected" or 502 | Colab session or tunnel is down. Rebuild and update `VTON_REMOTE_URL` |
| Colab 401 | `VTON_REMOTE_KEY` differs between the Colab secret and `backend/.env` |
| `curl` reports a 200 for a failing call | Don't use `-w "%{http_code}"`. Use `-D -` and `-H "Expect:"` |

## 6. Security

- Never commit `backend/.env`, API keys, the JWT secret, or ngrok tokens.
- Rotate `VTON_REMOTE_KEY` if it is ever shared in a chat or log.
- Uploaded files are renamed with generated UUIDs.
