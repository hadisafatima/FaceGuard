const API_BASE = "https://6q03i3h4vi.execute-api.us-east-1.amazonaws.com";

const statusEl = document.getElementById("status");
const scanBtn = document.getElementById("scanBtn");
const listEl = document.getElementById("alertList");

function setStatus(text, kind = "info") {
  statusEl.textContent = text;
  statusEl.className = "status " + kind;
}

// Call the backend with a timeout, return the parsed JSON.
async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 40000);
  try {
    const res = await fetch(API_BASE + path, { ...options, signal: controller.signal });
    if (!res.ok) {
      throw new Error("Server returned " + res.status);
    }
    return await res.json();
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error("The request timed out");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

function verdictClass(verdict) {
  return verdict === "Possible deepfake" ? "deepfake" : "repost";
}

function formatTime(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleString();
}

function makeEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

function renderAlerts(alerts) {
  listEl.replaceChildren();

  if (!alerts.length) {
    listEl.appendChild(makeEl("li", "empty", "No alerts to show yet."));
    return;
  }

  for (const a of alerts) {
    const cls = verdictClass(a.verdict);
    const li = makeEl("li", "alert " + cls);

    const top = makeEl("div", "alert-top");
    top.appendChild(makeEl("span", "alert-name", a.imageId));
    top.appendChild(makeEl("span", "badge " + cls, a.verdict));
    li.appendChild(top);

    li.appendChild(
      makeEl(
        "div",
        "alert-details",
        "Face match: " + a.similarity + "%  |  Manipulation score: " + a.manipulationScore + "/100"
      )
    );

    const when = formatTime(a.scannedAt);
    if (when) li.appendChild(makeEl("div", "alert-time", "Scanned " + when));

    listEl.appendChild(li);
  }
}

async function loadAlerts() {
  setStatus("Loading alerts...", "info");
  const data = await api("/alerts");
  renderAlerts(data.alerts);
  setStatus(data.count + " alert(s) found.", "success");
}

async function runScan() {
  scanBtn.disabled = true;
  scanBtn.textContent = "Scanning...";
  setStatus("Scanning... this takes about 15 seconds. Keep this window open.", "info");

  try {
    const result = await api("/scan", { method: "POST" });
    await loadAlerts();
    setStatus(
      "Scan complete: " + result.flagged + " flagged out of " + result.scanned + " images.",
      "success"
    );
  } catch (err) {
    setStatus("Scan failed: " + err.message, "error");
  } finally {
    scanBtn.disabled = false;
    scanBtn.textContent = "Scan now";
  }
}

scanBtn.addEventListener("click", runScan);

loadAlerts().catch((err) => {
  setStatus("Could not load alerts: " + err.message, "error");
});