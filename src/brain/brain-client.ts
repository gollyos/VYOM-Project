import type { BrainConnectionState, BrainEvent, BrainTask } from "./types";

const DEFAULT_BRAIN_URL = "http://127.0.0.1:7788";

function websocketUrl(httpUrl: string) {
  return `${httpUrl.replace(/^http/, "ws")}/ws/events`;
}

export class BrainClient {
  private readonly baseUrl: string;
  private socket: WebSocket | null = null;
  private reconnectTimer: number | null = null;
  private pingTimer: number | null = null;
  private reconnectAttempt = 0;
  private destroyed = false;
  // RECONNECT CURSOR. A disconnect used to silently drop every event the
  // Brain published while the UI was away - "task gayab" after a network
  // blip. The Brain's /ws/events?since= replays everything after the last
  // event this client saw; without the cursor that replay never runs.
  private lastEventId: string | null = null;
  private eventListeners = new Set<(event: BrainEvent) => void>();
  private connectionListeners = new Set<(state: BrainConnectionState) => void>();

  constructor(customUrl?: string) {
    this.baseUrl = (customUrl || (import.meta.env.VITE_VYOM_BRAIN_URL as string | undefined) || DEFAULT_BRAIN_URL).replace(/\/$/, "");
  }

  async health() {
    const response = await fetch(`${this.baseUrl}/health`, { signal: AbortSignal.timeout(5000) });
    if (!response.ok) throw new Error("Brain health check failed");
    return response.json() as Promise<{ status: string; service: string }>;
  }

  async createTask(userRequest: string) {
    const response = await fetch(`${this.baseUrl}/api/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_request: userRequest }),
    });
    if (!response.ok) throw new Error(`Brain rejected the task (${response.status})`);
    return response.json() as Promise<BrainTask>;
  }

  async decideApproval(taskId: string, approved: boolean) {
    const response = await fetch(`${this.baseUrl}/api/approvals/${taskId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    });
    if (!response.ok) throw new Error(`Approval update failed (${response.status})`);
    return response.json() as Promise<BrainTask>;
  }

  async cancelTask(taskId: string) {
    const response = await fetch(`${this.baseUrl}/api/tasks/${taskId}/cancel`, { method: "POST" });
    if (!response.ok) throw new Error(`Task cancellation failed (${response.status})`);
    return response.json() as Promise<BrainTask>;
  }

  async emergencyPause() {
    const response = await fetch(`${this.baseUrl}/api/desktop/emergency-pause`, { method: "POST" });
    if (!response.ok) throw new Error(`Emergency pause failed (${response.status})`);
    return response.json() as Promise<{ paused: boolean; cancelled_tasks: string[] }>;
  }

  async pauseAllAutomations() {
    const response = await fetch(`${this.baseUrl}/api/desktop/automations/pause-all`, { method: "POST" });
    if (!response.ok) throw new Error(`Pause automations failed (${response.status})`);
    return response.json() as Promise<{ paused: string[] }>;
  }

  async resumeAllAutomations() {
    const response = await fetch(`${this.baseUrl}/api/desktop/automations/resume-all`, { method: "POST" });
    if (!response.ok) throw new Error(`Resume automations failed (${response.status})`);
    return response.json() as Promise<{ resumed: string[] }>;
  }

  subscribe(
    onEvent: (event: BrainEvent) => void,
    onConnection: (state: BrainConnectionState) => void,
  ) {
    this.eventListeners.add(onEvent);
    this.connectionListeners.add(onConnection);
    this.connect();
    return () => {
      this.eventListeners.delete(onEvent);
      this.connectionListeners.delete(onConnection);
    };
  }

  destroy() {
    this.destroyed = true;
    if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer);
    if (this.pingTimer) window.clearInterval(this.pingTimer);
    this.socket?.close();
    this.socket = null;
    this.eventListeners.clear();
    this.connectionListeners.clear();
  }

  // Immediate reconnect attempt when the socket is down. The runtime's
  // offline health-poll calls this the moment /health answers, so a Brain
  // that came back (slow cold boot, Tauri supervisor respawn) is picked up
  // within one poll interval instead of the next backoff tick.
  retryNow() {
    if (this.destroyed) return;
    if (this.socket?.readyState === WebSocket.OPEN || this.socket?.readyState === WebSocket.CONNECTING) return;
    if (this.reconnectTimer) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.connect();
  }

  private emitConnection(state: BrainConnectionState) {
    this.connectionListeners.forEach((listener) => listener(state));
  }

  private connect() {
    if (this.destroyed || this.socket?.readyState === WebSocket.OPEN || this.socket?.readyState === WebSocket.CONNECTING) return;
    this.emitConnection(this.reconnectAttempt ? "reconnecting" : "connecting");
    const url = this.lastEventId
      ? `${websocketUrl(this.baseUrl)}?since=${encodeURIComponent(this.lastEventId)}`
      : websocketUrl(this.baseUrl);
    const socket = new WebSocket(url);
    this.socket = socket;
    socket.onopen = () => {
      this.reconnectAttempt = 0;
      this.emitConnection("online");
      if (this.pingTimer) window.clearInterval(this.pingTimer);
      this.pingTimer = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          try {
            socket.send("ping");
          } catch {
            // best-effort
          }
        }
      }, 15000);
    };
    socket.onmessage = (message) => {
      try {
        const raw = String(message.data);
        if (raw === "pong") return;
        const event = JSON.parse(raw) as BrainEvent & { type?: string };
        if (event.type === "heartbeat") return;
        if (event.schema_version === 1) {
          if (event.event_id) this.lastEventId = event.event_id;
          this.eventListeners.forEach((listener) => listener(event));
        }
      } catch {
        // Ignore invalid or future protocol messages without destabilizing the visual runtime.
      }
    };
    socket.onerror = () => socket.close();
    socket.onclose = () => {
      if (this.pingTimer) {
        window.clearInterval(this.pingTimer);
        this.pingTimer = null;
      }
      if (this.socket === socket) this.socket = null;
      if (this.destroyed) return;
      this.emitConnection("offline");
      this.reconnectAttempt += 1;
      const delay = Math.min(650 * this.reconnectAttempt, 5_000);
      this.reconnectTimer = window.setTimeout(() => {
        this.reconnectTimer = null;
        this.connect();
      }, delay);
    };
  }
}

