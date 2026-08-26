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
  | "visualization_requested"
  | "approval_required"
  | "verification_started"
  | "verification_passed"
  | "verification_failed"
  | "task_completed"
  | "task_failed"
  | "task_retried"
  | "task_cancelled"
  | "memory_retrieved"
  | "memory_created"
  | "memory_updated"
  | "memory_superseded"
  | "memory_forgotten"
  | "memory_consolidated"
  | "skill_matched"
  | "skill_created"
  | "skill_testing"
  | "skill_step_started"
  | "skill_promoted"
  | "skill_failed"
  | "skill_updated"
  | "agent_created"
  | "agent_testing"
  | "agent_ready"
  | "agent_started"
  | "agent_delegated"
  | "agent_completed"
  | "agent_paused"
  | "agent_failed"
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
  | "research_started"
  | "research_plan_ready"
  | "source_discovered"
  | "source_read"
  | "claim_extracted"
  | "contradiction_found"
  | "research_verified"
  | "browser_observed"
  | "browser_recovered"
  | "capability_gap_detected"
  | "api_discovered"
  | "mcp_discovered"
  | "saas_discovered"
  | "booking_search_started"
  | "booking_option_found"
  | "booking_approval_required"
  | "booking_confirmed"
  | "artifact_started"
  | "artifact_rendered"
  | "artifact_validation_failed"
  | "artifact_verified"
  | "delivery_package_ready"
  | "delivery_approval_required"
  | "delivery_sent"
  | "delivery_verified"
  | "desktop_startup_enabled"
  | "desktop_startup_disabled"
  | "app_opened"
  | "app_focused"
  | "app_closed"
  | "window_focused"
  | "window_moved"
  | "clipboard_read"
  | "clipboard_written"
  | "screen_captured"
  | "screen_observed"
  | "accessibility_action"
  | "mouse_action"
  | "keyboard_action"
  | "desktop_action_verified"
  | "desktop_action_failed"
  | "device_connected"
  | "device_disconnected"
  | "device_command_started"
  | "device_command_completed"
  | "emergency_pause"
  | "market_data_requested"
  | "market_data_received"
  | "market_data_stale"
  | "market_research_started"
  | "market_thesis_ready"
  | "trade_setup_created"
  | "trade_setup_rejected"
  | "risk_check_started"
  | "risk_check_passed"
  | "risk_check_failed"
  | "paper_order_created"
  | "paper_order_filled"
  | "paper_order_cancelled"
  | "paper_position_opened"
  | "paper_position_closed"
  | "backtest_started"
  | "backtest_completed"
  | "backtest_failed"
  | "strategy_created"
  | "strategy_validated"
  | "market_alert_triggered"
  | "paper_trading_paused"
  | "risk_kill_switch_triggered"
  | "goal_created"
  | "goal_updated"
  | "goal_completed"
  | "goal_blocked"
  | "habit_created"
  | "habit_event_recorded"
  | "habit_pattern_detected"
  | "habit_insight_created"
  | "routine_started"
  | "routine_completed"
  | "routine_missed"
  | "focus_started"
  | "focus_paused"
  | "focus_completed"
  | "commitment_created"
  | "commitment_due"
  | "commitment_completed"
  | "daily_plan_created"
  | "pending_work_recalled"
  | "curator_run_completed"
  | "morning_briefing_ready"
  | "evening_review_ready"
  | "weekly_review_ready"
  | "proactive_suggestion_created"
  | "proactive_suggestion_suppressed"
  | "notification_batched"
  | "quiet_mode_started"
  | "quiet_mode_ended"
  | "node_registered"
  | "node_authenticated"
  | "node_revoked"
  | "node_online"
  | "node_offline"
  | "task_dispatched"
  | "task_handoff_started"
  | "task_handoff_completed"
  | "task_lease_expired"
  | "sync_started"
  | "sync_completed"
  | "sync_conflict"
  | "offline_command_queued"
  | "offline_command_expired"
  | "backup_started"
  | "backup_completed"
  | "backup_failed"
  | "restore_started"
  | "restore_completed"
  | "health_degraded"
  | "worker_recovered"
  | "circuit_breaker_opened"
  | "mobile_approval_received"
  | "remote_command_received";

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
