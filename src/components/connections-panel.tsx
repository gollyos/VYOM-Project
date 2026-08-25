import { FormEvent, useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Link2, Loader2, Mail, MessageCircle, PlayCircle, Search, Send } from "lucide-react";

const BRAIN = (import.meta.env.VITE_VYOM_BRAIN_URL as string | undefined) ?? "http://127.0.0.1:7788";

function apiBase() {
  return BRAIN.replace(/\/$/, "");
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, { signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error(`GET ${path} failed (${response.status})`);
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(30000),
  });
  const text = await response.text();
  let payload: unknown = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { raw: text };
  }
  if (!response.ok) {
    const detail = (payload as { detail?: string } | null)?.detail || `${path} failed (${response.status})`;
    throw new Error(String(detail));
  }
  return payload as T;
}

/* ------------------------------------------------------------------ *
 * Gmail — email + 16-digit App Password
 * ------------------------------------------------------------------ */

function GmailCard() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [address, setAddress] = useState("");
  const [appPassword, setAppPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const checkStatus = useCallback(async () => {
    try {
      const status = await getJson<{ connected: boolean }>("/api/email/app-password/status");
      setConnected(status.connected);
    } catch {
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    void checkStatus();
  }, [checkStatus]);

  async function connect(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await postJson("/api/email/app-password/connect", { address, app_password: appPassword });
      setAppPassword("");
      await checkStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect Gmail");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setError(null);
    try {
      await postJson("/api/email/app-password/disconnect");
      await checkStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect Gmail");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="cap-card conn-card" aria-label="Gmail connection">
      <header className="cap-card-header">
        <span className="cap-card-icon conn-icon-gmail">
          <Mail size={14} />
        </span>
        <div>
          <h4>Gmail</h4>
          <p>Send and read email — connect with your address and a 16-digit App Password.</p>
        </div>
        <span className={`cap-status-dot ${connected ? "cap-status-connected" : "cap-status-disconnected"}`} />
      </header>

      {error && (
        <p className="cap-error">
          <AlertCircle size={11} /> {error}
        </p>
      )}

      {connected ? (
        <div className="conn-connected-row">
          <CheckCircle2 size={13} />
          <span>Connected</span>
          <button type="button" className="cap-mini cap-mini-danger" onClick={() => void disconnect()} disabled={busy}>
            Disconnect
          </button>
        </div>
      ) : (
        <form className="conn-form" onSubmit={connect}>
          <div className="cap-input-wrap">
            <input
              value={address}
              onChange={(event) => setAddress(event.target.value)}
              placeholder="you@gmail.com"
              type="email"
              required
              aria-label="Gmail address"
            />
          </div>
          <div className="cap-input-wrap">
            <input
              value={appPassword}
              onChange={(event) => setAppPassword(event.target.value)}
              placeholder="16-digit App Password"
              type="password"
              required
              aria-label="Gmail App Password"
            />
          </div>
          <a
            className="conn-guide-link"
            href="https://myaccount.google.com/apppasswords"
            target="_blank"
            rel="noreferrer"
          >
            <Link2 size={11} /> Get an App Password from Google
          </a>
          <button className="cap-primary" type="submit" disabled={busy || !address.trim() || !appPassword.trim()}>
            {busy ? <Loader2 size={12} className="cap-spin" /> : "Connect Gmail"}
          </button>
        </form>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ *
 * Telegram — bot token, then a real scannable t.me QR
 * ------------------------------------------------------------------ */

function TelegramCard() {
  const [botToken, setBotToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connectInfo, setConnectInfo] = useState<{ bot_username: string; connect_url: string; qr_code_data_url: string } | null>(null);

  const loadConnectInfo = useCallback(async () => {
    try {
      const info = await getJson<{ bot_username: string; connect_url: string; qr_code_data_url: string }>("/api/telegram/connect");
      setConnectInfo(info);
    } catch {
      setConnectInfo(null);
    }
  }, []);

  useEffect(() => {
    void loadConnectInfo();
  }, [loadConnectInfo]);

  async function connectToken(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await postJson("/api/telegram/connect-token", { bot_token: botToken });
      setBotToken("");
      setError("Bot token verified. Restart VYOM's Brain to activate it, then this QR code will appear.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect Telegram bot token");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="cap-card conn-card" aria-label="Telegram connection">
      <header className="cap-card-header">
        <span className="cap-card-icon conn-icon-telegram">
          <Send size={14} />
        </span>
        <div>
          <h4>Telegram</h4>
          <p>A real bot VYOM sends/receives messages through — paste a @BotFather token once.</p>
        </div>
        <span className={`cap-status-dot ${connectInfo ? "cap-status-connected" : "cap-status-disconnected"}`} />
      </header>

      {error && (
        <p className="cap-error">
          <AlertCircle size={11} /> {error}
        </p>
      )}

      {connectInfo ? (
        <div className="conn-qr-wrap">
          <img src={connectInfo.qr_code_data_url} alt="Scan to open the VYOM Telegram bot" className="conn-qr-image" />
          <p className="cap-muted">
            Scan with your phone, or open <a href={connectInfo.connect_url} target="_blank" rel="noreferrer">@{connectInfo.bot_username}</a> directly,
            then send it any message to finish linking.
          </p>
        </div>
      ) : (
        <form className="conn-form" onSubmit={connectToken}>
          <div className="cap-input-wrap">
            <input
              value={botToken}
              onChange={(event) => setBotToken(event.target.value)}
              placeholder="Bot token from @BotFather"
              type="password"
              required
              aria-label="Telegram bot token"
            />
          </div>
          <a className="conn-guide-link" href="https://t.me/BotFather" target="_blank" rel="noreferrer">
            <Link2 size={11} /> Create a bot with @BotFather
          </a>
          <button className="cap-primary" type="submit" disabled={busy || !botToken.trim()}>
            {busy ? <Loader2 size={12} className="cap-spin" /> : "Connect Telegram Bot"}
          </button>
        </form>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ *
 * WhatsApp — real whatsapp-web.js QR-scan connect
 * ------------------------------------------------------------------ */

type WhatsAppStatus = {
  state: string; // disconnected | starting | qr_pending | authenticated | ready | auth_failure
  qr_data_url: string | null;
  pushname: string | null;
  wid: string | null;
  detail: string | null;
};

function WhatsAppCard() {
  const [status, setStatus] = useState<WhatsAppStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const poll = useCallback(async () => {
    try {
      const result = await getJson<WhatsAppStatus>("/api/whatsapp/status");
      setStatus(result);
    } catch {
      /* leave the last known status showing rather than flicker to null */
    }
  }, []);

  useEffect(() => {
    void poll();
    const interval = window.setInterval(() => void poll(), 3000);
    return () => window.clearInterval(interval);
  }, [poll]);

  async function connect() {
    setBusy(true);
    setError(null);
    try {
      await postJson<WhatsAppStatus>("/api/whatsapp/connect");
      await poll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start WhatsApp connect");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setError(null);
    try {
      await postJson("/api/whatsapp/disconnect");
      await poll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect WhatsApp");
    } finally {
      setBusy(false);
    }
  }

  const state = status?.state ?? "disconnected";
  const isReady = state === "ready";
  const isQrPending = state === "qr_pending" && status?.qr_data_url;

  return (
    <section className="cap-card conn-card" aria-label="WhatsApp connection">
      <header className="cap-card-header">
        <span className="cap-card-icon conn-icon-whatsapp">
          <MessageCircle size={14} />
        </span>
        <div>
          <h4>WhatsApp</h4>
          <p>Real WhatsApp Web session — scan the QR with your phone, same as web.whatsapp.com.</p>
        </div>
        <span className={`cap-status-dot ${isReady ? "cap-status-connected" : state === "auth_failure" ? "cap-status-error" : "cap-status-disconnected"}`} />
      </header>

      {error && (
        <p className="cap-error">
          <AlertCircle size={11} /> {error}
        </p>
      )}

      {isReady ? (
        <div className="conn-connected-row">
          <CheckCircle2 size={13} />
          <span>Connected{status?.pushname ? ` as ${status.pushname}` : ""}</span>
          <button type="button" className="cap-mini cap-mini-danger" onClick={() => void disconnect()} disabled={busy}>
            Disconnect
          </button>
        </div>
      ) : isQrPending ? (
        <div className="conn-qr-wrap">
          <img src={status!.qr_data_url!} alt="Scan with WhatsApp to link this device" className="conn-qr-image" />
          <p className="cap-muted">Open WhatsApp on your phone → Linked Devices → Link a Device → scan this code.</p>
        </div>
      ) : (
        <div className="conn-form">
          {state === "starting" && (
            <p className="cap-muted">
              <Loader2 size={12} className="cap-spin" /> Starting WhatsApp Web session — generating your QR code…
            </p>
          )}
          {state === "auth_failure" && status?.detail && (
            <p className="cap-error">
              <AlertCircle size={11} /> {status.detail}
            </p>
          )}
          <button className="cap-primary" type="button" onClick={() => void connect()} disabled={busy || state === "starting"}>
            {busy ? <Loader2 size={12} className="cap-spin" /> : "Connect WhatsApp"}
          </button>
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ *
 * YouTube — OAuth (opens Google's consent screen in a new tab)
 * ------------------------------------------------------------------ */

function YouTubeCard() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  const checkStatus = useCallback(async () => {
    try {
      const records = await getJson<Array<{ id: string; status: string }>>("/api/integrations");
      const record = records.find((entry) => entry.id === "youtube");
      setConnected(record?.status === "connected");
    } catch {
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    void checkStatus();
  }, [checkStatus]);

  async function startOAuth() {
    setError(null);
    try {
      const start = await postJson<{ authorization_url: string }>("/api/integrations/youtube/oauth/start");
      window.open(start.authorization_url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start YouTube connect (Google OAuth client not configured)");
    }
  }

  return (
    <section className="cap-card conn-card" aria-label="YouTube connection">
      <header className="cap-card-header">
        <span className="cap-card-icon conn-icon-youtube">
          <PlayCircle size={14} />
        </span>
        <div>
          <h4>YouTube</h4>
          <p>Upload videos VYOM creates directly to your channel.</p>
        </div>
        <span className={`cap-status-dot ${connected ? "cap-status-connected" : "cap-status-disconnected"}`} />
      </header>

      {error && (
        <p className="cap-error">
          <AlertCircle size={11} /> {error}
        </p>
      )}

      {connected ? (
        <div className="conn-connected-row">
          <CheckCircle2 size={13} />
          <span>Connected</span>
        </div>
      ) : (
        <div className="conn-form">
          <button className="cap-primary" type="button" onClick={() => void startOAuth()}>
            Connect with Google
          </button>
          <p className="cap-muted">Opens Google's real sign-in in a new tab — grant access, then come back and refresh.</p>
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ *
 * SerpAPI — real Google search results, key paste
 * ------------------------------------------------------------------ */

function SerpApiCard() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const checkStatus = useCallback(async () => {
    try {
      const status = await getJson<{ connected: boolean }>("/api/search/serpapi/status");
      setConnected(status.connected);
    } catch {
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    void checkStatus();
  }, [checkStatus]);

  async function connect(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await postJson<{ status: string; note: string }>("/api/search/serpapi/connect", { api_key: apiKey });
      setApiKey("");
      setError(result.note);
      await checkStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect SerpAPI");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setError(null);
    try {
      await postJson("/api/search/serpapi/disconnect");
      await checkStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect SerpAPI");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="cap-card conn-card" aria-label="SerpAPI connection">
      <header className="cap-card-header">
        <span className="cap-card-icon conn-icon-serpapi">
          <Search size={14} />
        </span>
        <div>
          <h4>SerpAPI</h4>
          <p>Real Google search results for VYOM's research — faster and more reliable than page scraping.</p>
        </div>
        <span className={`cap-status-dot ${connected ? "cap-status-connected" : "cap-status-disconnected"}`} />
      </header>

      {error && (
        <p className="cap-error">
          <AlertCircle size={11} /> {error}
        </p>
      )}

      {connected ? (
        <div className="conn-connected-row">
          <CheckCircle2 size={13} />
          <span>Connected</span>
          <button type="button" className="cap-mini cap-mini-danger" onClick={() => void disconnect()} disabled={busy}>
            Disconnect
          </button>
        </div>
      ) : (
        <form className="conn-form" onSubmit={connect}>
          <div className="cap-input-wrap">
            <input
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="SerpAPI key"
              type="password"
              required
              aria-label="SerpAPI key"
            />
          </div>
          <a className="conn-guide-link" href="https://serpapi.com/manage-api-key" target="_blank" rel="noreferrer">
            <Link2 size={11} /> Get a key from SerpAPI
          </a>
          <button className="cap-primary" type="submit" disabled={busy || !apiKey.trim()}>
            {busy ? <Loader2 size={12} className="cap-spin" /> : "Connect SerpAPI"}
          </button>
        </form>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ *
 * Social token cards — Discord / Twitter / LinkedIn / Facebook
 * All four connect the same way: paste a token, VYOM verifies it with a
 * real health() call before saving. Generic one component for all four.
 * ------------------------------------------------------------------ */

type SocialSpec = {
  id: string;
  label: string;
  icon: React.ReactNode;
  tokenLabel: string;
  tokenPlaceholder: string;
  guideHref: string;
  guideText: string;
  description: string;
};

function SocialTokenCard({ spec }: { spec: SocialSpec }) {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const checkStatus = useCallback(async () => {
    try {
      const status = await getJson<{ connected: boolean }>(`/api/${spec.id}/status`);
      setConnected(status.connected);
    } catch {
      setConnected(false);
    }
  }, [spec.id]);

  useEffect(() => {
    void checkStatus();
  }, [checkStatus]);

  async function connect(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const endpoint =
        spec.id === "twitter"
          ? "/api/twitter/connect"
          : spec.id === "linkedin"
            ? "/api/linkedin/connect"
            : spec.id === "facebook"
              ? "/api/facebook/connect"
              : "/api/discord/connect";
      const body =
        spec.id === "twitter" || spec.id === "linkedin"
          ? { access_token: token }
          : spec.id === "facebook"
            ? { page_id: "100000000000000", access_token: token } // page_id overridden below
            : { bot_token: token };
      // Facebook needs a real page_id, not a placeholder; prompt for it.
      let payload = body;
      if (spec.id === "facebook") {
        const pageId = window.prompt("Your Facebook PAGE id (a number):");
        if (!pageId) {
          setError("Page id is required to connect Facebook.");
          setBusy(false);
          return;
        }
        payload = { page_id: pageId, access_token: token };
      }
      await postJson(endpoint, payload);
      setToken("");
      await checkStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Could not connect ${spec.label}`);
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setError(null);
    try {
      await postJson(`/api/${spec.id}/disconnect`);
      await checkStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Could not disconnect ${spec.label}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="cap-card conn-card" aria-label={`${spec.label} connection`}>
      <header className="cap-card-header">
        <span className={`cap-card-icon conn-icon-${spec.id}`}>{spec.icon}</span>
        <div>
          <h4>{spec.label}</h4>
          <p>{spec.description}</p>
        </div>
        <span className={`cap-status-dot ${connected ? "cap-status-connected" : "cap-status-disconnected"}`} />
      </header>

      {error && (
        <p className="cap-error">
          <AlertCircle size={11} /> {error}
        </p>
      )}

      {connected ? (
        <div className="conn-connected-row">
          <CheckCircle2 size={13} />
          <span>Connected</span>
          <button type="button" className="cap-mini cap-mini-danger" onClick={() => void disconnect()} disabled={busy}>
            Disconnect
          </button>
        </div>
      ) : (
        <form className="conn-form" onSubmit={connect}>
          <div className="cap-input-wrap">
            <input
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder={spec.tokenPlaceholder}
              type="password"
              required
              aria-label={`${spec.label} ${spec.tokenLabel}`}
            />
          </div>
          <a className="conn-guide-link" href={spec.guideHref} target="_blank" rel="noreferrer">
            <Link2 size={11} /> {spec.guideText}
          </a>
          <button className="cap-primary" type="submit" disabled={busy || !token.trim()}>
            {busy ? <Loader2 size={12} className="cap-spin" /> : `Connect ${spec.label}`}
          </button>
        </form>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ *
 * Instagram — token connect + a post action (image/reel/story)
 * ------------------------------------------------------------------ */

function InstagramCard() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [accountId, setAccountId] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [postInfo, setPostInfo] = useState<string | null>(null);

  const checkStatus = useCallback(async () => {
    try {
      const status = await getJson<{ connected: boolean }>("/api/instagram/status");
      setConnected(status.connected);
    } catch {
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    void checkStatus();
  }, [checkStatus]);

  async function connect(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await postJson("/api/instagram/connect", {
        instagram_business_account_id: accountId,
        access_token: accessToken,
      });
      setAccessToken("");
      await checkStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect Instagram");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setError(null);
    try {
      await postJson("/api/instagram/disconnect");
      await checkStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect Instagram");
    } finally {
      setBusy(false);
    }
  }

  async function testPost() {
    setBusy(true);
    setError(null);
    setPostInfo(null);
    try {
      const mediaUrl = window.prompt("Public https media URL (Instagram fetches it itself):");
      if (!mediaUrl) return;
      const caption = window.prompt("Caption:") ?? "";
      await postJson("/api/instagram/post", { media_url: mediaUrl, media_type: "IMAGE", caption });
      setPostInfo("Test post published — check your Instagram account.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not post to Instagram");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="cap-card conn-card" aria-label="Instagram connection">
      <header className="cap-card-header">
        <span className="cap-card-icon conn-icon-instagram">
          <InstagramIcon />
        </span>
        <div>
          <h4>Instagram</h4>
          <p>Post images/reels/stories and send DMs — connect your IG Business account.</p>
        </div>
        <span className={`cap-status-dot ${connected ? "cap-status-connected" : "cap-status-disconnected"}`} />
      </header>

      {error && (
        <p className="cap-error">
          <AlertCircle size={11} /> {error}
        </p>
      )}

      {connected ? (
        <div className="conn-connected-row">
          <CheckCircle2 size={13} />
          <span>Connected</span>
          <button type="button" className="cap-mini" onClick={() => void testPost()} disabled={busy}>
            Test Post
          </button>
          <button type="button" className="cap-mini cap-mini-danger" onClick={() => void disconnect()} disabled={busy}>
            Disconnect
          </button>
        </div>
      ) : (
        <form className="conn-form" onSubmit={connect}>
          <div className="cap-input-wrap">
            <input
              value={accountId}
              onChange={(event) => setAccountId(event.target.value)}
              placeholder="IG Business Account ID"
              required
              aria-label="Instagram Business Account ID"
            />
          </div>
          <div className="cap-input-wrap">
            <input
              value={accessToken}
              onChange={(event) => setAccessToken(event.target.value)}
              placeholder="Long-lived Page access token"
              type="password"
              required
              aria-label="Instagram access token"
            />
          </div>
          <button className="cap-primary" type="submit" disabled={busy || !accountId.trim() || !accessToken.trim()}>
            {busy ? <Loader2 size={12} className="cap-spin" /> : "Connect Instagram"}
          </button>
        </form>
      )}
    </section>
  );
}

function InstagramIcon() {
  return (
    <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="2" y="2" width="20" height="20" rx="5" ry="5" />
      <path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z" />
      <line x1="17.5" y1="6.5" x2="17.51" y2="6.5" />
    </svg>
  );
}


export function ConnectionsPanel() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className={`cap-toggle conn-toggle ${open ? "cap-toggle-active" : ""}`}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label="Toggle Connect Your Accounts panel"
      >
        <Link2 size={13} />
        <span>Connect Accounts</span>
        {open && <span className="cap-toggle-count" />}
      </button>

      {open && (
        <aside className="cap-drawer conn-drawer" role="dialog" aria-modal="false" aria-label="Connect your accounts">
          <header className="cap-drawer-header">
            <div className="cap-drawer-title">
              <Link2 size={14} />
              <div>
                <h3>Connect Your Accounts</h3>
                <p>Paste your own credentials — VYOM verifies each one live before saving it.</p>
              </div>
            </div>
            <div className="cap-drawer-actions">
              <button type="button" className="cap-icon-button" onClick={() => setOpen(false)} aria-label="Close">
                ✕
              </button>
            </div>
          </header>

          <div className="cap-drawer-body">
            <GmailCard />
            <TelegramCard />
            <WhatsAppCard />
            <YouTubeCard />
            <SerpApiCard />
            <SocialTokenCard
              spec={{
                id: "discord",
                label: "Discord",
                icon: <MessageCircle size={14} />,
                tokenLabel: "bot token",
                tokenPlaceholder: "Bot token from the Developer Portal",
                guideHref: "https://discord.com/developers/applications",
                guideText: "Create a bot in the Discord Developer Portal",
                description: "Send messages to a server VYOM's bot is in.",
              }}
            />
            <SocialTokenCard
              spec={{
                id: "twitter",
                label: "Twitter / X",
                icon: <Send size={14} />,
                tokenLabel: "access token",
                tokenPlaceholder: "OAuth 2.0 User Context access token",
                guideHref: "https://developer.x.com/en/portal",
                guideText: "Get a token from the X Developer Portal",
                description: "Post tweets, up to 280 characters.",
              }}
            />
            <SocialTokenCard
              spec={{
                id: "linkedin",
                label: "LinkedIn",
                icon: <Send size={14} />,
                tokenLabel: "access token",
                tokenPlaceholder: "OAuth 2.0 access token",
                guideHref: "https://www.linkedin.com/developers/",
                guideText: "Create an app in the LinkedIn Developers portal",
                description: "Post text updates to your LinkedIn feed.",
              }}
            />
            <SocialTokenCard
              spec={{
                id: "facebook",
                label: "Facebook",
                icon: <MessageCircle size={14} />,
                tokenLabel: "Page access token",
                tokenPlaceholder: "Long-lived Page access token",
                guideHref: "https://developers.facebook.com/tools/explorer/",
                guideText: "Get a Page token from the Graph API Explorer",
                description: "Post text, links, and photos to your Facebook Page.",
              }}
            />
            <InstagramCard />
          </div>
        </aside>
      )}
    </>
  );
}
