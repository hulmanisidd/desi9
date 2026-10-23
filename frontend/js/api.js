/**
 * api.js - Module 1.2: API abstraction layer.
 *
 * Rules:
 *  - This file contains fetch logic ONLY. No DOM access (that lives in ui.js).
 *  - JS names are camelCase; JSON keys sent/received are snake_case (job_id, item_ids, result_url).
 *  - The JWT is read from localStorage and never hardcoded here.
 *
 * Set USE_MOCK to false once the backend is running.
 *
 * Job status shape (every response, per Dev 2):
 *   { job_id, status, result_url, metadata, error }
 *   status is one of: queued | processing | completed | failed
 *   A failed job is still HTTP 200 - check `status` and show `error`.
 */

const USE_MOCK = true;
const MOCK_FORCE_FAIL = false; // set true in mock mode to test the "failed job" UI
const BASE_URL = "http://localhost:8000/api/v1";
const TOKEN_KEY = "jwtToken";
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024; // backend rejects files over 10 MB (413)

/* ---------- Auth helpers ---------- */

function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch (err) {
    return null;
  }
}

function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

/* ---------- Client-side file check (saves a round trip) ---------- */

/** Returns an error message string, or null if the file looks fine. */
function validateImageFile(file) {
  if (!file) return "Please choose an image first.";
  if (file.size === 0) return "That file is empty.";
  if (file.type !== "image/jpeg" && file.type !== "image/png") {
    return "Only JPEG or PNG images are allowed.";
  }
  if (file.size > MAX_UPLOAD_BYTES) return "File is too large (max 10 MB).";
  return null;
}

/* ---------- Low-level request helper ---------- */

const DEFAULT_ERROR_MESSAGES = {
  400: "The request could not be processed.",
  401: "Your session is missing, invalid or expired. Please sign in again.",
  404: "That item could not be found.",
  413: "File is too large (max 10 MB).",
  415: "Only JPEG or PNG images are allowed.",
  422: "The request was invalid.",
};

/**
 * Sends a request with the Authorization header.
 * Pass `body` as FormData (multipart) or a plain object (sent as JSON).
 * Throws an Error with `.status` set (0 = network failure) on any non-2xx response.
 *
 * Error statuses to expect (from Dev 2):
 *   401 bad/expired token | 404 unknown job or item | 415 not JPEG/PNG
 *   400 empty file, or VTON before a baseline photo exists | 413 file over 10 MB
 *   422 bad request body (e.g. missing item_ids)
 */
async function apiRequest(path, { method = "GET", body = null } = {}) {
  const headers = {};
  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const options = { method, headers };

  if (body instanceof FormData) {
    // Do NOT set Content-Type: the browser adds the multipart boundary itself.
    options.body = body;
  } else if (body !== null) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(`${BASE_URL}${path}`, options);
  } catch (networkErr) {
    const err = new Error("Cannot reach the server. Is the backend running?");
    err.status = 0;
    throw err;
  }

  if (!response.ok) {
    let serverMessage = "";
    try {
      const data = await response.json();
      // FastAPI sends a string for most errors, but an array of objects for 422.
      if (typeof data.detail === "string") serverMessage = data.detail;
      else if (typeof data.message === "string") serverMessage = data.message;
    } catch (parseErr) {
      // response had no JSON body
    }
    const message =
      serverMessage || DEFAULT_ERROR_MESSAGES[response.status] || `Request failed (${response.status})`;
    const err = new Error(message);
    err.status = response.status;
    throw err;
  }

  return response.json();
}

