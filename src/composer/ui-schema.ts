import type { VyomState } from "@/core/vyom-state";

export type UIObjectType =
  | "status-summary"
  | "agent-status"
  | "approval-action"
  | "metric"
  | "line-chart"
  | "pipeline-funnel"
  | "timeline"
  | "verified-result"
  | "causal-diagram"
  | "model-routing"
  | "task-mission"
  | "terminal-output"
  | "code-diff"
  | "browser-preview"
  | "memory-cluster"
  | "skill-procedure"
  | "email-thread"
  | "lead-profile"
  | "outreach-message"
  | "automation-status"
  | "research-map"
  | "confidence-indicator"
  | "evidence-card-group"
  | "contradiction-panel"
  | "comparison-table"
  | "artifact-preview"
  | "delivery-manifest"
  | "native-app-status"
  | "screenshot-preview"
  | "device-node"
  | "price-chart"
  | "trade-setup"
  | "risk-panel"
  | "equity-curve"
  | "daily-plan-timeline"
  | "priority-stack"
  | "goal-progress-path"
  | "habit-trend"
  | "routine-sequence"
  | "focus-mission";

export type SurfaceTone = "neutral" | "intelligence" | "attention" | "verified";

export type SurfaceFrame = {
  x: number;
  y: number;
  width: number;
  layer?: number;
};

type UIObjectBase<TType extends UIObjectType> = {
  id: string;
  type: TType;
  title: string;
  eyebrow?: string;
  tone?: SurfaceTone;
  frame: SurfaceFrame;
};

export type StatusSummaryObject = UIObjectBase<"status-summary"> & {
  focus: string;
  stats: Array<{
    label: string;
    value: string;
    tone?: SurfaceTone;
  }>;
};

export type AgentStatusObject = UIObjectBase<"agent-status"> & {
  agent: string;
  role: string;
  status: "active" | "waiting" | "verifying" | "complete";
  mission: string;
  progress: number;
  latestAction: string;
  model?: string;
  capabilities?: string[];
  tools?: string[];
  permissions?: string;
  modelPolicy?: Record<string, unknown>;
  performance?: Record<string, unknown>;
};

export type MemoryClusterObject = UIObjectBase<"memory-cluster"> & {
  nodes: Array<{
    id: string;
    label: string;
    type: string;
    confidence: number;
  }>;
  edges: Array<{ from: string; to: string; label?: string }>;
  caption?: string;
};

export type SkillProcedureObject = UIObjectBase<"skill-procedure"> & {
  version: string;
  status: string;
  steps: Array<{ id: string; label: string; capability: string }>;
  successRate: number;
  permissions: string;
};

export type ApprovalActionObject = UIObjectBase<"approval-action"> & {
  request: string;
  context: string;
  actionLabel: string;
  urgency: "normal" | "important";
};

export type MetricObject = UIObjectBase<"metric"> & {
  label: string;
  value: string;
  delta?: string;
  caption?: string;
  spark?: number[];
};

export type ChartSeries = {
  label: string;
  values: number[];
  color?: string;
};

export type LineChartObject = UIObjectBase<"line-chart"> & {
  labels: string[];
  series: ChartSeries[];
  unit?: string;
};

export type PipelineFunnelObject = UIObjectBase<"pipeline-funnel"> & {
  stages: Array<{
    label: string;
    value: number;
    detail?: string;
  }>;
};

export type TimelineObject = UIObjectBase<"timeline"> & {
  events: Array<{
    time: string;
    title: string;
    meta?: string;
    status?: "upcoming" | "active" | "complete";
  }>;
};

export type VerifiedResultObject = UIObjectBase<"verified-result"> & {
  statement: string;
  evidence: string[];
  timestamp: string;
};

export type CausalDiagramObject = UIObjectBase<"causal-diagram"> & {
  nodes: Array<{
    id: string;
    label: string;
    detail?: string;
    tone?: SurfaceTone;
  }>;
  edges: Array<{
    from: string;
    to: string;
    label?: string;
  }>;
};

