const API_BASE = "https://6q03i3h4vi.execute-api.us-east-1.amazonaws.com";
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
const ALLOWED_TYPES = ["image/jpeg", "image/png"];
const USER_KEY = "faceguardUserId";
const USER_ID_PATTERN = /^[a-f0-9]{32}$/;

const statusEl = document.getElementById("status");
const scanBtn = document.getElementById("scanBtn");
const listEl = document.getElementById("alertList");
const fileInput = document.getElementById("refFile");
const uploadBtn = document.getElementById("uploadBtn");
const uploadMsg = document.getElementById("uploadMsg");
const emailInput = document.getElementById("emailInput");
const saveEmailBtn = document.getElementById("saveEmailBtn");
const emailMsg = document.getElementById("emailMsg");
const refCountEl = document.getElementById("refCount");
const userIdText = document.getElementById("userIdText");

// ---------- Anonymous user identity ----------
// Each browser gets a random ID the first time FaceGuard runs.
// The backend uses it to keep every person's photos, alerts and email separate.

function newUserId() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function loadOrCreateUserId() {
  try {
    const saved = localStorage.getItem(USER_KEY);
    if (saved && USER_ID_PATTERN.test(saved)) return saved;
    const created = newUserId();
    localStorage.setItem(USER_KEY, created);
    return created;
  } catch (_) {
    // Storage unavailable: use an ID that lasts only while this window is open.
    return newUserId();
  }
}

const USER_ID = loadOrCreateUserId();

// ---------- Small helpers ----------

function setStatus(text, kind = "info") {
  statusEl.textContent = text;
  statusEl.className = "status " + kind;
}

function setUploadMsg(text, kind = "") {
  uploadMsg.textContent = text;
  uploadMsg.className = "upload-msg " + kind;
}

function setEmailMsg(text, kind = "") {
  emailMsg.textContent = text;
  emailMsg.className = "upload-msg " + kind;
}

