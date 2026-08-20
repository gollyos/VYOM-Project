/**
 * Phase 13 first-run onboarding. Rendered over the neural biome — never
 * a SaaS dashboard or a setup page. Minimal, immersive, skippable where
 * safe; state persists in the Brain so an interrupted setup resumes and
 * a completed one never reappears.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

interface SetupStep {
  id: string;
  title: string;
  description: string;
  required: boolean;
  status: "pending" | "in_progress" | "completed" | "skipped";
}

// The EXACT wire shape returned by GET/POST /api/setup/... - see
// services/brain/app/setup/onboarding.py::OnboardingService.status().
// Kept snake_case to match the real response; never assumed via a type
// cast (a prior version did `as SetupStatus`, which let the frontend
// silently believe fields existed - `steps` and `nextStep` in particular
// - that the backend never actually sent, crashing the whole app on
// first load with no error boundary).
interface SetupStatusResponse {
  finished: boolean;
  needs_onboarding: boolean;
  next_step: string | null;
  steps?: SetupStep[];
}

// Component-local view model - only what the UI needs, explicitly mapped
// from the wire shape so a missing/renamed backend field can never
// silently become `undefined` deep inside a render.
interface SetupStatus {
  finished: boolean;
  needsOnboarding: boolean;
  nextStep: string | null;
  steps: SetupStep[];
}

function toSetupStatus(data: SetupStatusResponse): SetupStatus {
  return {
    finished: Boolean(data.finished),
    needsOnboarding: !data.finished,
    nextStep: data.next_step ?? null,
    steps: Array.isArray(data.steps) ? data.steps : [],
  };
}

const BRAIN_BASE = "http://127.0.0.1:7788";

const PRIVACY_CHOICES = [
  { key: "external_models", label: "Allow external AI models", detail: "Required for cloud providers; local deterministic commands always work.", defaultChoice: "ask" },
  { key: "screen_capture", label: "Screen capture", detail: "Only ever on explicit request — never continuous.", defaultChoice: "on_request" },
  { key: "personal_memory", label: "Personal memory", detail: "VYOM remembers preferences and lessons locally.", defaultChoice: "enabled" },
  { key: "crash_reports", label: "Share crash reports", detail: "Local only by default; nothing is uploaded.", defaultChoice: "off" },
];

const AUTONOMY_PRESETS = [
  { key: "conservative", label: "Conservative", detail: "Only reading runs automatically; every action asks first." },
  { key: "balanced", label: "Balanced", detail: "Reads and safe local actions run automatically; external actions ask." },
  { key: "autonomous", label: "Autonomous", detail: "More proactive background work; approvals still guard every external action." },
];

export function OnboardingOverlay({ onFinished }: { onFinished: () => void }) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [privacy, setPrivacy] = useState<Record<string, string>>(
    Object.fromEntries(PRIVACY_CHOICES.map((choice) => [choice.key, choice.defaultChoice])),
  );
  const [autonomy, setAutonomy] = useState("balanced");
  const [diagnostics, setDiagnostics] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const response = await fetch(`${BRAIN_BASE}/api/setup/status`);
        if (!response.ok) throw new Error(`setup status responded ${response.status}`);
        const data = (await response.json()) as SetupStatusResponse;
        if (!cancelled) setStatus(toSetupStatus(data));
      } catch {
        // Brain unreachable or a malformed response: onboarding simply
        // cannot run right now. Never crash the app over this - status
        // stays null and the component renders nothing, matching
        // vyom-experience.tsx's own "Brain offline: experience loads
        // normally" fallback for the same endpoint.
        if (!cancelled) setStatus(null);
      }
    };
    void load();
    return () => { cancelled = true; };
  }, []);

  const step = useMemo(
    () => status?.steps.find((item) => item.id === status.nextStep) ?? null,
    [status],
  );

  const post = useCallback(async (path: string, body: unknown) => {
    setBusy(true);
    try {
      const response = await fetch(`${BRAIN_BASE}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
      });
      if (!response.ok) throw new Error(`${path} responded ${response.status}`);
      const data = (await response.json()) as SetupStatusResponse;
      const next = toSetupStatus(data);
      setStatus(next);
      if (next.finished) onFinished();
      return next;
    } catch {
      // A step transition that failed (Brain restarted mid-onboarding,
      // network blip, ...) must leave the overlay usable, not frozen or
      // crashed - the existing status is kept as-is and the user can
      // retry once busy clears in the finally block below.
      return null;
    } finally {
      setBusy(false);
    }
  }, [onFinished]);

  if (status === null) return null;

  const complete = (data: Record<string, unknown> = {}) => step && post(`/api/setup/steps/${step.id}/complete`, { data });
  const skip = () => step && post(`/api/setup/steps/${step.id}/skip`, {});
  const isLast = step?.id === "ready";

  const runDiagnostics = async () => {
    setBusy(true);
    try {
      const response = await fetch(`${BRAIN_BASE}/api/diagnostics/doctor`, { method: "POST" });
      const report = await response.json();
      setDiagnostics(`${report.overall} · ${report.counts.PASS} pass / ${report.counts.WARNING} warn / ${report.counts.FAIL} fail`);
    } catch {
      setDiagnostics("Could not reach the Brain for diagnostics.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="onboarding-veil" role="dialog" aria-label="VYOM setup">
      <div className="onboarding-panel">
        <div className="onboarding-core" aria-hidden="true"><span /></div>
        <p className="onboarding-eyebrow">VYOM · FIRST RUN</p>
        <h1 className="onboarding-title">{step ? step.title : "Welcome. I'm VYOM."}</h1>
        <p className="onboarding-description">
          {step ? step.description : "Setting up your environment."}
        </p>

        {step?.id === "privacy" && (
          <div className="onboarding-choices">
            {PRIVACY_CHOICES.map((choice) => (
              <label key={choice.key} className="onboarding-choice">
                <span>
                  <strong>{choice.label}</strong>
                  <em>{choice.detail}</em>
                </span>
                <select
                  value={privacy[choice.key]}
                  onChange={(event) => setPrivacy((current) => ({ ...current, [choice.key]: event.target.value }))}
                >
                  {choice.key === "external_models" && (
                    <>
                      <option value="ask">Ask before each use</option>
                      <option value="allowed">Allowed</option>
                      <option value="local_only">Local only</option>
                    </>
                  )}
                  {choice.key === "screen_capture" && (
                    <>
                      <option value="on_request">On request only</option>
                      <option value="off">Off</option>
                    </>
                  )}
                  {choice.key === "personal_memory" && (
                    <>
                      <option value="enabled">Enabled</option>
                      <option value="off">Off</option>
                    </>
                  )}
                  {choice.key === "crash_reports" && (
                    <>
                      <option value="off">Keep local</option>
                      <option value="opt_in">Share (opt-in)</option>
                    </>
                  )}
                </select>
              </label>
            ))}
          </div>
        )}

        {step?.id === "autonomy" && (
          <div className="onboarding-presets">
            {AUTONOMY_PRESETS.map((preset) => (
              <button
                key={preset.key}
                type="button"
                className={`onboarding-preset ${autonomy === preset.key ? "preset-active" : ""}`}
                onClick={() => setAutonomy(preset.key)}
              >
                <strong>{preset.label}</strong>
                <em>{preset.detail}</em>
              </button>
            ))}
            <p className="onboarding-note">Every preset keeps the same approval rules — nothing bypasses critical-action protection.</p>
          </div>
        )}

        {step?.id === "diagnostics" && (
          <div className="onboarding-diagnostics">
            <button type="button" className="onboarding-action" onClick={runDiagnostics} disabled={busy}>
              Run system diagnostics
            </button>
            {diagnostics && <p className="onboarding-result">{diagnostics}</p>}
          </div>
        )}

        <div className="onboarding-controls">
          <button
            type="button"
            className="onboarding-action onboarding-primary"
            disabled={busy}
            onClick={() => {
              if (step?.id === "privacy") { void complete({ choices: privacy }); return; }
              if (step?.id === "autonomy") { void complete({ preset: autonomy }); return; }
              if (step?.id === "ready") { void complete({}); return; }
              void complete({});
            }}
          >
            {isLast ? "Begin" : "Continue"}
          </button>
          {step && !step.required && (
            <button type="button" className="onboarding-skip" onClick={skip} disabled={busy}>
              Skip for now
            </button>
          )}
        </div>

        <div className="onboarding-progress" aria-hidden="true">
          {status.steps.map((item) => (
            <span
              key={item.id}
              className={`onboarding-dot ${item.status === "completed" ? "dot-done" : ""} ${item.id === step?.id ? "dot-current" : ""}`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
