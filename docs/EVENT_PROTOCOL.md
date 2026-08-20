# VYOM Brain Event Protocol

Brain events are versioned operational envelopes sent over `/ws/events`. They show what VYOM is doing without revealing hidden chain-of-thought.

```json
{
  "schema_version": 1,
  "event_id": "evt_...",
  "task_id": "task_...",
  "timestamp": "2026-08-15T00:00:00Z",
  "type": "task_progress",
  "human_readable_message": "Preparing the daily briefing",
  "structured_payload": {}
}
```

## Event types

| Type | Meaning |
| --- | --- |
| `task_created` | Task accepted and persisted. |
| `task_understanding` | Deterministic intent/profile classification. |
| `task_planning` | Structured planning started. |
| `plan_ready` | Ordered plan is available. |
| `model_selected` | Router chose a primary and fallbacks. |
| `model_fallback` | Runtime advanced to a bounded fallback. |
| `task_progress` | Concise execution progress. |
| `agent_activity` | Legacy generic activity signal; Phase 6 uses explicit agent events. |
| `tool_selected` / `tool_permission_check` | Registry selection and concrete permission decision. |
| `tool_started` / `tool_progress` / `tool_completed` | Real bounded tool lifecycle. |
| `tool_failed` / `tool_retry` | Truthful failure and bounded alternative attempt. |
| `terminal_started` / `terminal_output` | Controlled command and bounded output activity. |
| `browser_opened` / `browser_action` | Semantic Playwright activity. |
| `file_changed` / `git_changed` | Controlled local change evidence. |
| `test_started` / `test_passed` / `test_failed` | Real test/build verification progress. |
| `verification_evidence` | Typed evidence added to the task bundle. |
| `mcp_connected` / `mcp_tool_invoked` | Restricted MCP lifecycle. |
| `memory_retrieved` / `memory_created` / `memory_updated` | Scoped memory read and observable mutation. |
| `memory_superseded` / `memory_forgotten` / `memory_consolidated` | Correction, hard deletion by identifier, and verified operational consolidation. |
| `skill_matched` / `skill_created` / `skill_testing` | Existing procedure selection and controlled candidate lifecycle. |
| `skill_promoted` / `skill_failed` / `skill_updated` | Evidence-based promotion, truthful failure, and versioned update. |
| `agent_created` / `agent_testing` / `agent_ready` | Declarative agent factory lifecycle. |
| `agent_started` / `agent_delegated` / `agent_completed` | Bounded mission execution through the central runtime. |
| `agent_paused` / `agent_failed` | Persisted agent lifecycle interruption or failure. |
| `lesson_created` / `learning_applied` | Evidence-bound generalized lesson and later reuse. |
| `integration_connected` / `integration_disconnected` / `integration_error` | External provider lifecycle and health. |
| `email_searched` / `email_read` / `email_drafted` / `email_sent` / `email_verified` | Permission-aware email lifecycle with provider evidence. |
| `contact_resolved` / `contact_ambiguous` / `crm_updated` | Identity resolution and persistent internal CRM changes. |
| `lead_researched` / `lead_qualified` / `outreach_drafted` / `outreach_sent` / `reply_detected` | Evidence-bound agency operating loop. |
| `calendar_read` / `availability_checked` / `meeting_created` / `meeting_verified` | Calendar/meeting lifecycle and provider verification. |
| `briefing_generated` | Source-aware morning/daily briefing produced. |
| `automation_created` / `automation_scheduled` / `automation_started` / `automation_paused` / `automation_resumed` / `automation_completed` / `automation_failed` | Durable bounded background workflow lifecycle. |
| `visualization_requested` | Payload contains a validated UI composition for the existing Composer. |
| `approval_required` | L2/L3 task persisted and paused. |
| `verification_started` | Result checks began. |
| `verification_passed` / `verification_failed` | Verification evidence and score. |
| `task_completed` | Persisted verified result and user response. |
| `task_failed` | Terminal failure with truthful error. |
| `task_cancelled` | User/runtime cancellation completed. |
| `research_started` / `research_plan_ready` / `source_discovered` / `source_read` / `claim_extracted` / `contradiction_found` / `research_verified` | Phase 8 deep research lifecycle. |
| `capability_gap_detected` / `api_discovered` / `mcp_discovered` / `saas_discovered` | Phase 8 discovery lifecycle. |
| `booking_search_started` / `booking_option_found` / `booking_approval_required` / `booking_confirmed` | Phase 8 booking lifecycle. |
| `artifact_started` / `artifact_rendered` / `artifact_validation_failed` / `artifact_verified` | Phase 8 artifact generation/validation lifecycle. |
| `delivery_package_ready` / `delivery_approval_required` / `delivery_sent` / `delivery_verified` | Phase 8 client delivery lifecycle. |
| `desktop_startup_enabled` / `desktop_startup_disabled` | Phase 9 launch-at-login preference changed. |
| `app_opened` / `app_focused` / `app_closed` | Phase 9 application lifecycle. |
| `window_focused` / `window_moved` | Phase 9 native window operations. |
| `clipboard_read` / `clipboard_written` | Phase 9 deliberate clipboard access. |
| `screen_captured` / `screen_observed` | Phase 9 on-request screen capture and structured observation. |
| `accessibility_action` / `mouse_action` / `keyboard_action` | Phase 9 input control, accessibility-first with bounded fallback. |
| `desktop_action_verified` / `desktop_action_failed` | Phase 9 post-action verification outcome. |
| `device_connected` / `device_disconnected` | Phase 9 device node online/offline transitions. |
| `device_command_started` / `device_command_completed` | Phase 9 device command routing lifecycle. |
| `emergency_pause` | Phase 9 safety stop engaged; takes priority over normal execution. |
| `market_data_requested` / `market_data_received` / `market_data_stale` | Phase 10 market-data fetch lifecycle and freshness outcome. |
| `market_research_started` / `market_thesis_ready` | Phase 10 catalyst/research lifecycle and evidence-backed thesis availability. |
| `trade_setup_created` / `trade_setup_rejected` | Phase 10 structured setup construction and Risk Engine rejection. |
| `risk_check_started` / `risk_check_passed` / `risk_check_failed` | Phase 10 Risk Engine evaluation lifecycle (PASS/REDUCE/REJECT). |
| `paper_order_created` / `paper_order_filled` / `paper_order_cancelled` | Phase 10 simulated PAPER order lifecycle. |
| `paper_position_opened` / `paper_position_closed` | Phase 10 simulated PAPER position lifecycle. |
| `backtest_started` / `backtest_completed` / `backtest_failed` | Phase 10 deterministic historical simulation lifecycle. |
| `strategy_created` / `strategy_validated` | Phase 10 structured `StrategySpec` lifecycle. |
| `market_alert_triggered` | Phase 10 deterministic alert condition fired (cooldown-respecting). |
| `paper_trading_paused` | Phase 10 paper kill switch engaged; affects only PAPER records. |
| `risk_kill_switch_triggered` | Phase 10 automatic pause of new PAPER entries on a hard risk-limit breach. |
| `goal_created` / `goal_updated` / `goal_completed` / `goal_blocked` | Phase 11 goal lifecycle. |
| `habit_created` / `habit_event_recorded` / `habit_pattern_detected` / `habit_insight_created` | Phase 11 habit tracking and evidence-gated pattern/insight lifecycle. |
| `routine_started` / `routine_completed` / `routine_missed` | Phase 11 routine run lifecycle. |
| `focus_started` / `focus_paused` / `focus_completed` | Phase 11 focus session lifecycle. |
| `commitment_created` / `commitment_due` / `commitment_completed` | Phase 11 commitment lifecycle. |
| `daily_plan_created` / `morning_briefing_ready` / `evening_review_ready` / `weekly_review_ready` | Phase 11 planning/review generation lifecycle. |
| `proactive_suggestion_created` / `proactive_suggestion_suppressed` | Phase 11 proactive gate outcome, with a concrete reason when suppressed. |
| `notification_batched` | Phase 11 minor notifications grouped into one batch. |
| `quiet_mode_started` / `quiet_mode_ended` | Phase 11 explicit quiet-mode window lifecycle. |
| `node_registered` / `node_authenticated` / `node_revoked` | Phase 12 node lifecycle; authentication and revocation are always explicit. |
| `node_online` / `node_offline` | Phase 12 presence transitions from heartbeats. |
| `task_dispatched` | Phase 12 placement of a task onto a node (lease acquired). |
| `task_handoff_started` / `task_handoff_completed` | Phase 12 portable-task handoff between nodes; non-portable tasks report waiting honestly. |
| `task_lease_expired` | Phase 12 lease expiry; the coordinator then decides safe handoff or waiting. |
| `sync_started` / `sync_completed` / `sync_conflict` | Phase 12 journal pull lifecycle; conflicts carry the explicit resolution. |
| `offline_command_queued` / `offline_command_expired` | Phase 12 offline queue; expired consequential commands never execute. |
| `backup_started` / `backup_completed` / `backup_failed` / `restore_started` / `restore_completed` | Phase 12 backup/restore lifecycle. |
| `health_degraded` / `worker_recovered` | Phase 12 reliability transitions from real component checks. |
| `circuit_breaker_opened` | Phase 12 breaker opened for a provider/tool/MCP/integration/network key. |
| `mobile_approval_received` / `remote_command_received` | Phase 12 remote-device interactions (accepted or rejected, with reason). |

`visualization_requested.structured_payload.composition` uses the desktop's versioned `UIComposition` contract. Unknown event types or unsupported composition versions must be ignored safely by the desktop.

Tool events contain concise input/output summaries only. Raw secrets, unrestricted terminal streams, private model reasoning, and unbounded page content are never broadcast.

## Phase 13

Production/observability events reuse the existing protocol; new
behavioral events (health degraded, circuit breaker opened, backup /
restore lifecycle, remote command/approval traffic) were added in
Phase 12. Phase 13 adds no new event types — it adds correlation IDs
(request/trace) as cross-cutting envelope metadata available to every
consumer via headers and log fields.