// Call the backend with a timeout, return the parsed JSON.
// Every request carries the user's anonymous ID.
async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 40000);
  try {
    const headers = { ...(options.headers || {}), "x-user-id": USER_ID };
    const res = await fetch(API_BASE + path, { ...options, headers, signal: controller.signal });
    if (!res.ok) {
      let message = "Server returned " + res.status;
      try {
        const data = await res.json();
        if (data && data.error) message = data.error;
      } catch (_) {
        // response had no JSON body, keep the generic message
      }
      throw new Error(message);
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

// ---------- Takedown request ----------

function buildRemovalMessage(alert) {
  const found = formatTime(alert.scannedAt) || "recently";
  const isDeepfake = alert.verdict === "Possible deepfake";

  const subject = isDeepfake
    ? "Removal request: manipulated image of me published without consent"
    : "Removal request: image of me published without consent";

  const finding = isDeepfake
    ? "The image appears to have been digitally edited or generated, so it may misrepresent me."
    : "This is a photo of me that was posted without my permission.";

  const body = [
    "Hello,",
    "",
    "I am requesting the removal of an image of me that is published on your platform without my consent.",
    "",
    "Link to the page with the image: [paste the URL here]",
    "Image reference: " + alert.imageId,
    "Detected by FaceGuard on: " + found,
    "",
    finding,
    "Automated analysis (estimates, not proof):",
    "- Face match confidence: " + alert.similarity + "%",
    "- Manipulation likelihood: " + alert.manipulationScore + "/100",
    "",
    "I did not give permission for this image to be shared. Please remove it as soon as possible and confirm once it has been taken down. I can provide proof of identity if needed.",
    "",
    "Thank you,",
    "[Your name]",
  ].join("\n");

  return { subject, body };
}

// Works both inside the Chrome extension and on a normal web page.
function openInNewTab(url) {
  if (typeof chrome !== "undefined" && chrome.tabs && chrome.tabs.create) {
    chrome.tabs.create({ url });
  } else {
    window.open(url, "_blank", "noopener");
  }
}

function openRemovalEmail(alert) {
  const { subject, body } = buildRemovalMessage(alert);
  const url =
    "https://mail.google.com/mail/?view=cm&fs=1" +
    "&su=" + encodeURIComponent(subject) +
    "&body=" + encodeURIComponent(body);
  openInNewTab(url);
}

async function copyRemovalText(alert, button) {
  const { subject, body } = buildRemovalMessage(alert);
  try {
    await navigator.clipboard.writeText("Subject: " + subject + "\n\n" + body);
    button.textContent = "Copied!";
  } catch (err) {
    button.textContent = "Copy failed";
  }
  setTimeout(() => {
    button.textContent = "Copy text";
  }, 2000);
}

// ---------- Alerts list ----------

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

    const actions = makeEl("div", "alert-actions");

    const removeBtn = makeEl("button", "", "Request removal");
    removeBtn.type = "button";
    removeBtn.addEventListener("click", () => openRemovalEmail(a));
    actions.appendChild(removeBtn);

    const copyBtn = makeEl("button", "secondary", "Copy text");
    copyBtn.type = "button";
    copyBtn.addEventListener("click", () => copyRemovalText(a, copyBtn));
    actions.appendChild(copyBtn);

    li.appendChild(actions);
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

// ---------- Profile: email and reference photo count ----------

async function loadProfile() {
  try {
    const me = await api("/me");
    if (me.email) {
      emailInput.value = me.email;
      setEmailMsg(
        "Alerts will be sent to " + me.email + ". If you have not yet, click the confirmation link AWS emailed you.",
        "success"
      );
    } else {
      setEmailMsg("Add your email to receive alerts.", "");
    }
    refCountEl.textContent =
      me.referenceCount + " of " + me.maxReferences + " reference photos uploaded.";
  } catch (err) {
    setEmailMsg("Could not load your profile: " + err.message, "error");
  }
}

async function saveEmail() {
  const email = emailInput.value.trim();
  if (!email || !emailInput.checkValidity()) {
    setEmailMsg("Enter a valid email address.", "error");
    return;
  }

  saveEmailBtn.disabled = true;
  saveEmailBtn.textContent = "Saving...";
  setEmailMsg("Saving...", "");

  try {
    const result = await api("/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    setEmailMsg(result.message, "success");
  } catch (err) {
    setEmailMsg("Could not save: " + err.message, "error");
  } finally {
    saveEmailBtn.disabled = false;
    saveEmailBtn.textContent = "Save email";
  }
}

// ---------- Reference photo upload ----------

async function uploadReference() {
  const file = fileInput.files[0];

  if (!file) {
    setUploadMsg("Choose a JPG or PNG photo first.", "error");
    return;
  }
  if (!ALLOWED_TYPES.includes(file.type)) {
    setUploadMsg("Only JPG and PNG photos are allowed.", "error");
    return;
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    setUploadMsg("That photo is over 5 MB. Choose a smaller one.", "error");
    return;
  }

  uploadBtn.disabled = true;
  uploadBtn.textContent = "Uploading...";
  setUploadMsg("Uploading...", "");

  try {
    // 1. Ask the backend for a short-lived upload ticket
    const ticket = await api("/upload-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contentType: file.type }),
    });

    // 2. Send the photo straight to S3 with that ticket
    const form = new FormData();
    for (const [key, value] of Object.entries(ticket.fields)) {
      form.append(key, value);
    }
    form.append("file", file); // the file field must come last

    const res = await fetch(ticket.url, { method: "POST", body: form });
    if (!res.ok) {
      throw new Error("Upload failed (" + res.status + ")");
    }

    fileInput.value = "";
    setUploadMsg("Uploaded! It will be used in your next scan.", "success");
    loadProfile();
  } catch (err) {
    setUploadMsg("Upload failed: " + err.message, "error");
  } finally {
    uploadBtn.disabled = false;
    uploadBtn.textContent = "Upload reference photo";
  }
}

// ---------- Start ----------

scanBtn.addEventListener("click", runScan);
uploadBtn.addEventListener("click", uploadReference);
saveEmailBtn.addEventListener("click", saveEmail);

userIdText.textContent = USER_ID;

loadAlerts().catch((err) => {
  setStatus("Could not load alerts: " + err.message, "error");
});
loadProfile();
