/**
 * Records one hop of a user command to the Brain's trace log.
 *
 * The voice half of the command path lives inside the webview, where
 * nothing was observable from outside the running application - a broken
 * voice bus and a broken tool layer looked identical from the console.
 * Each hop posts a line keyed by one correlation id so the whole journey
 * (spoken words -> dispatch decision -> Brain task -> tool -> spoken
 * result) can be read back from a single file.
 *
 * Fire-and-forget and failure-tolerant: tracing must never change or
 * delay what the user asked for.
 */
const BRAIN_URL = (import.meta.env.VITE_VYOM_BRAIN_URL || "http://127.0.0.1:7788").replace(/\/$/, "");

export function newCorrelationId() {
  return `c_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export function trace(correlationId: string, stage: string, detail: Record<string, unknown> = {}) {
  try {
    void fetch(`${BRAIN_URL}/api/diagnostics/trace`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ correlation_id: correlationId, stage, detail }),
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    // Never let diagnostics break the command path.
  }
}
