# VYOM Browser Bridge

A Chrome extension that gives VYOM real access to the browser you're
actually using - your real tabs, your real signed-in profile, real DOM
content - instead of the isolated automation browser (`app.browser.*`) or
the screen-reading UI-Automation path (`app.desktop.*`) it falls back to
when this extension isn't connected.

## Install (unpacked, for now)

1. Open `chrome://extensions`.
2. Turn on **Developer mode** (top right).
3. **Load unpacked** → select this `chrome_extension` folder.
4. Click the VYOM icon in the toolbar to open the popup.

## Pair it with VYOM

1. Make sure the VYOM Brain is running locally (default `127.0.0.1:7788`).
2. In the popup, click **Open pairing page**. It opens
   `http://127.0.0.1:7788/api/extension/pairing` in a new tab - copy the
   `token` value shown there.
3. Back in the popup, paste it into **Pairing token** and click
   **Save & connect**.
4. The status dot turns green once connected. The token is remembered
   (both by the extension and by the Brain), so this is a one-time step -
   the extension reconnects automatically after a browser or Brain
   restart.

If the Brain isn't at the default address, edit **VYOM Brain address**
first (it must be a `ws://` URL ending in `/api/extension/ws`).

## What VYOM can do once connected

Through `ActionEngine` (`services/brain/app/execution/action_engine.py`),
these existing browser intents prefer the extension automatically and
fall back to the old UI-Automation path if it's ever unreachable:

- **list / open tabs** - real tab list, real `chrome.tabs.create`
- **read the page** - actual DOM text, headings and links, not just what
  UI Automation can see on screen
- **find on the page** - a real substring/DOM search with surrounding
  context, for "find X on this page" / "is X mentioned here"
- **click** - by visible text or CSS selector, on the real element

## Files

- `manifest.json` - Manifest V3 definition
- `background.js` - the service worker: holds the WebSocket to the Brain,
  dispatches commands, injects the DOM-side functions on demand via
  `chrome.scripting.executeScript`
- `popup.html` / `popup.js` - pairing UI and live connection status

## Security notes

- The extension only talks to the address you configure (default
  loopback). Change it only if VYOM's Brain is genuinely reachable
  elsewhere.
- The pairing token is required on every connection - a page or another
  extension cannot make VYOM act on your browser without it.
- `host_permissions: <all_urls>` is required for a page-read/click/type
  command to work on whatever site you're actually on; the extension only
  acts when VYOM sends it an explicit command, never on its own.