export type ModelRoutingObject = UIObjectBase<"model-routing"> & {
  model: string;
  provider: string;
  reason: string;
  fallback?: string;
  runtime?: string;
  cost?: string;
};

export type TaskMissionObject = UIObjectBase<"task-mission"> & {
  mission: string;
  status: "active" | "complete" | "failed";
  details: string[];
};

export type TerminalOutputObject = UIObjectBase<"terminal-output"> & {
  command: string;
  exitCode?: number | null;
  output: string;
};

export type CodeDiffObject = UIObjectBase<"code-diff"> & {
  path: string;
  diff: string;
};

export type BrowserPreviewObject = UIObjectBase<"browser-preview"> & {
  url: string;
  pageTitle: string;
  screenshot?: string;
  status: "loading" | "verified" | "failed";
};

export type EmailThreadObject = UIObjectBase<"email-thread"> & {
  provider: string;
  threadId?: string | null;
  messages: Array<{ sender: string; subject: string; preview: string; timestamp: string }>;
};

export type LeadProfileObject = UIObjectBase<"lead-profile"> & {
  domain: string;
  state: string;
  score: number;
  reason: string;
  evidence: string[];
};

export type OutreachMessageObject = UIObjectBase<"outreach-message"> & {
  draftId: string;
  recipients: string[];
  body: string;
  status: string;
  requiresApproval: boolean;
};

export type AutomationStatusObject = UIObjectBase<"automation-status"> & {
  automationId: string;
  schedule: string;
  timezone: string;
  status: string;
  nextRunAt?: string | null;
  lastResult?: string | null;
};

export type ResearchMapObject = UIObjectBase<"research-map"> & {
  goal: string;
  nodes: Array<{
    id: string;
    label: string;
    type: string;
    confidence: number;
  }>;
};

export type ConfidenceIndicatorObject = UIObjectBase<"confidence-indicator"> & {
  score: number;
  label: string;
};

export type EvidenceCardGroupObject = UIObjectBase<"evidence-card-group"> & {
  cards: Array<{
    statement: string;
    confidence: number;
    sources: string[];
  }>;
};

export type ContradictionPanelObject = UIObjectBase<"contradiction-panel"> & {
  items: Array<{
    claim: string;
    difference: string;
    recommendedInterpretation: string;
  }>;
};

export type ComparisonTableObject = UIObjectBase<"comparison-table"> & {
  headers: string[];
  rows: Array<Array<string | number>>;
};

export type ArtifactPreviewObject = UIObjectBase<"artifact-preview"> & {
  artifactId: string;
  artifactType: string;
  outputPath?: string | null;
  status: string;
  verified: boolean;
};

export type DeliveryManifestObject = UIObjectBase<"delivery-manifest"> & {
  entries: Array<{
    deliverable: string;
    file: string;
    version: string;
    verified: boolean;
  }>;
  qualityIssues: string[];
};

export type NativeAppStatusObject = UIObjectBase<"native-app-status"> & {
  appId: string;
  appName: string;
  running: boolean;
  integrationType: string;
  pid?: number | null;
};

export type ScreenshotPreviewObject = UIObjectBase<"screenshot-preview"> & {
  screenshotPath?: string | null;
  activeWindow?: string | null;
  activeApplication?: string | null;
  confidence: number;
};

export type DeviceNodeObject = UIObjectBase<"device-node"> & {
  nodeId: string;
  deviceType: string;
  trustLevel: string;
  online: string;
  capabilities: string[];
};

export type PriceChartObject = UIObjectBase<"price-chart"> & {
  candles: Array<[string, number, number, number, number, number]>; // timestamp, open, high, low, close, volume
  indicators?: Record<string, number | null>;
};

export type TradeSetupObject = UIObjectBase<"trade-setup"> & {
  label: string; // always "PAPER" — simulation only, never live
  entryZone: number[];
  stop: number;
  targets: number[];
  riskReward?: number | null;
  maxRisk?: number | null;
  confidence: number;
  invalidation: string;
  dataTimestamp: string;
};

