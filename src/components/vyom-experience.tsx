import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, ArrowUp, Mic, MicOff, RotateCw } from "lucide-react";
import { BrandMark } from "./brand-mark";
import { NeuralBiome } from "./neural-biome";
import { OnboardingOverlay } from "./onboarding-overlay";
import { UIComposer } from "@/composer/ui-composer";
import { AgentStackPanel } from "./agent-stack-panel";
import { ConnectionsPanel } from "./connections-panel";
import { WindowControls } from "./window-controls";
import { newCorrelationId, trace } from "@/core/trace";
import { STATE_VISUALS } from "@/core/vyom-state";
import { useVyomRuntime } from "@/core/use-vyom-runtime";
import { useVoiceRuntime } from "@/voice/use-voice-runtime";

const commandSuggestions = [
  "What is my status today?",
  "Analyze NVDA",
  "What should I do today?",
  "How are my habits going?",
  "What needs approval?",
  "Close everything",
];
const voiceBars = [5, 11, 17, 8, 23, 13, 19, 7, 16, 10, 21, 9, 15, 6, 12];

export function VyomExperience() {
  const [query, setQuery] = useState("");
  const [time, setTime] = useState("");
  const [needsOnboarding, setNeedsOnboarding] = useState(false);
  const {
    state: composerState,
    response,
    operationalMessage,
    lastCommand,
    busy,
    composition,
    visibleObjectIds,
    composerPhase,
    brainConnection,
    activeTaskId,
    terminalEventKey,
    approval,
    runCommand,
    decideApproval,
    cancelActiveTask,
  } = useVyomRuntime();
  const voice = useVoiceRuntime({ onCommand: runCommand });

  // What the user HEARS is the Brain's verified result. Previously the
  // conversational voice model answered on its own, so the spoken reply
  // had no relationship to whether any tool actually ran.
  // -- build / runtime identity (diagnostics, not a dashboard) ----------
  // Answers "are we both looking at the same application?" from inside the
  // running window: build id, mode, Brain status and live registry counts.
  const [runtimeInfo, setRuntimeInfo] = useState<{
    brain: string; tools: number; skills: number; capabilities: number; model: string;
  } | null>(null);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const base = import.meta.env.VITE_VYOM_BRAIN_URL || "http://127.0.0.1:7788";
        const [tools, skills, capabilities, models] = await Promise.all([
          fetch(`${base}/api/tools`).then((r) => r.json()).catch(() => []),
          fetch(`${base}/api/skills`).then((r) => r.json()).catch(() => []),
          fetch(`${base}/api/capabilities`).then((r) => r.json()).catch(() => []),
          fetch(`${base}/api/models`).then((r) => r.json()).catch(() => ({ models: [] })),
        ]);
        if (cancelled) return;
        const enabled = (models.models ?? []).filter((m: { model_id?: string }) => m.model_id);
        setRuntimeInfo({
          brain: base,
          tools: Array.isArray(tools) ? tools.length : 0,
          skills: Array.isArray(skills) ? skills.length : 0,
          capabilities: Array.isArray(capabilities)
            ? capabilities.filter((c: { status?: string }) => c.status === "available").length
            : 0,
          model: enabled[0]?.model_id ?? "none configured",
        });
      } catch {
        // Diagnostics are best-effort and never block the experience.
      }
    })();
    return () => { cancelled = true; };
  }, [brainConnection]);

  const diagnostics = useMemo(() => {
    const mode = import.meta.env.DEV ? "DEV" : "RELEASE";
    const build = (import.meta.env.VITE_VYOM_BUILD_ID as string | undefined) ?? "unversioned";
    return {
      label: `VYOM / ${mode} / ${build}`,
      detail: runtimeInfo
        ? `mode=${mode} build=${build} brain=${runtimeInfo.brain} model=${runtimeInfo.model} ` +
          `tools=${runtimeInfo.tools} skills=${runtimeInfo.skills} capabilities=${runtimeInfo.capabilities}`
        : `mode=${mode} build=${build} · Brain registries not reachable yet`,
    };
  }, [runtimeInfo]);

  // VYOM speaks a RESULT, not a running commentary. Every interim
  // response used to be spoken, which is why it repeated "on it" while a
  // mission was still working. Progress belongs on the canvas; the voice
  // is reserved for the outcome (or a state that needs the user).
  //
  // FIX (Aug 2026): The previous implementation had a race condition —
  // composerState, response, and terminalEventKey are set by separate
  // useState calls and React batches/re-renders them independently.
  // The effect fired when terminalEventKey arrived but composerState
  // wasn't "Completed" yet → returned early. Next render composerState
  // updated → effect fired again → but either spokenTerminalRef was
  // already set (if the key matched) OR terminalEventKey was null (if
  // next command cleared it). Result: 61/61 voice completions silent.
  //
  // Fix: terminalEventKey is the authoritative signal that a terminal
  // event arrived. We capture the response at that moment using a ref
  // so we're not racing against async state updates. composerState check
  // removed — terminalEventKey already encodes the event type.
  const spokenTerminalRef = useRef<string | null>(null);
  const lastResponseRef = useRef<string | null>(null);
  lastResponseRef.current = response;

  useEffect(() => {
    if (!terminalEventKey) return;
    if (!voice.sessionActive) return;
    if (spokenTerminalRef.current === terminalEventKey) return;
    // Capture response synchronously at the moment terminalEventKey fires.
    // This avoids the race where response is set in the same batch but
    // composerState hasn't caught up yet.
    const textToSpeak = lastResponseRef.current;
    if (!textToSpeak) return;
    spokenTerminalRef.current = terminalEventKey;
    // The final TTS hop of the command path, through the same trace
    // mechanism as every other hop, so a session can be analyzed
    // end-to-end (utterance -> task -> terminal -> ONE spoken answer).
    trace(newCorrelationId(), "tts.speak", { terminalKey: terminalEventKey, text: textToSpeak.slice(0, 200) });
    voice.speak(textToSpeak);
  // Intentionally exclude composerState — it races with terminalEventKey.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [terminalEventKey, voice]);
  const state = voice.sessionActive && voice.state !== "Idle" ? voice.state : composerState;
  const visual = STATE_VISUALS[state];
  const isBusy = busy || (voice.sessionActive && voice.state !== "Idle");
  // RAW SPEECH IS DIAGNOSTICS, NOT THE INTERFACE.
  //
  // The live transcript sat permanently in the foreground, so the centre
  // of the screen was a running log of the user's own words - which they
  // asked to have removed. VYOM's visual foreground represents MISSION
  // state; the transcript stays available for debugging and for anyone
  // who needs it on screen for accessibility, behind an explicit opt-in.
  const showTranscript = (() => {
    try {
      return window.localStorage.getItem("vyom.showTranscript") === "true";
    } catch {
      return false;
    }
  })();
  const rawTranscript = voice.state === "Speaking" ? voice.outputTranscript : voice.inputTranscript;
  const transcript = showTranscript ? rawTranscript : "";
  const transcriptOwner = voice.state === "Speaking" ? "VYOM" : "YOU";

  useEffect(() => {
    let cancelled = false;
    const checkOnboarding = async () => {
      try {
        const response = await fetch("http://127.0.0.1:7788/api/setup/status", { signal: AbortSignal.timeout(2500) });
        const data = await response.json();
        if (!cancelled) setNeedsOnboarding(Boolean(data.needs_onboarding));
      } catch {
        /* Brain offline: onboarding cannot run; the experience loads normally. */
      }
    };
    void checkOnboarding();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const updateTime = () =>
      setTime(
        new Intl.DateTimeFormat("en-IN", {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }).format(new Date()),
      );
    updateTime();
    const timer = window.setInterval(updateTime, 10_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const enterNativeFullscreen = async () => {
      if (!("__TAURI_INTERNALS__" in window)) return;
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      const appWindow = getCurrentWindow();
      await appWindow.show();
      await appWindow.setFocus();
      await appWindow.setFullscreen(true);
    };

    void enterNativeFullscreen().catch(() => undefined);
  }, []);

  useEffect(() => {
    const handleTrayListen = () => {
      if (!voice.sessionActive) voice.toggle();
    };
    window.addEventListener("vyom-tray-listen", handleTrayListen);
    return () => window.removeEventListener("vyom-tray-listen", handleTrayListen);
  }, [voice]);

  useEffect(() => {
    const handleFullscreenShortcut = async (event: KeyboardEvent) => {
      if (event.key !== "F11" && event.key !== "Escape") return;
      if (!("__TAURI_INTERNALS__" in window)) return;

      event.preventDefault();
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      const appWindow = getCurrentWindow();
      const isFullscreen = await appWindow.isFullscreen();

      if (event.key === "F11") await appWindow.setFullscreen(!isFullscreen);
      if (event.key === "Escape" && isFullscreen) await appWindow.setFullscreen(false);
    };

    window.addEventListener("keydown", handleFullscreenShortcut);
    return () => window.removeEventListener("keydown", handleFullscreenShortcut);
  }, []);

  const submitCommand = (command: string) => {
    const nextCommand = command.trim();
    if (!nextCommand) return;
    setQuery("");
    runCommand(nextCommand);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    submitCommand(query);
  };

  const shellStyle = useMemo(
    () =>
      ({
        "--state-color": visual.color,
        "--state-secondary": visual.secondary,
        "--state-energy": visual.energy,
      }) as React.CSSProperties,
    [visual],
  );

  return (
    <main
      className={`vyom-shell state-${state.toLowerCase()} ${composition ? "workspace-active" : "workspace-calm"}`}
      style={shellStyle}
    >
      <NeuralBiome state={state} />
      {needsOnboarding && <OnboardingOverlay onFinished={() => setNeedsOnboarding(false)} />}
      <div className="atmosphere atmosphere-center" aria-hidden="true" />
      <div className="atmosphere atmosphere-grain" aria-hidden="true" />
      <div className="atmosphere atmosphere-vignette" aria-hidden="true" />

      <header className="topbar" data-tauri-drag-region>
        <div className="identity">
          <BrandMark state={state} />
          <span className="wordmark">VYOM</span>
          {/* Build identity, so a running window can be matched to the
              exact frontend + Brain it is actually using. Hover for the
              full runtime fingerprint. */}
          <span className="build-label" title={diagnostics.detail}>
            {diagnostics.label}
          </span>
        </div>
        <div className="system-status">
          <span className="status-dot" />
          <span>
            {voice.connection === "connected"
              ? "GEMINI LIVE"
              : voice.connection === "reconnecting"
                ? "VOICE RECONNECTING"
                : brainConnection === "online"
                  ? "BRAIN ONLINE"
                  : brainConnection === "reconnecting"
                    ? "BRAIN RECONNECTING"
                    : "LOCAL PRESENCE"}
          </span>
          <span className="status-divider" />
          <span>{time || "--:--"}</span>
        </div>
        <WindowControls />
      </header>

      <UIComposer
        composition={composition}
        visibleObjectIds={visibleObjectIds}
        phase={composerPhase}
      />

      <section className="core-interface" aria-live="polite" aria-atomic="true">
        <div className="state-readout">
          <span className="state-rule" aria-hidden="true" />
          <strong>{state}</strong>
          <span className="state-rule" aria-hidden="true" />
        </div>
        <p className="state-description">{visual.description}</p>

        {(state === "Listening" || state === "Speaking" || state === "Interrupted") && (
          <div
            className="voice-signature"
            aria-hidden="true"
            style={{ "--live-level": voice.level } as React.CSSProperties}
          >
            {voiceBars.map((height, index) => (
              <span
                key={index}
                style={
                  {
                    "--bar-height": `${height}px`,
                    "--bar-delay": `${index * 46}ms`,
                  } as React.CSSProperties
                }
              />
            ))}
          </div>
        )}

        <div className={`live-transcript ${transcript ? "transcript-visible" : ""}`}>
          {transcript && <span>{transcriptOwner}</span>}
          <p>{transcript || "\u00A0"}</p>
        </div>

        <div className={`brain-response ${response ? "response-visible" : ""}`}>
          {lastCommand && <span className="response-context">{lastCommand}</span>}
          <p>{response ?? "\u00A0"}</p>
        </div>

        <p className={`operational-message ${operationalMessage ? "operation-visible" : ""}`}>
          {operationalMessage ?? "\u00A0"}
        </p>
      </section>

      <AgentStackPanel />
      <ConnectionsPanel />

      <section className="interaction-dock">
        {approval && (
          <div className="brain-approval-notice" role="alert">
            <span><AlertCircle size={11} />{approval.level} approval · {approval.action}</span>
            <div>
              <button type="button" onClick={() => decideApproval(false)}>Reject</button>
              <button type="button" onClick={() => decideApproval(true)}>Approve</button>
            </div>
          </div>
        )}
        {voice.error && (
          <div className={`voice-notice notice-${voice.error.code}`} role="status">
            <AlertCircle size={11} />
            <span>{voice.error.message}</span>
            {voice.error.recoverable && (
              <button type="button" onClick={voice.retry} aria-label="Retry voice connection">
                <RotateCw size={10} /> Retry
              </button>
            )}
          </div>
        )}

        <div className={`command-suggestions ${isBusy ? "suggestions-muted" : ""}`}>
          {commandSuggestions.map((command, index) => (
            <div className="suggestion-item" key={command}>
              {index > 0 && <span className="suggestion-separator" aria-hidden="true" />}
              <button type="button" onClick={() => submitCommand(command)}>
                {command}
              </button>
            </div>
          ))}
        </div>

        <form className="command-bar" onSubmit={submit}>
          <button
            className={`activation-key ${voice.sessionActive ? "voice-active" : ""} ${voice.error ? "voice-fault" : ""}`}
            type="button"
            onClick={voice.toggle}
            aria-label={voice.sessionActive ? "Stop voice" : "Start voice"}
            title={voice.sessionActive ? "Stop voice" : "Start Gemini Live voice"}
          >
            {voice.sessionActive ? <MicOff size={14} /> : <Mic size={14} />}
          </button>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={isBusy ? `${state}…` : "Ask VYOM"}
            aria-label="Command"
            autoComplete="off"
            spellCheck={false}
          />
          <button className="send-button" type="submit" disabled={!query.trim()} aria-label="Send command">
            <ArrowUp size={15} strokeWidth={1.7} />
          </button>
        </form>

        <div className="runtime-note">
          <span />
          {voice.connection === "connected"
            ? `${voice.providerInfo?.model ?? "Gemini Live"} · mic on`
            : brainConnection === "online"
              ? `Brain online${activeTaskId ? " · task active" : ""}`
              : voice.providerInfo?.configured
                ? "Voice ready · text fallback"
                : "Brain offline · local fallback"}
          <i>·</i>
          {activeTaskId ? (
            <button className="cancel-task" type="button" onClick={cancelActiveTask}>Cancel task</button>
          ) : (
            <span className="keyboard-hint">Enter to send</span>
          )}
        </div>
      </section>
    </main>
  );
}
