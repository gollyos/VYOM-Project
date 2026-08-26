export type VyomState =
  | "Idle"
  | "Listening"
  | "Understanding"
  | "Thinking"
  | "Planning"
  | "Researching"
  | "Speaking"
  | "Interrupted"
  | "Executing"
  | "Verifying"
  | "WaitingApproval"
  | "Completed"
  | "Failed";

export type StateVisual = {
  description: string;
  color: string;
  secondary: string;
  energy: number;
  tempo: number;
  networkOpacity: number;
};

export const STATE_VISUALS: Record<VyomState, StateVisual> = {
  Idle: {
    description: "Presence online",
    color: "#79aaa8",
    secondary: "#315d61",
    energy: 0.28,
    tempo: 0.22,
    networkOpacity: 0.14,
  },
  Listening: {
    description: "Attention focused",
    color: "#9adbd5",
    secondary: "#4f8e91",
    energy: 0.72,
    tempo: 0.82,
    networkOpacity: 0.27,
  },
  Understanding: {
    description: "Intent resolving",
    color: "#7fc7d2",
    secondary: "#356c79",
    energy: 0.88,
    tempo: 1.28,
    networkOpacity: 0.33,
  },
  Thinking: {
    description: "Forming a response",
    color: "#78bdd0",
    secondary: "#315f78",
    energy: 0.92,
    tempo: 1.35,
    networkOpacity: 0.34,
  },
  Planning: {
    description: "Structuring the mission",
    color: "#82c5d0",
    secondary: "#396d78",
    energy: 0.9,
    tempo: 1.16,
    networkOpacity: 0.34,
  },
  Researching: {
    description: "Reading and cross-checking sources",
    color: "#7aa8d6",
    secondary: "#33517d",
    energy: 0.84,
    tempo: 1.08,
    networkOpacity: 0.32,
  },
  Speaking: {
    description: "Presenting clearly",
    color: "#b4e3dc",
    secondary: "#4f9290",
    energy: 0.78,
    tempo: 0.68,
    networkOpacity: 0.29,
  },
  Interrupted: {
    description: "Yielding attention",
    color: "#c3a06c",
    secondary: "#725832",
    energy: 0.94,
    tempo: 1.52,
    networkOpacity: 0.36,
  },
  Executing: {
    description: "Action in motion",
    color: "#7bc6d4",
    secondary: "#316b7a",
    energy: 1,
    tempo: 1.7,
    networkOpacity: 0.38,
  },
  Verifying: {
    description: "Checking completion",
    color: "#8dc4a4",
    secondary: "#3e715a",
    energy: 0.86,
    tempo: 1.02,
    networkOpacity: 0.31,
  },
  WaitingApproval: {
    description: "Permission required",
    color: "#c4a067",
    secondary: "#745b34",
    energy: 0.7,
    tempo: 0.46,
    networkOpacity: 0.27,
  },
  Completed: {
    description: "Verified completion",
    color: "#91c7a7",
    secondary: "#47765e",
    energy: 0.72,
    tempo: 0.58,
    networkOpacity: 0.29,
  },
  Failed: {
    description: "Result not completed",
    color: "#c17c72",
    secondary: "#75423d",
    energy: 0.62,
    tempo: 0.4,
    networkOpacity: 0.25,
  },
};

export type VyomIntent = "wake" | "status" | "plan" | "explain-model" | "agency" | "developer" | "close" | "stop" | "unknown";

export function resolveIntent(command: string): VyomIntent {
  const normalized = command.trim().toLowerCase().replace(/[?.!]+$/g, "");

  if (normalized === "vyom" || normalized === "hey vyom") return "wake";
  if (
    normalized === "what is my status today" ||
    normalized.includes("status today") ||
    normalized.includes("today's status")
  ) {
    return "status";
  }
  if (normalized.includes("plan my work") || normalized.includes("plan my day")) return "plan";
  if (normalized.includes("model you chose") || normalized.includes("explain model")) return "explain-model";
  if (normalized === "agency" || normalized.includes("show agency")) return "agency";
  if (normalized === "developer" || normalized.includes("show developer")) return "developer";
  if (normalized.includes("close everything") || normalized.includes("clear everything")) return "close";
  // Stop/cancel fast-path: these keywords bypass the full 1400ms
  // dispatch-settle timer and route directly to the backend's
  // kernel interrupt, which completes in <22ms with zero tokens.
  // Without this, a spoken "stop" paid the same latency tax as
  // any other sentence — the user had to wait over a second for
  // VYOM to stop doing something it shouldn't be doing at all.
  if (
    normalized === "stop" || normalized === "ruko" ||
    normalized === "bas" || normalized === "bas karo" ||
    normalized === "cancel" || normalized === "ruk" ||
    normalized === "theher" || normalized === "theher jao" ||
    normalized === "ruk jao" || normalized === "stop karo" ||
    normalized === "ruko ruko" || normalized === "bas bas"
  ) {
    return "stop";
  }
  return "unknown";
}
