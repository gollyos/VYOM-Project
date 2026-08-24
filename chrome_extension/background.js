// VYOM Browser Bridge - background service worker.
//
// Holds one WebSocket back to the local VYOM Brain and executes whatever
// command it sends against the user's REAL Chrome (real tabs, real
// signed-in session) - the thing app.browser.* (an isolated Playwright
// browser) and the desktop UI-Automation path can't do: real DOM access
// to the page the user is actually looking at.

const DEFAULT_BRAIN_URL = "ws://127.0.0.1:7788/api/extension/ws";
const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 30000;

let socket = null;
let reconnectDelay = RECONNECT_MIN_MS;
let reconnectTimer = null;

// -- connection ---------------------------------------------------------

async function getConfig() {
  const stored = await chrome.storage.local.get(["vyomBrainUrl", "vyomToken"]);
  return {
    url: stored.vyomBrainUrl || DEFAULT_BRAIN_URL,
    token: stored.vyomToken || "",
  };
}

async function connect() {
  const { url, token } = await getConfig();
  if (!token) {
    setStatus("unpaired");
    return; // nothing to connect with until the popup saves a token
  }
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  const target = `${url}?token=${encodeURIComponent(token)}`;
  setStatus("connecting");
  try {
    socket = new WebSocket(target);
  } catch (error) {
    scheduleReconnect();
    return;
  }

  socket.onopen = () => {
    reconnectDelay = RECONNECT_MIN_MS;
    setStatus("connected");
  };

  socket.onmessage = async (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (error) {
      return; // malformed frame; never crash the connection over it
    }
    const { id, cmd, params } = message;
    if (!id || !cmd) return;
    try {
      const result = await runCommand(cmd, params || {});
      send({ id, ok: true, result });
    } catch (error) {
      send({ id, ok: false, error: String((error && error.message) || error) });
    }
  };

  socket.onclose = () => {
    setStatus("disconnected");
    scheduleReconnect();
  };

  socket.onerror = () => {
    // onclose always follows onerror for a WebSocket; the reconnect is
    // scheduled there, not duplicated here.
  };
}

function send(payload) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(payload));
  }
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(async () => {
    reconnectTimer = null;
    reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
    await connect();
  }, reconnectDelay);
}

async function setStatus(status) {
  await chrome.storage.local.set({ vyomStatus: status });
}

chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && (changes.vyomBrainUrl || changes.vyomToken)) {
    if (socket) {
      try { socket.close(); } catch (error) { /* already closing */ }
      socket = null;
    }
    reconnectDelay = RECONNECT_MIN_MS;
    connect();
  }
});
connect();

// -- command dispatch -----------------------------------------------------

async function resolveTab(params) {
  if (params && params.tabId) {
    return chrome.tabs.get(params.tabId);
  }
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab) throw new Error("No active tab is open.");
  return tab;
}

async function runCommand(cmd, params) {
  switch (cmd) {
    case "list_tabs":
      return listTabs();
    case "open_tab":
      return openTab(params.url);
    case "close_tab":
      return closeTab(params);
    case "activate_tab":
      return activateTab(params);
    case "read_page":
      return execOnTab(params, extractPage, []);
    case "find_on_page":
      return execOnTab(params, findOnPage, [params.query || ""]);
    case "click":
      return execOnTab(params, clickTarget, [params.selector || null, params.text || null]);
    case "type":
      return execOnTab(params, typeInto, [params.selector || null, params.text || "", !!params.submit]);
    case "scroll":
      return execOnTab(params, scrollPage, [params.direction || "down", params.amount || 600]);
    default:
      throw new Error(`Unknown command: ${cmd}`);
  }
}

async function listTabs() {
  const tabs = await chrome.tabs.query({});
  return tabs.map((tab) => ({
    id: tab.id, title: tab.title || "", url: tab.url || "",
    active: !!tab.active, windowId: tab.windowId,
  }));
}

async function openTab(url) {
  if (!url) throw new Error("No URL given to open.");
  const normalised = /^https?:\/\//i.test(url) ? url : `https://${url}`;
  const tab = await chrome.tabs.create({ url: normalised, active: true });
  return { id: tab.id, url: tab.url || normalised, title: tab.title || "" };
}