/* ---------- Mock support ---------- */

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Small inline SVG so mock images work offline (no network, no extra files).
function mockImage(label, color) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400">` +
    `<rect width="100%" height="100%" fill="${color}"/>` +
    `<text x="50%" y="50%" fill="#fff" font-family="sans-serif" font-size="22" ` +
    `text-anchor="middle">${label}</text></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

const MOCK_POLLS_BEFORE_DONE = 2;
let mockJobCounter = 0;
let mockItemCounter = 0;
let mockBaselineReady = false;
const mockJobs = {}; // job_id -> { type, polls, payload }

// Seeded so recommendations and try-on can be tested without uploading anything first.
const mockWardrobe = [
  { item_id: "uuid-seed-top", image_url: mockImage("Grey hoodie", "#6b6b6b"), category: "top", sub_category: "hoodie", color: "grey", fabric: "cotton" },
  { item_id: "uuid-seed-bottom", image_url: mockImage("Blue jeans", "#1f3a5f"), category: "bottom", sub_category: "jeans", color: "blue", fabric: "denim" },
];

function createMockJob(type, payload = {}) {
  mockJobCounter += 1;
  const jobId = `job-mock-${mockJobCounter}`;
  mockJobs[jobId] = { type, polls: 0, payload };
  return jobId;
}

function mockStatusBody(jobId, status, extra = {}) {
  return { job_id: jobId, status, result_url: null, metadata: null, error: null, ...extra };
}

function buildMockCompleted(jobId, job) {
  switch (job.type) {
    case "wardrobe": {
      mockItemCounter += 1;
      const isTop = mockItemCounter % 2 === 1;
      const item = {
        item_id: `uuid-mock-${mockItemCounter}`,
        image_url: mockImage(isTop ? "New top" : "New bottom", isTop ? "#7a3b2e" : "#2e5e4e"),
        category: isTop ? "top" : "bottom",
        sub_category: isTop ? "t-shirt" : "trousers",
        color: isTop ? "maroon" : "green",
        fabric: "cotton",
      };
      mockWardrobe.push(item);
      return mockStatusBody(jobId, "completed", {
        result_url: item.image_url,
        metadata: {
          item_id: item.item_id,
          category: item.category,
          sub_category: item.sub_category,
          color: item.color,
          fabric: item.fabric,
        },
      });
    }
    case "baseline":
      mockBaselineReady = true;
      return mockStatusBody(jobId, "completed", { result_url: mockImage("Your photo", "#555555"), metadata: {} });
    case "recommendations": {
      const tops = mockWardrobe.filter((i) => i.category === "top");
      const bottoms = mockWardrobe.filter((i) => i.category === "bottom");
      const outfits = [];
      tops.slice(0, 2).forEach((top, idx) => {
        const bottom = bottoms[idx % Math.max(bottoms.length, 1)];
        if (!bottom) return;
        outfits.push({
          name: idx === 0 ? "Casual Friday" : "Smart casual",
          occasion: idx === 0 ? "casual" : "smart_casual",
          reasoning: "Colours and fabrics pair well together.",
          item_ids: [top.item_id, bottom.item_id],
          items: [top, bottom].map((i) => ({ item_id: i.item_id, image_url: i.image_url, category: i.category })),
        });
      });
      return mockStatusBody(jobId, "completed", { metadata: { cached: false, outfits } });
    }
    case "vton": {
      const steps = (job.payload.itemIds || []).map((id) => {
        const item = mockWardrobe.find((i) => i.item_id === id);
        return {
          item_id: id,
          category: item ? item.category : "top",
          image_url: mockImage(`Step: ${id}`, "#7a3b2e"),
        };
      });
      return mockStatusBody(jobId, "completed", {
        result_url: mockImage("Try-on result", "#7a3b2e"),
        metadata: { steps },
      });
    }
    default:
      return mockStatusBody(jobId, "failed", { error: "Unknown mock job" });
  }
}

function mockError(status, message) {
  const err = new Error(message);
  err.status = status;
  return err;
}

/* ---------- API 1: Wardrobe ingestion ---------- */

async function uploadWardrobeItem(file) {
  if (USE_MOCK) {
    await delay(500);
    const jobId = createMockJob("wardrobe");
    return { status: "queued", job_id: jobId, message: "Processing background removal and tagging..." };
  }
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest("/wardrobe/upload", { method: "POST", body: formData });
}

/* ---------- Wardrobe list (PROPOSED by Dev 2: GET /wardrobe/items, not in the contract yet) ---------- */

/**
 * Returns { items: [{ item_id, image_url, category, sub_category, color, fabric }] } in upload order.
 * If the backend answers 404 (endpoint not built yet), ui.js should fall back to the
 * item_id/result_url pairs it saved in localStorage from completed wardrobe jobs.
 */
async function listWardrobeItems() {
  if (USE_MOCK) {
    await delay(300);
    return { items: mockWardrobe.map((i) => ({ ...i })) };
  }
  return apiRequest("/wardrobe/items");
}

/* ---------- API 2: Baseline photo ingestion ---------- */

async function uploadBaselinePhoto(file) {
  if (USE_MOCK) {
    await delay(500);
    const jobId = createMockJob("baseline");
    return { status: "queued", job_id: jobId, message: "Processing pose estimation maps..." };
  }
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest("/user/upload-baseline", { method: "POST", body: formData });
}

/* ---------- API 3: Outfit recommendations ---------- */

async function requestOutfitRecommendations() {
  if (USE_MOCK) {
    await delay(500);
    const jobId = createMockJob("recommendations");
    return { status: "queued", job_id: jobId, message: "Generating style recommendations..." };
  }
  return apiRequest("/outfits/recommend", { method: "POST" });
}

/* ---------- API 4: Job status (single check; the polling loop is Module 1.3) ---------- */

async function getJobStatus(jobId) {
  if (USE_MOCK) {
    await delay(300);
    const job = mockJobs[jobId];
    if (!job) throw mockError(404, "Job not found.");
    // A finished job always returns the same result (and never re-adds wardrobe items).
    if (job.result) return job.result;
    job.polls += 1;
    if (job.polls <= MOCK_POLLS_BEFORE_DONE) {
      return mockStatusBody(jobId, job.polls === 1 ? "queued" : "processing");
    }
    job.result = MOCK_FORCE_FAIL
      ? mockStatusBody(jobId, "failed", { error: "Mock failure: something went wrong." })
      : buildMockCompleted(jobId, job);
    return job.result;
  }
  return apiRequest(`/jobs/status/${encodeURIComponent(jobId)}`);
}

/* ---------- API 5: VTON generation ---------- */

/**
 * Order matters: upload the baseline photo and wait for it to complete BEFORE calling this,
 * otherwise the backend answers 400. A completed job has result_url (final image) and
 * metadata.steps = [{ item_id, category, image_url }] in render order.
 */
async function generateVton(itemIds) {
  if (USE_MOCK) {
    await delay(500);
    if (!mockBaselineReady) {
      throw mockError(400, "Upload your baseline photo first.");
    }
    if (!Array.isArray(itemIds) || itemIds.length === 0) {
      throw mockError(422, "item_ids is required.");
    }
    const jobId = createMockJob("vton", { itemIds });
    return { status: "queued", job_id: jobId, message: "Rendering virtual try-on..." };
  }
  return apiRequest("/vton/generate", { method: "POST", body: { item_ids: itemIds } });
}

/* ================================================================
 * Module 1.3: Async job manager (polling)
 * ================================================================ */

const POLL_INTERVAL_MS = USE_MOCK ? 1000 : 3000; // plan: ping every 3-5 seconds
const POLL_TIMEOUT_MS = 5 * 60 * 1000;           // give up after 5 minutes
const POLL_MAX_RETRIES = 3;                       // consecutive transient failures allowed

function abortError() {
  const err = new Error("Polling was cancelled.");
  err.name = "AbortError";
  return err;
}

/** Waits `ms`, but rejects early if `signal` is aborted. */
function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal && signal.aborted) return reject(abortError());
    const timer = setTimeout(() => {
      if (signal) signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    function onAbort() {
      clearTimeout(timer);
      reject(abortError());
    }
    if (signal) signal.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Polls GET /jobs/status/{job_id} until the job finishes.
 *
 * Resolves with the final status body when status is "completed" OR "failed"
 * (a failed job is a normal 200 response; check `result.status` and show `result.error`).
 *
 * Rejects (so ui.js should catch) when:
 *   - the server answers 4xx (401 expired token, 404 unknown job, ...): no point retrying
 *   - the server/network keeps failing (more than POLL_MAX_RETRIES times in a row)
 *   - the timeout passes (err.code === "timeout")
 *   - the caller aborts (err.name === "AbortError")
 *
 * Options:
 *   onUpdate(statusBody)  called after every successful check (use it to update loading text)
 *   intervalMs, timeoutMs optional overrides
 *   signal                an AbortSignal; abort it to stop polling (e.g. user starts a new upload)
 *
 * Checks never overlap: the next request is only sent after the previous one finished.
 */
async function pollJob(jobId, options = {}) {
  const {
    onUpdate = null,
    intervalMs = POLL_INTERVAL_MS,
    timeoutMs = POLL_TIMEOUT_MS,
    signal = null,
  } = options;

  const startedAt = Date.now();
  let failuresInARow = 0;

  while (true) {
    if (signal && signal.aborted) throw abortError();

    let body;
    try {
      body = await getJobStatus(jobId);
      failuresInARow = 0;
    } catch (err) {
      const status = err.status;
      const isTransient = status === 0 || status >= 500;
      failuresInARow += 1;
      if (!isTransient || failuresInARow > POLL_MAX_RETRIES) throw err;
      // transient problem: fall through, wait, and try again
      body = null;
    }

    if (body) {
      if (onUpdate) onUpdate(body);
      if (body.status === "completed" || body.status === "failed") return body;
    }

    if (Date.now() - startedAt + intervalMs > timeoutMs) {
      const err = new Error("This is taking too long. Please try again.");
      err.code = "timeout";
      throw err;
    }

    await sleep(intervalMs, signal);
  }
}