export type RiskPanelObject = UIObjectBase<"risk-panel"> & {
  reasons: string[];
  riskPctOfEquity: number;
  positionSize: number;
};

export type EquityCurveObject = UIObjectBase<"equity-curve"> & {
  equityCurve: Array<[number, number]>;
  metrics: Record<string, unknown>;
  integrityNotes: string[];
};

export type DailyPlanTimelineObject = UIObjectBase<"daily-plan-timeline"> & {
  rows: Array<[string, number, string]>; // label, score, reasons
};

export type PriorityStackObject = UIObjectBase<"priority-stack"> & {
  items: string[];
};

export type GoalProgressPathObject = UIObjectBase<"goal-progress-path"> & {
  milestones: Array<{ title: string; status: string }>;
  nextAction?: string | null;
  progress?: number | null;
};

export type HabitTrendObject = UIObjectBase<"habit-trend"> & {
  consistencyPct?: number | null;
  message: string;
  intervention?: string | null;
};

export type RoutineSequenceObject = UIObjectBase<"routine-sequence"> & {
  steps: Array<{ type: string; status: string; detail: string }>;
};

export type FocusMissionObject = UIObjectBase<"focus-mission"> & {
  sessionId: string;
  status: string;
};

export type UIObject =
  | StatusSummaryObject
  | AgentStatusObject
  | ApprovalActionObject
  | MetricObject
  | LineChartObject
  | PipelineFunnelObject
  | TimelineObject
  | VerifiedResultObject
  | CausalDiagramObject
  | ModelRoutingObject
  | TaskMissionObject
  | TerminalOutputObject
  | CodeDiffObject
  | BrowserPreviewObject
  | MemoryClusterObject
  | SkillProcedureObject
  | EmailThreadObject
  | LeadProfileObject
  | OutreachMessageObject
  | AutomationStatusObject
  | ResearchMapObject
  | ConfidenceIndicatorObject
  | EvidenceCardGroupObject
  | ContradictionPanelObject
  | ComparisonTableObject
  | ArtifactPreviewObject
  | DeliveryManifestObject
  | NativeAppStatusObject
  | ScreenshotPreviewObject
  | DeviceNodeObject
  | PriceChartObject
  | TradeSetupObject
  | RiskPanelObject
  | EquityCurveObject
  | DailyPlanTimelineObject
  | PriorityStackObject
  | GoalProgressPathObject
  | HabitTrendObject
  | RoutineSequenceObject
  | FocusMissionObject;

export type CompositionStep = {
  id: string;
  label: string;
  atMs: number;
  state: VyomState;
  objectIds: string[];
};

export type UIComposition = {
  schemaVersion: 1;
  id: string;
  mode: "daily-status" | "agency" | "developer" | "planning" | "routing" | "brain-context" | "tool-execution" | "coding";
  label: string;
  summary: string;
  generatedAt: string;
  objects: UIObject[];
  sequence: CompositionStep[];
};

export type ComposerPhase = "calm" | "composing" | "active" | "dismissing";

export function validateComposition(composition: UIComposition): UIComposition {
  const ids = new Set(composition.objects.map((object) => object.id));
  const sequencedIds = composition.sequence.flatMap((step) => step.objectIds);

  if (ids.size !== composition.objects.length) {
    throw new Error(`Composition ${composition.id} contains duplicate object ids.`);
  }

  sequencedIds.forEach((id) => {
    if (!ids.has(id)) throw new Error(`Composition ${composition.id} references missing object ${id}.`);
  });

  composition.objects.forEach((object) => {
    const { x, y, width } = object.frame;
    if (x < 0 || y < 0 || width <= 0 || x + width > 100) {
      throw new Error(`Composition ${composition.id} has an invalid frame for ${object.id}.`);
    }
  });

  return composition;
}
