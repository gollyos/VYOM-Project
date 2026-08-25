import { useCallback, useEffect, useRef, useState } from "react";
import { BrainClient } from "@/brain/brain-client";
import type { BrainConnectionState, BrainEvent, PendingApproval } from "@/brain/types";
import { validateComposition, type ComposerPhase, type UIComposition } from "@/composer/ui-schema";
import { newCorrelationId, trace } from "./trace";
import { resolveIntent, type VyomState } from "./vyom-state";

const NATIVE_NOTIFICATION_CATEGORIES: Partial<Record<BrainEvent["type"], string>> = {
  approval_required: "Approval needed",
  task_failed: "Task failed",
  automation_completed: "Automation completed",
  reply_detected: "Client reply received",
  meeting_verified: "Meeting confirmed",
};

async function dispatchNativeNotification(title: string, body: string) {
  if (!("__TAURI_INTERNALS__" in window)) return;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("show_native_notification", { title, body });
  } catch {
    // Native notifications are best-effort; the in-app response remains authoritative.
  }
}

async function dispatchWindowVisibility(action: "minimize" | "restore") {
  if (!("__TAURI_INTERNALS__" in window)) return;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    if (action === "minimize") await invoke("minimize_vyom_window");
    else await invoke("restore_vyom_window");
  } catch {
    // Window control is best-effort; the in-app task flow remains authoritative.
  }
}

type RuntimeSnapshot = {
  state: VyomState;
  response: string | null;
  operationalMessage: string | null;
  lastCommand: string | null;
  busy: boolean;
  composition: UIComposition | null;
  visibleObjectIds: string[];
  composerPhase: ComposerPhase;
  brainConnection: BrainConnectionState;
  activeTaskId: string | null;
  terminalEventKey: string | null;
  approval: PendingApproval | null;
  runCommand: (
    command: string,
    correlationId?: string,
    options?: { supersedesPrevious?: boolean },
  ) => void;
  decideApproval: (approved: boolean) => void;
  cancelActiveTask: () => void;
  emergencyStop: () => void;
};