async function closeTab(params) {
  const tab = await resolveTab(params);
  await chrome.tabs.remove(tab.id);
  return { closed: true, id: tab.id };
}

async function activateTab(params) {
  const tab = await resolveTab(params);
  await chrome.tabs.update(tab.id, { active: true });
  await chrome.windows.update(tab.windowId, { focused: true });
  return { activated: true, id: tab.id };
}

async function execOnTab(params, func, args) {
  const tab = await resolveTab(params);
  const [injection] = await chrome.scripting.executeScript({
    target: { tabId: tab.id }, func, args,
  });
  return injection && injection.result;
}

// -- functions injected into the page (must be fully self-contained) ------

function extractPage() {
  function isVisible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    const style = window.getComputedStyle(el);
    return style.visibility !== "hidden" && style.display !== "none";
  }
  const title = document.title || "";
  const url = location.href;
  const bodyText = ((document.body && document.body.innerText) || "").trim();
  const headings = Array.from(document.querySelectorAll("h1, h2, h3"))
    .filter(isVisible).map((h) => h.innerText.trim()).filter(Boolean).slice(0, 30);
  const links = Array.from(document.querySelectorAll("a[href]"))
    .filter(isVisible)
    .map((a) => ({ text: a.innerText.trim().slice(0, 80), href: a.href }))
    .filter((l) => l.text)
    .slice(0, 50)
    .map((l) => `${l.text} (${l.href})`);
  return { title, url, text: bodyText.slice(0, 20000), headings, links };
}

function findOnPage(query) {
  const needle = (query || "").toLowerCase();
  if (!needle) return { matches: [] };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
  const matches = [];
  let node;
  while ((node = walker.nextNode()) && matches.length < 10) {
    const text = node.textContent;
    if (!text) continue;
    const idx = text.toLowerCase().indexOf(needle);
    if (idx === -1) continue;
    const parent = node.parentElement;
    if (parent) {
      const style = window.getComputedStyle(parent);
      if (style.visibility === "hidden" || style.display === "none") continue;
    }
    const start = Math.max(0, idx - 60);
    const end = Math.min(text.length, idx + query.length + 60);
    matches.push(text.slice(start, end).trim());
  }
  return { matches };
}

function clickTarget(selector, text) {
  function isVisible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    const style = window.getComputedStyle(el);
    return style.visibility !== "hidden" && style.display !== "none";
  }
  let el = selector ? document.querySelector(selector) : null;
  if (!el && text) {
    const needle = text.toLowerCase().trim();
    const candidates = Array.from(document.querySelectorAll(
      'a, button, [role="button"], input[type="submit"], input[type="button"], summary, [onclick]'
    )).filter(isVisible);
    const label = (node) =>
      (node.innerText || node.value || node.getAttribute("aria-label") || "").toLowerCase().trim();
    el = candidates.find((c) => label(c) === needle) || candidates.find((c) => label(c).includes(needle));
  }
  if (!el) {
    return { success: false, error: `No clickable element found for "${text || selector}".` };
  }
  el.scrollIntoView({ block: "center", behavior: "instant" });
  el.click();
  const shown = (el.innerText || el.value || el.getAttribute("aria-label") || text || selector || "")
    .trim().slice(0, 60);
  return { success: true, summary: `Clicked '${shown}'.` };
}

function typeInto(selector, text, submit) {
  function isVisible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }
  let el = selector ? document.querySelector(selector) : null;
  if (!el) {
    const active = document.activeElement;
    if (active && ["INPUT", "TEXTAREA"].includes(active.tagName)) {
      el = active;
    } else {
      el = Array.from(document.querySelectorAll(
        'input[type="text"], input[type="search"], input:not([type]), textarea'
      )).filter(isVisible)[0];
    }
  }
  if (!el) {
    return { success: false, error: "No text input found on this page." };
  }
  el.focus();
  const proto = el.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
  setter.call(el, text);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  if (submit) {
    const form = el.closest("form");
    if (form) {
      form.requestSubmit ? form.requestSubmit() : form.submit();
    } else {
      el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    }
  }
  return { success: true, summary: "Typed into the field." };
}

function scrollPage(direction, amount) {
  const delta = amount || 600;
  const dy = direction === "up" ? -delta : delta;
  window.scrollBy({ top: dy, behavior: "instant" });
  return { success: true };
}
