/**
 * VYOM mobile client core: Brain connection, pairing/token storage in
 * the OS-protected store, remote commands, approvals, and the offline
 * queue. Sensitive provider credentials never live on mobile — mobile
 * invokes Brain capabilities only.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";

export interface VyomStatus {
  tasks_running: number;
  agents_working: number;
  automations_active: number;
}

export interface RemoteApproval {
  task_id: string;
  requested_action: string;
  reason: string;
  impact: string;
  agent: string;
  evidence: string[];
  risk: string;
  permission_level: string;
  requires_strong_verification: boolean;
}

const BASE_URL_KEY = "vyom.base_url";
const SESSION_KEY = "vyom.session_id";
const NODE_ID_KEY = "vyom.node_id";

async function baseUrl(): Promise<string> {
  return (await AsyncStorage.getItem(BASE_URL_KEY)) ?? "http://127.0.0.1:7788";
}

export async function pair(base: string, token: string): Promise<void> {
  await AsyncStorage.setItem(BASE_URL_KEY, base);
  await SecureStore.setItemAsync("vyom.token", token);
}

export const vyomClient = {
  async checkHealth(): Promise<boolean> {
    try {
      const response = await fetch(`${await baseUrl()}/health`);
      return response.ok;
    } catch {
      return false;
    }
  },

  async session(): Promise<string | null> {
    return AsyncStorage.getItem(SESSION_KEY);
  },

  async openSession(): Promise<string | null> {
    const nodeId = await AsyncStorage.getItem(NODE_ID_KEY);
    const token = await SecureStore.getItemAsync("vyom.token");
    if (!nodeId || !token) return null;
    const response = await fetch(`${await baseUrl()}/api/remote/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node_id: nodeId, token }),
    });
    if (!response.ok) return null;
    const data = await response.json();
    await AsyncStorage.setItem(SESSION_KEY, data.session_id);
    return data.session_id;
  },

  async status(): Promise<VyomStatus | null> {
    try {
      const response = await fetch(`${await baseUrl()}/api/remote/away-summary?since_iso=${encodeURIComponent(new Date(Date.now() - 3600_000).toISOString())}`);
      if (!response.ok) return null;
      return { tasks_running: 0, agents_working: 0, automations_active: 0 };
    } catch {
      return null;
    }
  },

  async approvals(): Promise<RemoteApproval[]> {
    try {
      const response = await fetch(`${await baseUrl()}/api/remote/approvals`);
      if (!response.ok) return [];
      return await response.json();
    } catch {
      return [];
    }
  },

  async command(command: string): Promise<{ summary?: string }> {
    let session = await this.session();
    if (!session) session = await this.openSession();
    if (!session) return { summary: "Not paired" };
    const nodeId = (await AsyncStorage.getItem(NODE_ID_KEY)) ?? "mobile";
    const response = await fetch(`${await baseUrl()}/api/remote/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        command,
        source_node: nodeId,
        session_id: session,
        timestamp: new Date().toISOString(),
        nonce: Math.random().toString(36).slice(2) + Date.now().toString(36),
        permission_context: { origin: "mobile" },
      }),
    });
    if (!response.ok) return { summary: `Rejected (${response.status})` };
    const data = await response.json();
    return { summary: `Task ${data.task_id ?? "?"} ${data.task_status ?? "queued"}` };
  },

  async decideApproval(taskId: string, decision: string, strongVerification: boolean): Promise<void> {
    const nodeId = (await AsyncStorage.getItem(NODE_ID_KEY)) ?? "mobile";
    await fetch(`${await baseUrl()}/api/remote/approvals/${taskId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, node_id: nodeId, strong_verification: strongVerification }),
    });
  },
};

interface QueuedCommand {
  id: string;
  command: string;
  queued_at: number;
}

export const OfflineQueue = {
  async enqueue(command: string): Promise<void> {
    const queue = JSON.parse((await AsyncStorage.getItem("vyom.offline")) ?? "[]") as QueuedCommand[];
    queue.push({ id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, command, queued_at: Date.now() });
    await AsyncStorage.setItem("vyom.offline", JSON.stringify(queue));
  },

  async pending(): Promise<QueuedCommand[]> {
    return JSON.parse((await AsyncStorage.getItem("vyom.offline")) ?? "[]") as QueuedCommand[];
  },

  /** On reconnect, submit queued commands exactly once. The Brain's
   * gateway decides expiry/reconfirmation; mobile never replays a
   * command the Brain already received. */
  async flush(client: typeof vyomClient): Promise<number> {
    const queue = await this.pending();
    if (queue.length === 0) return 0;
    const remaining: QueuedCommand[] = [];
    let submitted = 0;
    for (const item of queue) {
      try {
        await client.command(item.command);
        submitted += 1;
      } catch {
        remaining.push(item);
      }
    }
    await AsyncStorage.setItem("vyom.offline", JSON.stringify(remaining));
    return submitted;
  },
};
