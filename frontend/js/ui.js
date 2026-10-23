/**
 * ui.js - Module 1.4: DOM wiring + media display.
 *
 * Rules:
 *  - All DOM access lives here. All network logic stays in api.js.
 *  - Loading / success / error states are driven only by API results.
 *  - Server-provided text is inserted with textContent / createElement, never innerHTML.
 *
 * Status boxes use data-state="idle | loading | success | error" so style.css can style them.
 * Wrapped in an IIFE so names here can never clash with globals in api.js.
 */
(function () {
  "use strict";

  const WARDROBE_CACHE_KEY = "desi9Wardrobe"; // fallback while GET /wardrobe/items is not built
  const PROGRESS_TEXT = { queued: "Waiting in line...", processing: "Processing..." };

  const $ = (id) => document.getElementById(id);

  const el = {
    wardrobeForm: $("wardrobeUploadForm"),
    wardrobeFile: $("wardrobeFileInput"),
    wardrobeBtn: $("wardrobeUploadBtn"),
    wardrobeStatus: $("wardrobeStatus"),
    wardrobeGrid: $("wardrobeGrid"),
    baselineForm: $("baselineUploadForm"),
    baselineFile: $("baselineFileInput"),
    baselineBtn: $("baselineUploadBtn"),
    baselineStatus: $("baselineStatus"),
    baselinePreview: $("baselinePreview"),
    recommendBtn: $("recommendBtn"),
    outfitStatus: $("outfitStatus"),
    outfitCards: $("outfitCards"),
    vtonBtn: $("vtonGenerateBtn"),
    vtonStatus: $("vtonStatus"),
    vtonImage: $("vtonResultImage"),
  };

  const state = {
    wardrobe: [],
    outfits: [],
    selectedIndex: null,
    vtonBusy: false,
  };

  /* ---------- Small helpers ---------- */

  function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function setStatus(target, stateName, message) {
    target.dataset.state = stateName;
    target.textContent = "";
    if (stateName === "loading") {
      const spinner = make("span", "spinner");
      spinner.setAttribute("aria-hidden", "true");
      target.appendChild(spinner);
    }
    if (message) target.appendChild(document.createTextNode(message));
  }

  function describeItem(item) {
    return [item.color, item.sub_category].filter(Boolean).join(" ") || item.category || "Clothing item";
  }

  /* ---------- Job runner (start request -> pollJob -> final result) ---------- */

  const controllers = {}; // one AbortController per kind of job

  /**
   * Returns the completed status body, or null if the job failed, errored or was cancelled
   * (in those cases the status box already shows the reason).
   */
  async function runJob(key, statusEl, startMessage, startRequest) {
    if (controllers[key]) controllers[key].abort();
    const controller = new AbortController();
    controllers[key] = controller;
    const signal = controller.signal;

    setStatus(statusEl, "loading", startMessage);
    try {
      const started = await startRequest();
      const result = await pollJob(started.job_id, {
        signal,
        onUpdate: (body) => setStatus(statusEl, "loading", PROGRESS_TEXT[body.status] || "Working..."),
      });
      if (result.status === "failed") {
        setStatus(statusEl, "error", result.error || "Something went wrong. Please try again.");
        return null;
      }
      return result;
    } catch (err) {
      if (err.name === "AbortError") return null;
      setStatus(statusEl, "error", err.message || "Something went wrong. Please try again.");
      return null;
    }
  }

  window.addEventListener("pagehide", () => {
    Object.values(controllers).forEach((c) => c.abort());
  });

  /* ---------- Wardrobe: cache + grid ---------- */

  function readWardrobeCache() {
    try {
      const parsed = JSON.parse(localStorage.getItem(WARDROBE_CACHE_KEY) || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      return [];
    }
  }

  function writeWardrobeCache(items) {
    try {
      localStorage.setItem(WARDROBE_CACHE_KEY, JSON.stringify(items));
    } catch (err) {
      // storage full or blocked: the grid still works for this session
    }
  }

  function cacheNewItem(item) {
    if (!item.item_id) return;
    const items = readWardrobeCache().filter((i) => i.item_id !== item.item_id);
    items.push(item);
    writeWardrobeCache(items);
  }

  function renderWardrobe() {
    el.wardrobeGrid.textContent = "";
    if (state.wardrobe.length === 0) {
      el.wardrobeGrid.appendChild(make("p", "empty", "No items yet. Upload your first piece above."));
      return;
    }
    state.wardrobe.forEach((item) => {
      const figure = make("figure", "grid-item");
      const img = make("img");
      img.src = item.image_url;
      img.alt = describeItem(item);
      img.loading = "lazy";
      figure.appendChild(img);
      figure.appendChild(make("figcaption", "", describeItem(item)));
      el.wardrobeGrid.appendChild(figure);
    });
  }

  /** Loads the wardrobe from the server; falls back to the local cache if the endpoint is missing. */
  async function refreshWardrobe() {
    try {
      const data = await listWardrobeItems();
      state.wardrobe = data.items || [];
      writeWardrobeCache(state.wardrobe);
      renderWardrobe();
      return true;
    } catch (err) {
      if (err.status === 404 || err.status === 0) {
        state.wardrobe = readWardrobeCache();
        renderWardrobe();
        return true;
      }
      setStatus(el.wardrobeStatus, "error", err.message);
      return false;
    }
  }

  /* ---------- Section 1: upload clothes ---------- */

  el.wardrobeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = el.wardrobeFile.files[0];
    const problem = validateImageFile(file);
    if (problem) {
      setStatus(el.wardrobeStatus, "error", problem);
      return;
    }

    el.wardrobeBtn.disabled = true;
    const result = await runJob("wardrobe", el.wardrobeStatus, "Uploading...", () => uploadWardrobeItem(file));
    el.wardrobeBtn.disabled = false;
    if (!result) return;

    const meta = result.metadata || {};
    cacheNewItem({
      item_id: meta.item_id,
      image_url: result.result_url,
      category: meta.category,
      sub_category: meta.sub_category,
      color: meta.color,
      fabric: meta.fabric,
    });
    const refreshed = await refreshWardrobe();
    if (refreshed) {
      setStatus(el.wardrobeStatus, "success", `Added: ${describeItem(meta)}.`);
      el.wardrobeForm.reset();
    }
  });

  /* ---------- Section 2: baseline photo ---------- */

  el.baselineForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = el.baselineFile.files[0];
    const problem = validateImageFile(file);
    if (problem) {
      setStatus(el.baselineStatus, "error", problem);
      return;
    }

    el.baselineBtn.disabled = true;
    const result = await runJob("baseline", el.baselineStatus, "Uploading...", () => uploadBaselinePhoto(file));
    el.baselineBtn.disabled = false;
    if (!result) return;

    if (result.result_url) {
      el.baselinePreview.src = result.result_url;
      el.baselinePreview.classList.remove("hidden");
    }
    setStatus(el.baselineStatus, "success", "Photo saved. You can now try outfits on.");
    el.baselineForm.reset();
  });

  /* ---------- Section 3: outfit recommendations ---------- */

  function updateVtonButton() {
    el.vtonBtn.disabled = state.selectedIndex === null || state.vtonBusy;
  }

  function selectOutfit(index) {
    state.selectedIndex = index;
    el.outfitCards.querySelectorAll(".outfit-card").forEach((card, i) => {
      const selected = i === index;
      card.classList.toggle("selected", selected);
      const button = card.querySelector("button");
      button.setAttribute("aria-pressed", String(selected));
      button.textContent = selected ? "Selected" : "Select outfit";
    });
    updateVtonButton();
    const outfit = state.outfits[index];
    setStatus(el.vtonStatus, "idle", `Selected: ${outfit.name || "Outfit " + (index + 1)}. Ready to generate.`);
  }

  function renderOutfits() {
    el.outfitCards.textContent = "";
    if (state.outfits.length === 0) {
      el.outfitCards.appendChild(make("p", "empty", "No recommendations yet."));
      return;
    }
    state.outfits.forEach((outfit, index) => {
      const card = make("div", "outfit-card");
      card.appendChild(make("strong", "outfit-name", outfit.name || `Outfit ${index + 1}`));
      if (outfit.occasion) card.appendChild(make("span", "outfit-occasion", outfit.occasion.replace(/_/g, " ")));

      const row = make("div", "outfit-items");
      (outfit.items || []).forEach((item) => {
        const img = make("img");
        img.src = item.image_url;
        img.alt = item.category || "garment";
        row.appendChild(img);
      });
      card.appendChild(row);

      if (outfit.reasoning) card.appendChild(make("p", "outfit-reasoning", outfit.reasoning));

      const button = make("button", "btn", "Select outfit");
      button.type = "button";
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", () => selectOutfit(index));
      card.appendChild(button);

      el.outfitCards.appendChild(card);
    });
  }

  el.recommendBtn.addEventListener("click", async () => {
    el.recommendBtn.disabled = true;
    const result = await runJob("outfits", el.outfitStatus, "Putting outfits together...", requestOutfitRecommendations);
    el.recommendBtn.disabled = false;
    if (!result) return;

    state.outfits = (result.metadata && result.metadata.outfits) || [];
    state.selectedIndex = null;
    renderOutfits();
    updateVtonButton();

    if (state.outfits.length === 0) {
      setStatus(el.outfitStatus, "idle", "No outfits yet. Upload at least one top and one bottom first.");
    } else {
      setStatus(el.outfitStatus, "success", `${state.outfits.length} outfit idea(s) ready. Pick one to try on.`);
    }
  });

  /* ---------- Section 4: virtual try-on result ---------- */

  el.vtonImage.addEventListener("error", () => {
    el.vtonImage.classList.add("hidden");
    setStatus(el.vtonStatus, "error", "The try-on image could not be loaded. Please generate it again.");
  });

  el.vtonBtn.addEventListener("click", async () => {
    const outfit = state.outfits[state.selectedIndex];
    if (!outfit) return;

    state.vtonBusy = true;
    updateVtonButton();
    el.vtonImage.classList.add("hidden");

    const result = await runJob("vton", el.vtonStatus, "Starting try-on...", () => generateVton(outfit.item_ids));

    state.vtonBusy = false;
    updateVtonButton();
    if (!result) return;

    if (!result.result_url) {
      setStatus(el.vtonStatus, "error", "The try-on finished but no image came back. Please try again.");
      return;
    }
    el.vtonImage.alt = `Virtual try-on: ${outfit.name || "selected outfit"}`;
    el.vtonImage.src = result.result_url;
    el.vtonImage.classList.remove("hidden");
    setStatus(el.vtonStatus, "success", "Your try-on is ready.");
  });

  /* ---------- Start-up ---------- */

  renderWardrobe();
  renderOutfits();
  updateVtonButton();
  refreshWardrobe();
})();