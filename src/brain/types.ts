import type { UIComposition } from "@/composer/ui-schema";

export type BrainConnectionState = "connecting" | "online" | "offline" | "reconnecting";

export type BrainEventType =
  | "task_created"
  | "task_understanding"
  | "task_planning"
  | "plan_ready"
  | "model_selected"
  | "model_fallback"
  | "task_progress"
  | "agent_activity"
  | "tool_started"
  | "tool_selected"
  | "tool_permission_check"
  | "tool_progress"
  | "tool_completed"
  | "tool_failed"
  | "tool_retry"
  | "browser_opened"
  | "browser_action"
  | "terminal_started"
  | "terminal_output"
  | "file_changed"
  | "git_changed"
  | "test_started"
  | "test_passed"
  | "test_failed"
  | "verification_evidence"
  | "mcp_connected"
  | "mcp_tool_invoked"
  | "memory_created"
  | "memory_retrieved"
  | "memory_updated"
  | "memory_forgotten"
  | "memory_consolidated"
  | "memory_superseded"
  | "skill_created"
  | "skill_matched"
  | "skill_testing"
  | "skill_promoted"
  | "skill_failed"
  | "skill_updated"
  | "agent_created"
  | "agent_testing"
  | "agent_ready"
  | "agent_started"
  | "agent_delegated"
  | "agent_completed"
  | "agent_failed"
  | "agent_paused"
  | "lesson_created"
  | "learning_applied"
  | "integration_connected"
  | "integration_disconnected"
  | "integration_error"
  | "email_searched"
  | "email_read"
  | "email_drafted"
  | "email_send_approval_required"
  | "email_sent"
  | "email_verified"
  | "contact_resolved"
  | "contact_ambiguous"
  | "crm_updated"
  | "lead_researched"
  | "lead_qualified"
  | "outreach_drafted"
  | "outreach_approval_required"
  | "outreach_sent"
  | "reply_detected"
  | "followup_scheduled"
  | "calendar_read"
  | "availability_checked"
  | "meeting_approval_required"
  | "meeting_created"
  | "meeting_verified"
  | "briefing_generated"
  | "automation_created"
  | "automation_scheduled"
  | "automation_started"
  | "automation_paused"
  | "automation_resumed"
  | "automation_completed"
  | "automation_failed"
  | "visualization_requested"
  | "approval_required"
  | "verification_started"
  | "verification_passed"
  | "verification_failed"
  | "task_completed"
  | "task_failed"
  | "task_cancelled";

export type BrainEvent = {
  schema_version: 1;
  event_id: string;
  task_id: string;
  timestamp: string;
  type: BrainEventType;
  human_readable_message: string;
  structured_payload: {
    composition?: UIComposition;
    response?: string;
    error?: string;
    task?: {
      result?: {
        structured_data?: {
          clear_workspace?: boolean;
        };
      };
    };
    /** Telemetry the Brain emits about ITSELF (health checks, resource
     * sampling). It is recorded internally but must never take over the
     * foreground, interrupt a mission, or be spoken - see LAW 8.
     */
    background?: boolean;
    /**
     * Per-task execution mode the Brain decided (from
     * classify_visibility): 'background' -> minimize VYOM's own window and
     * work invisibly; 'visual' -> keep the window up (browser opens headed).
     * Present once profile.visibility is set (absent on the very first
     * task_created event).
     */
    window_visibility?: "background" | "visual";
    channel?: "BACKGROUND_HEALTH" | string;
    routing?: {
      primary_model: string;
      primary_provider: string;
      fallback_models: string[];
      reason_selected: string;
      estimated_cost_tier: string;
    };
    approval?: {
      id: string;
      task_id: string;
      permission_level: "L2" | "L3";
      action: string;
      reason: string;
    };
  };
};

export type BrainTask = {
  id: string;
  goal: string;
  user_request: string;
  status: string;
  progress: number;
  assigned_model?: string | null;
  error?: string | null;
};

export type PendingApproval = {
  taskId: string;
  approvalId: string;
  level: "L2" | "L3";
  action: string;
  reason: string;
};
