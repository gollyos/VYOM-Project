import { Minus, Square, X } from "lucide-react";

/**
 * Custom window chrome for VYOM's `decorations: false` window (see
 * src-tauri/tauri.conf.json). With OS decorations off, there is no
 * native minimize/maximize/close anywhere - these three buttons are the
 * ONLY way for the user to control the window, so this is not
 * cosmetic. Calls the Rust commands directly (desktop.rs) rather than
 * the generic @tauri-apps/api/window minimize()/close(), matching how
 * the rest of the app already talks to the window (see
 * minimize_vyom_window / restore_vyom_window usage elsewhere).
 */
export function WindowControls() {
  async function invoke(command: string) {
    try {
      const { invoke: tauriInvoke } = await import("@tauri-apps/api/core");
      await tauriInvoke(command);
    } catch (error) {
      console.error(`[window-controls] ${command} failed`, error);
    }
  }

  return (
    <div className="window-controls" aria-label="Window controls">
      <button
        type="button"
        className="window-control window-control-minimize"
        onClick={() => void invoke("minimize_vyom_window")}
        aria-label="Minimize"
        title="Minimize"
      >
        <Minus size={13} />
      </button>
      <button
        type="button"
        className="window-control window-control-maximize"
        onClick={() => void invoke("toggle_maximize_vyom_window")}
        aria-label="Maximize / Restore"
        title="Maximize / Restore"
      >
        <Square size={11} />
      </button>
      <button
        type="button"
        className="window-control window-control-close"
        onClick={() => void invoke("close_vyom_window")}
        aria-label="Close"
        title="Close"
      >
        <X size={14} />
      </button>
    </div>
  );
}
