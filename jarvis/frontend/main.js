/**
 * JARVIS Desktop Assistant — Frontend Controller (Eel Bridge)
 */

document.addEventListener("DOMContentLoaded", () => {
  // DOM References
  const chatMessages = document.getElementById("chatMessages");
  const chatContainer = document.getElementById("chatContainer");
  const txtCommand = document.getElementById("txtCommand");
  const btnSend = document.getElementById("btnSend");
  const btnMic = document.getElementById("btnMic");
  const orbWrapper = document.getElementById("orbWrapper");
  const orbStatus = document.getElementById("orbStatus");
  const systemStateBadge = document.getElementById("systemStateBadge");
  const systemStateText = document.getElementById("systemStateText");
  const historyList = document.getElementById("historyList");
  const contactsList = document.getElementById("contactsList");
  const btnRefreshHistory = document.getElementById("btnRefreshHistory");
  const btnRefreshContacts = document.getElementById("btnRefreshContacts");
  const btnAddContact = document.getElementById("btnAddContact");
  const initTime = document.getElementById("initTime");

  if (initTime) {
    initTime.textContent = formatCurrentTime();
  }

  // Helper: Format current time
  function formatCurrentTime() {
    const d = new Date();
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  // =========================================================================
  // Eel Exposed JavaScript Functions (Called from Python Backend)
  // =========================================================================

  /**
   * Display a chat message bubble in the UI canvas.
   * @param {string} sender - 'user' or 'jarvis'
   * @param {string} text - Message body
   * @param {string} [timeStr] - Formatted timestamp
   */
  window.displayMessage = function (sender, text, timeStr) {
    if (!text || !text.trim()) return;

    const row = document.createElement("div");
    row.className = `message-row ${sender === "user" ? "user-row" : "jarvis-row"}`;

    const time = timeStr || formatCurrentTime();
    const isJarvis = sender.toLowerCase() === "jarvis";

    const avatarHtml = isJarvis
      ? `<div class="message-avatar"><i class="bi bi-robot"></i></div>`
      : `<div class="message-avatar"><i class="bi bi-person"></i></div>`;

    const bubbleHtml = `
      <div class="message-bubble ${isJarvis ? "jarvis-bubble" : "user-bubble"}">
        <div class="message-sender">${isJarvis ? "JARVIS" : "YOU"}</div>
        <div class="message-content">${escapeHtml(text)}</div>
        <div class="message-time">${time}</div>
      </div>
    `;

    row.innerHTML = avatarHtml + bubbleHtml;
    chatMessages.appendChild(row);

    // Auto-scroll to bottom
    chatContainer.scrollTop = chatContainer.scrollHeight;
  };

  /**
   * Update visual orb state and status texts.
   * @param {string} state - 'ready', 'listening', 'thinking', 'speaking', 'error'
   */
  window.setJarvisState = function (state) {
    orbWrapper.classList.remove("state-listening", "state-thinking", "state-speaking");
    btnMic.classList.remove("listening");

    switch (state.toLowerCase()) {
      case "listening":
        orbWrapper.classList.add("state-listening");
        btnMic.classList.add("listening");
        orbStatus.textContent = "LISTENING TO VOICE INPUT...";
        systemStateText.textContent = "VOICE LISTENING";
        systemStateBadge.className = "state-badge border-success text-success";
        break;

      case "thinking":
      case "processing":
        orbWrapper.classList.add("state-thinking");
        orbStatus.textContent = "PROCESSING COMMAND...";
        systemStateText.textContent = "THINKING";
        systemStateBadge.className = "state-badge border-warning text-warning";
        break;

      case "speaking":
        orbWrapper.classList.add("state-speaking");
        orbStatus.textContent = "JARVIS SPEAKING...";
        systemStateText.textContent = "SPEAKING";
        systemStateBadge.className = "state-badge border-info text-info";
        break;

      case "ready":
      default:
        orbStatus.textContent = "READY FOR COMMAND";
        systemStateText.textContent = "SYSTEM READY";
        systemStateBadge.className = "state-badge";
        break;
    }
  };

  /**
   * Populate command history list drawer.
   */
  window.updateCommandHistory = function (records) {
    if (!records || records.length === 0) {
      historyList.innerHTML = `<div class="text-center text-muted py-4">No recent commands recorded.</div>`;
      return;
    }

    historyList.innerHTML = records
      .map(
        (r) => `
        <div class="history-item">
          <div class="history-query"><i class="bi bi-chevron-right me-1 text-cyan"></i>${escapeHtml(r.query)}</div>
          <div class="history-response">${escapeHtml(r.response)}</div>
          <div class="history-ts">${escapeHtml(r.ts)}</div>
        </div>
      `
      )
      .join("");
  };

  /**
   * Populate contacts drawer list.
   */
  window.updateContactsList = function (contacts) {
    if (!contacts || contacts.length === 0) {
      contactsList.innerHTML = `<div class="text-center text-muted py-3">No contacts saved in database.</div>`;
      return;
    }

    contactsList.innerHTML = contacts
      .map(
        (c) => `
        <div class="contact-item">
          <div class="d-flex justify-content-between align-items-center">
            <strong class="text-light">${escapeHtml(c.name)}</strong>
            <span class="badge bg-secondary">${escapeHtml(c.phone)}</span>
          </div>
          ${c.email ? `<div class="text-muted small mt-1"><i class="bi bi-envelope me-1"></i>${escapeHtml(c.email)}</div>` : ""}
        </div>
      `
      )
      .join("");
  };

  // Expose methods to Eel namespace if eel is loaded
  if (typeof eel !== "undefined") {
    eel.expose(displayMessage, "displayMessage");
    eel.expose(setJarvisState, "setJarvisState");
    eel.expose(updateCommandHistory, "updateCommandHistory");
    eel.expose(updateContactsList, "updateContactsList");
  }

  // =========================================================================
  // User Actions and Event Listeners
  // =========================================================================

  // Submit typed command
  function submitCommand() {
    const text = txtCommand.value.trim();
    if (!text) return;

    // Display user bubble immediately
    displayMessage("user", text);
    txtCommand.value = "";
    setJarvisState("thinking");

    if (typeof eel !== "undefined" && eel.take_typed_command) {
      eel.take_typed_command(text)();
    } else {
      console.warn("Eel bridge is not active. Simulating local fallback.");
      setTimeout(() => {
        displayMessage("jarvis", `Simulated response for: "${text}"`);
        setJarvisState("ready");
      }, 600);
    }
  }

  // Trigger Voice Input
  function triggerVoice() {
    setJarvisState("listening");
    if (typeof eel !== "undefined" && eel.start_listening) {
      eel.start_listening()();
    } else {
      setTimeout(() => {
        setJarvisState("ready");
      }, 3000);
    }
  }

  // Event: Send Button Click
  btnSend.addEventListener("click", submitCommand);

  // Event: Enter Key in Input
  txtCommand.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      submitCommand();
    }
  });

  // Event: Mic Button Click
  btnMic.addEventListener("click", () => {
    triggerVoice();
  });

  // Global Keyboard Shortcut: Ctrl + J
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && (e.key === "j" || e.key === "J")) {
      e.preventDefault();
      triggerVoice();
    }
  });

  // Fetch History on drawer open or refresh button
  function loadHistory() {
    if (typeof eel !== "undefined" && eel.get_history) {
      eel.get_history()();
    }
  }

  btnRefreshHistory.addEventListener("click", loadHistory);
  document.getElementById("btnHistory").addEventListener("click", loadHistory);

  // Fetch Contacts on drawer open or refresh button
  function loadContacts() {
    if (typeof eel !== "undefined" && eel.get_contacts) {
      eel.get_contacts()();
    }
  }

  btnRefreshContacts.addEventListener("click", loadContacts);
  document.getElementById("btnContacts").addEventListener("click", loadContacts);

  // Add Contact Form Submit
  btnAddContact.addEventListener("click", () => {
    const nameInput = document.getElementById("contactName");
    const phoneInput = document.getElementById("contactPhone");
    const emailInput = document.getElementById("contactEmail");

    const name = nameInput.value.trim();
    const phone = phoneInput.value.trim();
    const email = emailInput.value.trim();

    if (!name || !phone) {
      alert("Please provide both Name and Phone Number.");
      return;
    }

    if (typeof eel !== "undefined" && eel.save_contact) {
      eel.save_contact(name, phone, email)();
      nameInput.value = "";
      phoneInput.value = "";
      emailInput.value = "";
      setTimeout(loadContacts, 300);
    }
  });

  // Helper: Escape HTML
  function escapeHtml(str) {
    if (typeof str !== "string") return str;
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
});
