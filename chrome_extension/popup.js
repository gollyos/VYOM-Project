const DEFAULT_BRAIN_URL = "ws://127.0.0.1:7788/api/extension/ws";
const DEFAULT_PAIRING_PAGE = "http://127.0.0.1:7788/api/extension/pairing";

const dot = document.getElementById("dot");
const statusText = document.getElementById("statusText");
const urlInput = document.getElementById("url");
const tokenInput = document.getElementById("token");

async function refreshStatus() {
  const stored = await chrome.storage.local.get(["vyomStatus", "vyomBrainUrl", "vyomToken"]);
  const status = stored.vyomStatus || (stored.vyomToken ? "disconnected" : "unpaired");
  dot.className = `dot ${status}`;
  statusText.textContent = {
    connected: "Connected to VYOM",
    connecting: "Connecting…",
    disconnected: "Disconnected - retrying",
    unpaired: "Not paired yet",
  }[status] || status;
  urlInput.value = stored.vyomBrainUrl || DEFAULT_BRAIN_URL;
  tokenInput.value = stored.vyomToken || "";
}

document.getElementById("save").addEventListener("click", async () => {
  const url = urlInput.value.trim() || DEFAULT_BRAIN_URL;
  const token = tokenInput.value.trim();
  await chrome.storage.local.set({ vyomBrainUrl: url, vyomToken: token });
  statusText.textContent = "Saved. Connecting…";
  setTimeout(refreshStatus, 800);
});

document.getElementById("openPairing").addEventListener("click", () => {
  // A real navigated tab, not a fetch() from the extension's own origin -
  // the Brain's CORS allowlist only covers the desktop app's own origins,
  // so a cross-origin fetch from chrome-extension://... would be blocked
  // even though the endpoint itself needs no auth for a loopback caller.
  const base = urlInput.value.trim().replace(/^ws/, "http").replace(/\/api\/extension\/ws$/, "");
  const pairingUrl = base ? `${base}/api/extension/pairing` : DEFAULT_PAIRING_PAGE;
  chrome.tabs.create({ url: pairingUrl });
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.vyomStatus) refreshStatus();
});

refreshStatus();