export function useVyomRuntime(): RuntimeSnapshot {
  const [state, setState] = useState<VyomState>("Idle");
  const [response, setResponse] = useState<string | null>(null);
  const [operationalMessage, setOperationalMessageState] = useState<string | null>(null);
  const operationalMessageTimer = useRef<number | null>(null);
  const pendingOperationalMessage = useRef<string | null>(null);
  // High-frequency Brain events (tool_progress, terminal_output,
  // browser_action, memory_created/updated, mcp_tool_invoked, ...) can
  // arrive in rapid bursts during an active mission; without this, every
  // single one triggers an immediate React re-render. Trailing-edge
  // coalescing to at most one update per ~80ms keeps the UI responsive
  // under a burst while staying well under typical "instant" human
  // perception. Clearing back to calm (message = null) always flushes
  // immediately so it never lags behind a stale queued burst.
  const setOperationalMessage = useCallback((message: string | null) => {
    pendingOperationalMessage.current = message;
    if (message === null) {
      if (operationalMessageTimer.current !== null) {
        window.clearTimeout(operationalMessageTimer.current);
        operationalMessageTimer.current = null;
      }
      setOperationalMessageState(null);
      return;
    }
    if (operationalMessageTimer.current !== null) return;
    operationalMessageTimer.current = window.setTimeout(() => {
      operationalMessageTimer.current = null;
      setOperationalMessageState(pendingOperationalMessage.current);
    }, 80);
  }, []);
  const [lastCommand, setLastCommand] = useState<string | null>(null);
  const [composition, setComposition] = useState<UIComposition | null>(null);
  const [visibleObjectIds, setVisibleObjectIds] = useState<string[]>([]);
  const [composerPhase, setComposerPhase] = useState<ComposerPhase>("calm");
  const [brainConnection, setBrainConnection] = useState<BrainConnectionState>("connecting");
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [terminalEventKey, setTerminalEventKey] = useState<string | null>(null);
  const [approval, setApproval] = useState<PendingApproval | null>(null);
  const timers = useRef<number[]>([]);
  const clientRef = useRef<BrainClient | null>(null);
  const compositionRef = useRef<UIComposition | null>(null);
  const activeTaskRef = useRef<string | null>(null);
  // Independent commands may run concurrently. Only one owns the visual
  // foreground; the others retain their own task/event identity here and
  // are never cancelled or allowed to paint over the foreground task.
  const backgroundTaskIdsRef = useRef(new Set<string>());
  const foregroundSubmissionRef = useRef(0);
  const lastCommandRef = useRef<string | null>(null);
  const correlationRef = useRef<string | null>(null);
  const supersededTaskIdsRef = useRef<Set<string>>(new Set());
  // Tracks whether VYOM's own window has been minimized for a background
  // task, so we restore it exactly once when that task finishes.
  const windowMinimizedRef = useRef(false);

  useEffect(() => { compositionRef.current = composition; }, [composition]);
  useEffect(() => { activeTaskRef.current = activeTaskId; }, [activeTaskId]);
  useEffect(() => { lastCommandRef.current = lastCommand; }, [lastCommand]);

  const clearTimers = useCallback(() => {
    timers.current.forEach((timer) => window.clearTimeout(timer));
    timers.current = [];
  }, []);

  const schedule = useCallback((callback: () => void, delay: number) => {
    const timer = window.setTimeout(callback, delay);
    timers.current.push(timer);
  }, []);

  const returnToCalm = useCallback((at: number) => {
    schedule(() => setState("Idle"), at);
    schedule(() => setResponse(null), at + 1200);
    schedule(() => setOperationalMessage(null), at + 1600);
  }, [schedule]);

  const openComposition = useCallback((nextComposition: UIComposition, command: string) => {
    clearTimers();
    lastCommandRef.current = command;
    setLastCommand(command);
    setResponse(null);

    const begin = () => {
      compositionRef.current = nextComposition;
      setComposition(nextComposition);
      setVisibleObjectIds([]);
      setComposerPhase("composing");
      nextComposition.sequence.forEach((step) => {
        schedule(() => {
          setState(step.state);
          setOperationalMessage(step.label);
          setVisibleObjectIds((current) => Array.from(new Set([...current, ...step.objectIds])));
        }, step.atMs);
      });
      const finalAt = Math.max(...nextComposition.sequence.map((step) => step.atMs), 0);
      schedule(() => {
        setComposerPhase("active");
        setState("Completed");
        setResponse(nextComposition.summary);
        setOperationalMessage("Verified result ready");
      }, finalAt + 420);
      schedule(() => setState("Idle"), finalAt + 2200);
      schedule(() => setResponse(null), finalAt + 4300);
      schedule(() => setOperationalMessage(null), finalAt + 4700);
    };

    if (compositionRef.current) {
      setComposerPhase("dismissing");
      setState("Thinking");
      schedule(begin, 460);
    } else {
      begin();
    }
  }, [clearTimers, schedule]);

  const handleBrainEvent = useCallback((event: BrainEvent) => {
    // BACKGROUND_HEALTH and anything else the Brain emits about ITSELF is
    // not the user's mission. It used to reach the foreground whenever no
    // task happened to be active - which is exactly when the user is
    // looking at a calm screen - and painted CPU/RAM and "X is degraded"
    // over it. Telemetry stays internal; the foreground belongs to what
    // the user asked for.
    const isBackground =
      event.structured_payload?.background === true ||
      event.structured_payload?.channel === "BACKGROUND_HEALTH" ||
      event.task_id === "system";
    if (isBackground) return;

    // Per-task execution mode (background vs visual) reaches the frontend
    // on every event as structured_payload.window_visibility. When the
    // Brain decides a task should run in the BACKGROUND (profile.visibility
    // = 'background', from classify_visibility), VYOM's own window minimizes
    // so the work happens invisibly and out of the user's way; when that
    // task ends (completed/failed/cancelled) the window is restored so the
    // user sees the result. Guarded by windowMinimizedRef so we only
    // minimize once and restore exactly once. Best-effort (Tauri only).
    const windowVisibility = event.structured_payload.window_visibility;
    if (windowVisibility === "background" && !windowMinimizedRef.current) {
      windowMinimizedRef.current = true;
      void dispatchWindowVisibility("minimize");
    }
    if (windowMinimizedRef.current &&
        ["task_completed", "task_failed", "task_cancelled"].includes(event.type)) {
      windowMinimizedRef.current = false;
      void dispatchWindowVisibility("restore");
    }
    // late cancellation/failure/completion event must not replace the UI
    // state of the newer command during the create-task handoff window.
    if (supersededTaskIdsRef.current.has(event.task_id)) {
      if (["task_completed", "task_failed", "task_cancelled"].includes(event.type)) {
        supersededTaskIdsRef.current.delete(event.task_id);
      }
      return;
    }

    const isBackgroundTask = backgroundTaskIdsRef.current.has(event.task_id);
    if (isBackgroundTask) {
      if (["task_completed", "task_failed", "task_cancelled"].includes(event.type)) {
        backgroundTaskIdsRef.current.delete(event.task_id);
        const backgroundTitle = event.type === "task_completed"
          ? "Background task completed"
          : event.type === "task_failed"
            ? "Background task failed"
            : "Background task cancelled";
        void dispatchNativeNotification(backgroundTitle, event.human_readable_message);
      }
      return;
    }

    if (!activeTaskRef.current && event.type === "task_created") {
      activeTaskRef.current = event.task_id;
      setActiveTaskId(event.task_id);
    }
    if (activeTaskRef.current && event.task_id !== activeTaskRef.current) return;
    setOperationalMessage(event.human_readable_message);

    const notificationTitle = NATIVE_NOTIFICATION_CATEGORIES[event.type];
    if (notificationTitle) void dispatchNativeNotification(notificationTitle, event.human_readable_message);

    switch (event.type) {
      case "task_created": setState("Understanding"); break;
      case "task_understanding": setState("Understanding"); break;
      case "task_planning": setState("Planning"); break;
      case "plan_ready": setState("Planning"); break;
      case "model_selected": setState("Thinking"); break;
      case "model_fallback": setState("Thinking"); break;
      case "task_progress": setState("Executing"); break;
      case "tool_selected":
      case "tool_permission_check": setState("Planning"); break;
      case "tool_started":
      case "tool_progress":
      case "browser_opened":
      case "browser_action":
      case "terminal_started":
      case "terminal_output":
      case "file_changed":
      case "git_changed":
      case "test_started":
      case "mcp_connected":
      case "mcp_tool_invoked":
      case "memory_created":
      case "memory_updated":
      case "memory_superseded":
      case "memory_forgotten":
      case "skill_created":
      case "skill_updated":
      case "agent_started":
      case "agent_delegated": setState("Executing"); break;
      case "integration_connected":
      case "email_searched":
      case "email_read":
      case "email_drafted":
      case "contact_resolved":
      case "crm_updated":
      case "lead_researched":
      case "outreach_drafted":
      case "calendar_read":
      case "availability_checked":
      case "automation_created":
      case "automation_scheduled":
      case "automation_started":
      case "automation_resumed": setState("Executing"); break;
      case "tool_completed":
      case "test_passed":
      case "verification_evidence":
      case "memory_retrieved":
      case "memory_consolidated":
      case "skill_matched":
      case "skill_testing":
      case "skill_promoted":
      case "agent_created":
      case "agent_testing":
      case "agent_ready":
      case "agent_completed":
      case "lesson_created":
      case "learning_applied": setState("Verifying"); break;
      case "email_sent":
      case "email_verified":
      case "lead_qualified":
      case "outreach_sent":
      case "reply_detected":
      case "followup_scheduled":
      case "meeting_created":
      case "meeting_verified":
      case "briefing_generated":
      case "automation_completed": setState("Verifying"); break;
      case "integration_disconnected":
      case "integration_error":
      case "automation_failed": setState("Failed"); break;
      case "email_send_approval_required":
      case "outreach_approval_required":
      case "meeting_approval_required":
      case "automation_paused": setState("WaitingApproval"); break;
      case "contact_ambiguous": setState("Thinking"); break;
      case "tool_retry": setState("Thinking"); break;
      case "tool_failed":
      case "test_failed":
      case "skill_failed":
      case "agent_failed": setState("Failed"); break;
      case "agent_paused": setState("WaitingApproval"); break;
      case "approval_required": {
        setState("WaitingApproval");
        const pending = event.structured_payload.approval;
        if (pending) {
          setApproval({
            taskId: event.task_id,
            approvalId: pending.id,
            level: pending.permission_level,
            action: pending.action,
            reason: pending.reason,
          });
        }
        break;
      }
      case "verification_started": setState("Verifying"); break;
      case "verification_failed": setState("Failed"); break;
      case "verification_passed": setState("Verifying"); break;
      case "visualization_requested": {
        const value = event.structured_payload.composition;
        if (value) {
          try { openComposition(validateComposition(value), lastCommandRef.current ?? "Brain task"); } catch {
            setState("Failed");
            setResponse("The Brain returned an invalid visual composition.");
          }
        }
        break;
      }
      case "task_completed":
        if (correlationRef.current) {
          trace(correlationRef.current, "brain.task_completed", {
            task_id: event.task_id,
            response: event.structured_payload.response ?? event.human_readable_message,
          });
        }
        setApproval(null);
        if (event.structured_payload.task?.result?.structured_data?.clear_workspace) {
          setVisibleObjectIds([]);
          setComposition(null);
          compositionRef.current = null;
          setComposerPhase("calm");
        }
        setState("Completed");
        setResponse(event.structured_payload.response ?? event.human_readable_message);
        setTerminalEventKey(`task_completed:${event.task_id}`);
        activeTaskRef.current = null;
        setActiveTaskId(null);
        break;
      case "task_failed":
        if (correlationRef.current) {
          trace(correlationRef.current, "brain.task_failed", {
            task_id: event.task_id,
            error: event.structured_payload.error ?? event.human_readable_message,
          });
        }
        setApproval(null);
        setState("Failed");
        setResponse(event.structured_payload.error ?? event.human_readable_message);
        setTerminalEventKey(`task_failed:${event.task_id}`);
        activeTaskRef.current = null;
        setActiveTaskId(null);
        returnToCalm(4200);
        break;
      case "task_cancelled":
        setApproval(null);
        setState("Idle");
        setResponse("Task cancelled.");
        activeTaskRef.current = null;
        setActiveTaskId(null);
        returnToCalm(1800);
        break;
    }
  }, [openComposition, returnToCalm]);

  useEffect(() => {
    const client = new BrainClient();
    clientRef.current = client;
    const unsubscribe = client.subscribe(handleBrainEvent, setBrainConnection);
    void client.health().then(() => setBrainConnection("online")).catch(() => setBrainConnection("offline"));
    return () => {
      unsubscribe();
      client.destroy();
      clearTimers();
    };
  }, [clearTimers, handleBrainEvent]);

  const submitToBrain = useCallback((
    command: string,
    correlationId?: string,
    options?: { supersedesPrevious?: boolean },
  ) => {
    const correlation = correlationId ?? newCorrelationId();
    const submission = ++foregroundSubmissionRef.current;
    correlationRef.current = correlation;
    trace(correlation, "command.submitted", { command, source: correlationId ? "voice" : "text" });
    clearTimers();
    // A voice turn split by a premature VAD end-of-turn (see voice.rs) can
    // still dispatch a partial utterance before the continuation arrives.
    // The prior in-flight task is cancelled server-side rather than just
    // forgotten locally - left running, it competed with the new task for
    // the same rate-limited model call and was the direct cause of a
    // stray HTTP 503 the user saw as an unexplained failure.
    // Only a corrected revision of the SAME acoustic utterance supersedes
    // prior work. A genuinely new command is an independent task: move
    // the old foreground task to the background instead of cancelling it.
    if (options?.supersedesPrevious && activeTaskRef.current) {
      supersededTaskIdsRef.current.add(activeTaskRef.current);
      if (supersededTaskIdsRef.current.size > 64) {
        const oldest = supersededTaskIdsRef.current.values().next().value;
        if (oldest) supersededTaskIdsRef.current.delete(oldest);
      }
      trace(correlation, "brain.superseded_task_cancelled", { task_id: activeTaskRef.current });
      void clientRef.current?.cancelTask(activeTaskRef.current).catch(() => undefined);
    } else if (activeTaskRef.current) {
      backgroundTaskIdsRef.current.add(activeTaskRef.current);
    }
    activeTaskRef.current = null;
    setActiveTaskId(null);
    setApproval(null);
    lastCommandRef.current = command;
    setLastCommand(command);
    setResponse(null);
    setTerminalEventKey(null);
    setOperationalMessage("Sending goal to the local Brain");
    setState("Understanding");
    void clientRef.current?.createTask(command).then((task) => {
      // Several create requests can be in flight at once. The newest
      // submission owns the foreground; an older response arriving later
      // becomes background work and may not steal UI authority.
      if (submission !== foregroundSubmissionRef.current) {
        backgroundTaskIdsRef.current.add(task.id);
        return;
      }
      activeTaskRef.current = task.id;
      setActiveTaskId(task.id);
      setBrainConnection("online");
      trace(correlation, "brain.task_created", { task_id: task.id, command });
    }).catch((error: unknown) => {
      trace(correlation, "brain.unreachable", {
        command,
        error: error instanceof Error ? error.message : String(error),
      });
      // No local fallback answer. Previously a failed Brain call could be
      // answered from a hard-coded local composition, which made a
      // disconnected Brain look like a working assistant. VYOM now always
      // shows the real failure.
      setBrainConnection("offline");
      setOperationalMessage("VYOM Brain disconnected · retrying connection");
      setState("Failed");
      setResponse(
        `VYOM Brain disconnected. The command was not executed. (${
          error instanceof Error ? error.message : "no response from 127.0.0.1:7788"
        })`,
      );
      setTerminalEventKey(`brain-unreachable:${correlation}`);
      returnToCalm(5200);
    });
  }, [clearTimers, returnToCalm]);

  const runCommand = useCallback((
    rawCommand: string,
    correlationId?: string,
    options?: { supersedesPrevious?: boolean },
  ) => {
    const command = rawCommand.trim();
    if (!command) return;
    trace(correlationId ?? newCorrelationId(), "command.received", { command });
    const intent = resolveIntent(command);
    if (intent === "wake") {
      clearTimers();
      lastCommandRef.current = command;
      setLastCommand(command);
      setState("Listening");
      schedule(() => { setState("Speaking"); setResponse("I’m here."); }, 650);
      returnToCalm(1900);
      return;
    }
    // Every remaining command - typed or spoken - enters the one Brain
    // command pipeline. There is no separate demo/developer route: the
    // "developer" view used to be served from a hard-coded local
    // composition that never touched the Brain at all.
    submitToBrain(command, correlationId, options);
  }, [clearTimers, returnToCalm, schedule, submitToBrain]);

  const decideApproval = useCallback((approved: boolean) => {
    if (!approval) return;
    setOperationalMessage(approved ? "Approval granted · resuming task" : "Approval rejected · cancelling task");
    setState(approved ? "Executing" : "Idle");
    void clientRef.current?.decideApproval(approval.taskId, approved).catch(() => {
      setState("Failed");
      setResponse("The approval decision could not reach the Brain.");
    });
    if (!approved) setApproval(null);
  }, [approval]);

  const cancelActiveTask = useCallback(() => {
    if (!activeTaskRef.current) return;
    void clientRef.current?.cancelTask(activeTaskRef.current);
  }, []);

  const emergencyStop = useCallback(() => {
    clearTimers();
    void clientRef.current?.emergencyPause();
    if (activeTaskRef.current) void clientRef.current?.cancelTask(activeTaskRef.current);
    setState("Idle");
    setResponse("Emergency stop engaged. Active input automation and tasks were cancelled.");
    activeTaskRef.current = null;
    setActiveTaskId(null);
    setApproval(null);
  }, [clearTimers]);

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    let disposed = false;
    const unlisten: Array<() => void> = [];

    void (async () => {
      const { listen } = await import("@tauri-apps/api/event");

      const trayUnlisten = await listen<string>("tray-action", (event) => {
        switch (event.payload) {
          case "listen":
            window.dispatchEvent(new CustomEvent("vyom-tray-listen"));
            break;
          case "pause_vyom":
            cancelActiveTask();
            break;
          case "pause_automations":
            void clientRef.current?.pauseAllAutomations();
            break;
          case "resume_automations":
            void clientRef.current?.resumeAllAutomations();
            break;
          case "current_tasks":
            submitToBrain("What needs approval?");
            break;
        }
      });

      const emergencyUnlisten = await listen("emergency-pause", () => {
        emergencyStop();
      });

      if (disposed) {
        trayUnlisten();
        emergencyUnlisten();
      } else {
        unlisten.push(trayUnlisten, emergencyUnlisten);
      }
    })();

    return () => {
      disposed = true;
      unlisten.forEach((fn) => fn());
    };
  }, [cancelActiveTask, emergencyStop, submitToBrain]);

  return {
    state,
    response,
    operationalMessage,
    lastCommand,
    busy: state !== "Idle" || composerPhase === "composing" || composerPhase === "dismissing",
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
    emergencyStop,
  };
}
