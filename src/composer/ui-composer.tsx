import { memo } from "react";
import type { CSSProperties, ReactNode } from "react";
import {
  Activity,
  Bot,
  Brain,
  Braces,
  Check,
  CheckCircle2,
  CircleAlert,
  GitBranch,
  LineChart as LineChartIcon,
  Network,
  Monitor,
  SquareTerminal,
  Route,
  Sparkles,
  Timer,
  Workflow,
  Mail,
  Building2,
  Send,
  Clock3,
  Compass,
  Gauge,
  ScrollText,
  GitCompareArrows,
  Table2,
  FileStack,
  PackageCheck,
  AppWindow,
  Camera,
  Laptop2,
  TrendingUp,
  Target,
  ShieldAlert,
  ListChecks,
  ListOrdered,
  Flag,
  Repeat,
} from "lucide-react";
import type {
  AgentStatusObject,
  ApprovalActionObject,
  CausalDiagramObject,
  ComposerPhase,
  LineChartObject,
  MetricObject,
  ModelRoutingObject,
  PipelineFunnelObject,
  StatusSummaryObject,
  SurfaceTone,
  TimelineObject,
  UIComposition,
  UIObject,
  VerifiedResultObject,
  BrowserPreviewObject,
  CodeDiffObject,
  TaskMissionObject,
  TerminalOutputObject,
  MemoryClusterObject,
  BrainGraphObject,
  SkillProcedureObject,
  EmailThreadObject,
  LeadProfileObject,
  OutreachMessageObject,
  AutomationStatusObject,
  ResearchMapObject,
  ConfidenceIndicatorObject,
  EvidenceCardGroupObject,
  ContradictionPanelObject,
  ComparisonTableObject,
  ArtifactPreviewObject,
  DeliveryManifestObject,
  NativeAppStatusObject,
  ScreenshotPreviewObject,
  DeviceNodeObject,
  PriceChartObject,
  TradeSetupObject,
  RiskPanelObject,
  EquityCurveObject,
  DailyPlanTimelineObject,
  PriorityStackObject,
  GoalProgressPathObject,
  HabitTrendObject,
  RoutineSequenceObject,
  FocusMissionObject,
} from "./ui-schema";

type UIComposerProps = {
  composition: UIComposition | null;
  visibleObjectIds: string[];
  phase: ComposerPhase;
};

const iconByType: Record<UIObject["type"], ReactNode> = {
  "status-summary": <Sparkles size={13} />,
  "agent-status": <Bot size={13} />,
  "approval-action": <CircleAlert size={13} />,
  metric: <Activity size={13} />,
  "line-chart": <LineChartIcon size={13} />,
  "pipeline-funnel": <GitBranch size={13} />,
  timeline: <Timer size={13} />,
  "verified-result": <CheckCircle2 size={13} />,
  "causal-diagram": <Route size={13} />,
  "model-routing": <Network size={13} />,
  "task-mission": <Bot size={13} />,
  "terminal-output": <SquareTerminal size={13} />,
  "code-diff": <Braces size={13} />,
  "browser-preview": <Monitor size={13} />,
  "memory-cluster": <Brain size={13} />,
  "brain-graph": <Network size={13} />,
  "skill-procedure": <Workflow size={13} />,
  "email-thread": <Mail size={13} />,
  "lead-profile": <Building2 size={13} />,
  "outreach-message": <Send size={13} />,
  "automation-status": <Clock3 size={13} />,
  "research-map": <Compass size={13} />,
  "confidence-indicator": <Gauge size={13} />,
  "evidence-card-group": <ScrollText size={13} />,
  "contradiction-panel": <GitCompareArrows size={13} />,
  "comparison-table": <Table2 size={13} />,
  "artifact-preview": <FileStack size={13} />,
  "delivery-manifest": <PackageCheck size={13} />,
  "native-app-status": <AppWindow size={13} />,
  "screenshot-preview": <Camera size={13} />,
  "device-node": <Laptop2 size={13} />,
  "price-chart": <TrendingUp size={13} />,
  "trade-setup": <Target size={13} />,
  "risk-panel": <ShieldAlert size={13} />,
  "equity-curve": <TrendingUp size={13} />,
  "daily-plan-timeline": <ListChecks size={13} />,
  "priority-stack": <ListOrdered size={13} />,
  "goal-progress-path": <Flag size={13} />,
  "habit-trend": <Repeat size={13} />,
  "routine-sequence": <ListOrdered size={13} />,
  "focus-mission": <Target size={13} />,
};

function toneClass(tone: SurfaceTone | undefined) {
  return `tone-${tone ?? "neutral"}`;
}

function formatGeneratedAt(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(parsed);
}

function Surface({ object, children }: { object: UIObject; children: ReactNode }) {
  const style = {
    "--surface-x": `${object.frame.x}%`,
    "--surface-y": `${object.frame.y}%`,
    "--surface-width": `${object.frame.width}%`,
    zIndex: object.frame.layer ?? 1,
  } as CSSProperties;

  return (
    <article
      className={`ui-object ui-object-${object.type} ${toneClass(object.tone)}`}
      data-object-id={object.id}
      data-object-type={object.type}
      style={style}
    >
      <span className="surface-anchor" aria-hidden="true" />
      <header className="surface-header">
        <span className="surface-icon" aria-hidden="true">{iconByType[object.type]}</span>
        <span className="surface-heading">
          {object.eyebrow && <span>{object.eyebrow}</span>}
          <strong>{object.title}</strong>
        </span>
      </header>
      <div className="surface-content">{children}</div>
      <span className="surface-scan" aria-hidden="true" />
    </article>
  );
}

function StatusSummary({ object }: { object: StatusSummaryObject }) {
  return (
    <Surface object={object}>
      <p className="summary-focus">{object.focus}</p>
      <div className="summary-stats">
        {object.stats.map((stat) => (
          <div className={toneClass(stat.tone)} key={stat.label}>
            <strong>{stat.value}</strong>
            <span>{stat.label}</span>
          </div>
        ))}
      </div>
    </Surface>
  );
}

function AgentStatus({ object }: { object: AgentStatusObject }) {
  return (
    <Surface object={object}>
      <div className="agent-identity-row">
        <span className={`agent-presence status-${object.status}`}><i /></span>
        <div>
          <strong>{object.agent}</strong>
          <span>{object.role}</span>
        </div>
        <small>{object.status}</small>
      </div>
      <p className="agent-mission">{object.mission}</p>
      <div className="progress-track" aria-label={`${object.progress}% complete`}>
        <span style={{ width: `${object.progress}%` }} />
      </div>
      <div className="agent-meta">
        <span>{object.progress}%</span>
        {object.model && <span>{object.model}</span>}
      </div>
      <p className="latest-action"><i />{object.latestAction}</p>
    </Surface>
  );
}

function ApprovalAction({ object }: { object: ApprovalActionObject }) {
  return (
    <Surface object={object}>
      <p className="approval-request">{object.request}</p>
      <p className="approval-context">{object.context}</p>
      <div className="approval-footer">
        <span className={`urgency urgency-${object.urgency}`}>{object.urgency}</span>
        <span className="approval-call">{object.actionLabel}<span aria-hidden="true">↗</span></span>
      </div>
    </Surface>
  );
}

function pointsFor(values: number[], width = 240, height = 64, range?: [number, number]) {
  const minimum = range?.[0] ?? Math.min(...values);
  const maximum = range?.[1] ?? Math.max(...values);
  const spread = Math.max(maximum - minimum, 1);
  return values
    .map((value, index) => {
      const x = values.length === 1 ? width / 2 : (index / (values.length - 1)) * width;
      const y = height - ((value - minimum) / spread) * (height - 8) - 4;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function Sparkline({ values }: { values: number[] }) {
  return (
    <svg className="metric-spark" viewBox="0 0 120 34" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={pointsFor(values, 120, 34)} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Metric({ object }: { object: MetricObject }) {
  return (
    <Surface object={object}>
      <div className="metric-reading">
        <div>
          <span>{object.label}</span>
          <strong>{object.value}</strong>
        </div>
        {object.spark && <Sparkline values={object.spark} />}
      </div>
      <div className="metric-caption">
        {object.delta && <span>{object.delta}</span>}
        {object.caption && <small>{object.caption}</small>}
      </div>
    </Surface>
  );
}

function LineChart({ object }: { object: LineChartObject }) {
  const values = object.series.flatMap((series) => series.values);
  const range: [number, number] = [Math.min(...values), Math.max(...values)];
  const latestValues = object.series.map((series) => series.values.at(-1) ?? 0);

  return (
    <Surface object={object}>
      <div className="chart-legend">
        {object.series.map((series, index) => (
          <span key={series.label} style={{ "--series-color": series.color ?? (index === 0 ? "#9adbd5" : "#7eaaa1") } as CSSProperties}>
            <i />{series.label}<strong>{latestValues[index].toLocaleString()}{object.unit ?? ""}</strong>
          </span>
        ))}
      </div>
      <svg className="line-chart" viewBox="0 0 240 72" preserveAspectRatio="none" role="img" aria-label={object.title}>
        <path className="chart-grid" d="M0 16H240 M0 36H240 M0 56H240" />
        {object.series.map((series, index) => (
          <polyline
            key={series.label}
            points={pointsFor(series.values, 240, 68, range)}
            style={{ "--series-color": series.color ?? (index === 0 ? "#9adbd5" : "#7eaaa1") } as CSSProperties}
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      <div className="chart-labels">
        <span>{object.labels[0]}</span>
        <span>{object.labels[Math.floor(object.labels.length / 2)]}</span>
        <span>{object.labels.at(-1)}</span>
      </div>
    </Surface>
  );
}

function PipelineFunnel({ object }: { object: PipelineFunnelObject }) {
  const maximum = Math.max(...object.stages.map((stage) => stage.value), 1);

  return (
    <Surface object={object}>
      <div className="funnel-stages">
        {object.stages.map((stage) => (
          <div className="funnel-stage" key={stage.label}>
            <div className="funnel-label">
              <span>{stage.label}</span>
              <strong>{stage.value}</strong>
              {stage.detail && <small>{stage.detail}</small>}
            </div>
            <div className="funnel-track">
              <span style={{ width: `${Math.max((stage.value / maximum) * 100, 8)}%` }} />
            </div>
          </div>
        ))}
      </div>
    </Surface>
  );
}

function Timeline({ object }: { object: TimelineObject }) {
  return (
    <Surface object={object}>
      <div className="timeline-events">
        {object.events.map((event) => (
          <div className={`timeline-event event-${event.status ?? "upcoming"}`} key={`${event.time}-${event.title}`}>
            <span className="timeline-time">{event.time}</span>
            <i aria-hidden="true" />
            <div>
              <strong>{event.title}</strong>
              {event.meta && <small>{event.meta}</small>}
            </div>
          </div>
        ))}
      </div>
    </Surface>
  );
}

function VerifiedResult({ object }: { object: VerifiedResultObject }) {
  return (
    <Surface object={object}>
      <div className="verified-statement"><Check size={14} />{object.statement}</div>
      <div className="evidence-list">
        {object.evidence.map((evidence) => <span key={evidence}><i />{evidence}</span>)}
      </div>
      <small className="verified-time">{object.timestamp}</small>
    </Surface>
  );
}

function CausalDiagram({ object }: { object: CausalDiagramObject }) {
  return (
    <Surface object={object}>
      <div className="causal-flow">
        {object.nodes.map((node, index) => {
          const edge = object.edges.find((candidate) => candidate.from === node.id);
          return (
            <div className="causal-segment" key={node.id}>
              <div className={`causal-node ${toneClass(node.tone)}`}>
                <strong>{node.label}</strong>
                {node.detail && <span>{node.detail}</span>}
              </div>
              {index < object.nodes.length - 1 && (
                <div className="causal-edge">
                  {edge?.label && <small>{edge.label}</small>}
                  <i />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Surface>
  );
}

function ModelRouting({ object }: { object: ModelRoutingObject }) {
  return (
    <Surface object={object}>
      <div className="routing-model">
        <div><span>Model</span><strong>{object.model}</strong></div>
        <small>{object.provider}</small>
      </div>
      <p className="routing-reason">{object.reason}</p>
      <div className="routing-meta">
        {object.fallback && <span><i />Fallback<strong>{object.fallback}</strong></span>}
        {object.runtime && <span><i />Runtime<strong>{object.runtime}</strong></span>}
        {object.cost && <span><i />Cost<strong>{object.cost}</strong></span>}
      </div>
    </Surface>
  );
}

function TaskMission({ object }: { object: TaskMissionObject }) {
  return (
    <Surface object={object}>
      <div className={`tool-status tool-status-${object.status}`}><i />{object.status}</div>
      <p className="tool-mission">{object.mission}</p>
      <div className="tool-detail-list">{object.details.map((detail) => <span key={detail}>{detail}</span>)}</div>
    </Surface>
  );
}

function TerminalOutput({ object }: { object: TerminalOutputObject }) {
  return (
    <Surface object={object}>
      <div className="terminal-command"><span>$</span>{object.command}<small>{object.exitCode == null ? "—" : `exit ${object.exitCode}`}</small></div>
      <pre className="tool-code-output">{object.output || "No output returned."}</pre>
    </Surface>
  );
}

function CodeDiff({ object }: { object: CodeDiffObject }) {
  return (
    <Surface object={object}>
      <div className="diff-path">{object.path}</div>
      <pre className="tool-code-output diff-output">{object.diff || "No tracked diff."}</pre>
    </Surface>
  );
}

function BrowserPreview({ object }: { object: BrowserPreviewObject }) {
  return (
    <Surface object={object}>
      <div className={`browser-verification browser-${object.status}`}><i />{object.status}</div>
      <p className="browser-title">{object.pageTitle || "Local application"}</p>
      <small className="browser-url">{object.url}</small>
      {object.screenshot && <span className="browser-evidence">Screenshot evidence captured</span>}
    </Surface>
  );
}

function MemoryCluster({ object }: { object: MemoryClusterObject }) {
  return (
    <Surface object={object}>
      <div className="memory-cluster">
        {object.nodes.map((node) => (
          <div className="memory-node" key={node.id}>
            <span className="memory-orbit" aria-hidden="true"><i /></span>
            <div>
              <small>{node.type}</small>
              <strong>{node.label}</strong>
            </div>
            <em>{Math.round(node.confidence * 100)}%</em>
          </div>
        ))}
      </div>
      {object.caption && <p className="memory-caption">{object.caption}</p>}
    </Surface>
  );
}

function BrainGraph({ object }: { object: BrainGraphObject }) {
  const visible = object.nodes.slice(0, 32);
  const positions = new Map(visible.map((node, index) => {
    if (node.id === object.rootId) return [node.id, { x: 50, y: 50 }];
    const ringIndex = index - (visible.some((item) => item.id === object.rootId) ? 1 : 0);
    const count = Math.max(visible.length - 1, 1);
    const angle = (ringIndex / count) * Math.PI * 2 - Math.PI / 2;
    const radius = ringIndex % 2 === 0 ? 36 : 27;
    return [node.id, { x: 50 + Math.cos(angle) * radius, y: 50 + Math.sin(angle) * radius }];
  }));
  return (
    <Surface object={object}>
      <div className="brain-graph-meta">
        <span>{object.totalNodes.toLocaleString()} entities</span>
        <span>{object.totalRelationships.toLocaleString()} links</span>
        <small>Showing {visible.length} nearest entities</small>
      </div>
      <div className="brain-graph-canvas" role="img" aria-label="VYOM persistent operating brain graph">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {object.edges.map((edge) => {
            const from = positions.get(edge.from); const to = positions.get(edge.to);
            if (!from || !to) return null;
            return <line key={`${edge.from}-${edge.to}-${edge.relation}`} x1={from.x} y1={from.y} x2={to.x} y2={to.y} className={edge.verified ? "verified" : ""} />;
          })}
        </svg>
        {visible.map((node) => {
          const point = positions.get(node.id)!;
          const core = node.id === object.rootId;
          return (
            <div key={node.id} className={`brain-graph-node${core ? " brain-graph-core" : ""}`}
              style={{ left: `${point.x}%`, top: `${point.y}%` }} title={`${node.kind}: ${node.label}`}>
              <i /><strong>{core ? "VYOM" : node.label}</strong><small>{node.kind}</small>
            </div>
          );
        })}
      </div>
    </Surface>
  );
}

function SkillProcedure({ object }: { object: SkillProcedureObject }) {
  return (
    <Surface object={object}>
      <div className="skill-meta">
        <span>v{object.version}</span>
        <strong>{object.status}</strong>
        <small>{object.permissions}</small>
      </div>
      <div className="skill-steps">
        {object.steps.map((step, index) => (
          <div className="skill-step" key={step.id}>
            <i>{String(index + 1).padStart(2, "0")}</i>
            <span><strong>{step.label.replace(/_/g, " ")}</strong><small>{step.capability}</small></span>
          </div>
        ))}
      </div>
      <div className="skill-reliability"><span style={{ width: `${object.successRate * 100}%` }} /></div>
    </Surface>
  );
}

function EmailThread({ object }: { object: EmailThreadObject }) {
  return (
    <Surface object={object}>
      <div className="business-meta"><span>{object.provider}</span><small>{object.threadId ?? "No thread selected"}</small></div>
      <div className="email-thread-list">
        {object.messages.map((message, index) => (
          <div className="email-thread-row" key={`${message.timestamp}-${index}`}>
            <span><strong>{message.sender}</strong><small>{message.timestamp}</small></span>
            <b>{message.subject}</b><p>{message.preview}</p>
          </div>
        ))}
        {!object.messages.length && <p className="business-empty">No messages matched.</p>}
      </div>
    </Surface>
  );
}

function LeadProfile({ object }: { object: LeadProfileObject }) {
  return (
    <Surface object={object}>
      <div className="lead-score"><strong>{object.score}</strong><span>/ 100</span><small>{object.state}</small></div>
      <p className="lead-domain">{object.domain}</p>
      <p className="lead-reason">{object.reason}</p>
      <div className="evidence-list">{object.evidence.map((item) => <span key={item}><i />{item}</span>)}</div>
    </Surface>
  );
}

function OutreachMessage({ object }: { object: OutreachMessageObject }) {
  return (
    <Surface object={object}>
      <div className="business-meta"><span>{object.status}</span><small>{object.draftId}</small></div>
      <p className="outreach-recipient">To · {object.recipients.join(", ")}</p>
      <pre className="outreach-body">{object.body}</pre>
      {object.requiresApproval && <div className="approval-note"><i />L2 approval required before send</div>}
    </Surface>
  );
}

function AutomationStatus({ object }: { object: AutomationStatusObject }) {
  return (
    <Surface object={object}>
      <div className="automation-state"><i /><strong>{object.status}</strong><small>{object.timezone}</small></div>
      <p className="automation-schedule">{object.schedule}</p>
      <div className="automation-detail"><span>Next run</span><strong>{object.nextRunAt ? formatGeneratedAt(object.nextRunAt) : "Event triggered"}</strong></div>
      {object.lastResult && <p className="automation-result">{object.lastResult}</p>}
    </Surface>
  );
}

function ResearchMap({ object }: { object: ResearchMapObject }) {
  return (
    <Surface object={object}>
      <p className="research-goal">{object.goal}</p>
      <div className="memory-cluster">
        {object.nodes.map((node) => (
          <div className="memory-node" key={node.id}>
            <span className="memory-orbit" aria-hidden="true"><i /></span>
            <div>
              <small>{node.type}</small>
              <strong>{node.label}</strong>
            </div>
            <em>{Math.round(node.confidence * 100)}%</em>
          </div>
        ))}
        {!object.nodes.length && <p className="business-empty">No sources were found.</p>}
      </div>
    </Surface>
  );
}

function ConfidenceIndicator({ object }: { object: ConfidenceIndicatorObject }) {
  return (
    <Surface object={object}>
      <div className="confidence-reading">
        <strong>{Math.round(object.score * 100)}%</strong>
        <span>{object.label}</span>
      </div>
      <div className="skill-reliability"><span style={{ width: `${Math.max(object.score * 100, 3)}%` }} /></div>
    </Surface>
  );
}

function EvidenceCardGroup({ object }: { object: EvidenceCardGroupObject }) {
  return (
    <Surface object={object}>
      <div className="evidence-card-list">
        {object.cards.map((card, index) => (
          <div className="evidence-card" key={`${card.statement}-${index}`}>
            <p>{card.statement}</p>
            <div className="evidence-card-footer">
              <span>{card.sources.length} source{card.sources.length === 1 ? "" : "s"}</span>
              <em>{Math.round(card.confidence * 100)}%</em>
            </div>
          </div>
        ))}
        {!object.cards.length && <p className="business-empty">No evidence-backed claims yet.</p>}
      </div>
    </Surface>
  );
}

function ContradictionPanel({ object }: { object: ContradictionPanelObject }) {
  return (
    <Surface object={object}>
      <div className="contradiction-list">
        {object.items.map((item, index) => (
          <div className="contradiction-item" key={`${item.claim}-${index}`}>
            <strong>{item.claim}</strong>
            <p>{item.difference}</p>
            <small>{item.recommendedInterpretation}</small>
          </div>
        ))}
      </div>
    </Surface>
  );
}

function ComparisonTable({ object }: { object: ComparisonTableObject }) {
  return (
    <Surface object={object}>
      <table className="comparison-table">
        <thead>
          <tr>{object.headers.map((header) => <th key={header}>{header}</th>)}</tr>
        </thead>
        <tbody>
          {object.rows.map((row, index) => (
            <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{String(cell)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </Surface>
  );
}

function ArtifactPreview({ object }: { object: ArtifactPreviewObject }) {
  return (
    <Surface object={object}>
      <div className={`browser-verification browser-${object.verified ? "verified" : "loading"}`}><i />{object.status}</div>
      <p className="browser-title">{object.artifactType}</p>
      {object.outputPath && <small className="browser-url">{object.outputPath}</small>}
    </Surface>
  );
}

function DeliveryManifest({ object }: { object: DeliveryManifestObject }) {
  return (
    <Surface object={object}>
      <div className="manifest-list">
        {object.entries.map((entry, index) => (
          <div className="manifest-row" key={`${entry.deliverable}-${index}`}>
            <span><strong>{entry.deliverable}</strong><small>{entry.version}</small></span>
            <em className={entry.verified ? "manifest-ok" : "manifest-pending"}>{entry.verified ? "verified" : "pending"}</em>
          </div>
        ))}
        {!object.entries.length && <p className="business-empty">No deliverables selected.</p>}
      </div>
      {object.qualityIssues.length > 0 && (
        <div className="evidence-list">
          {object.qualityIssues.map((issue) => <span key={issue}><i />{issue}</span>)}
        </div>
      )}
    </Surface>
  );
}

function NativeAppStatus({ object }: { object: NativeAppStatusObject }) {
  return (
    <Surface object={object}>
      <div className={`browser-verification browser-${object.running ? "verified" : "loading"}`}><i />{object.running ? "running" : "not running"}</div>
      <p className="browser-title">{object.appName}</p>
      <div className="automation-detail">
        <span>Integration</span>
        <strong>{object.integrationType}{object.pid ? ` · pid ${object.pid}` : ""}</strong>
      </div>
    </Surface>
  );
}

function ScreenshotPreview({ object }: { object: ScreenshotPreviewObject }) {
  return (
    <Surface object={object}>
      <div className={`browser-verification browser-${object.confidence > 0 ? "verified" : "loading"}`}><i />{Math.round(object.confidence * 100)}% confidence</div>
      <p className="browser-title">{object.activeWindow ?? "No active window identified"}</p>
      {object.activeApplication && <small className="browser-url">{object.activeApplication}</small>}
      {object.screenshotPath && <span className="browser-evidence">Screenshot evidence captured</span>}
    </Surface>
  );
}

function DeviceNode({ object }: { object: DeviceNodeObject }) {
  return (
    <Surface object={object}>
      <div className="business-meta"><span>{object.deviceType}</span><small>{object.trustLevel}</small></div>
      <div className={`automation-state`}><i /><strong>{object.online}</strong></div>
      <div className="evidence-list">{object.capabilities.map((capability) => <span key={capability}><i />{capability}</span>)}</div>
    </Surface>
  );
}

function PriceChart({ object }: { object: PriceChartObject }) {
  const closes = object.candles.map((candle) => candle[4]);
  const latest = closes.at(-1);
  const high = closes.length ? Math.max(...closes) : undefined;
  const low = closes.length ? Math.min(...closes) : undefined;
  return (
    <Surface object={object}>
      <div className="metric-reading">
        <div>
          <span>Latest close</span>
          <strong>{latest !== undefined ? latest.toFixed(2) : "n/a"}</strong>
        </div>
        {closes.length > 1 && <Sparkline values={closes} />}
      </div>
      <div className="metric-caption">
        {high !== undefined && low !== undefined && <span>Range {low.toFixed(2)} – {high.toFixed(2)}</span>}
        {object.indicators && (
          <small>
            {Object.entries(object.indicators)
              .filter(([, value]) => value !== null && value !== undefined)
              .map(([key, value]) => `${key}: ${Number(value).toFixed(2)}`)
              .join(" · ")}
          </small>
        )}
      </div>
    </Surface>
  );
}

function TradeSetup({ object }: { object: TradeSetupObject }) {
  return (
    <Surface object={object}>
      <div className="business-meta"><span>{object.label}</span><small>{Math.round(object.confidence * 100)}% confidence</small></div>
      <div className="evidence-list">
        <span><i />Entry {object.entryZone.join(" – ")}</span>
        <span><i />Stop {object.stop}</span>
        {object.targets.length > 0 && <span><i />Targets {object.targets.join(", ")}</span>}
        {object.riskReward != null && <span><i />R:R {object.riskReward}</span>}
      </div>
      <p className="business-empty">{object.invalidation}</p>
    </Surface>
  );
}

function RiskPanel({ object }: { object: RiskPanelObject }) {
  return (
    <Surface object={object}>
      <div className="metric-reading">
        <div>
          <span>Risk % of equity</span>
          <strong>{object.riskPctOfEquity.toFixed(2)}%</strong>
        </div>
      </div>
      <div className="evidence-list">
        {object.reasons.length
          ? object.reasons.map((reason, index) => <span key={index}><i />{reason}</span>)
          : <span><i />Within configured limits</span>}
      </div>
    </Surface>
  );
}

function EquityCurve({ object }: { object: EquityCurveObject }) {
  const values = object.equityCurve.map(([, value]) => value);
  return (
    <Surface object={object}>
      {values.length > 1 && <Sparkline values={values} />}
      <div className="evidence-list">
        {object.integrityNotes.slice(0, 2).map((note, index) => <span key={index}><i />{note}</span>)}
      </div>
    </Surface>
  );
}

function DailyPlanTimeline({ object }: { object: DailyPlanTimelineObject }) {
  return (
    <Surface object={object}>
      <table className="comparison-table">
        <tbody>
          {object.rows.map(([label, score, reasons], index) => (
            <tr key={index}>
              <td>{label}</td>
              <td>{score}</td>
              <td>{reasons}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Surface>
  );
}

function PriorityStack({ object }: { object: PriorityStackObject }) {
  return (
    <Surface object={object}>
      <div className="evidence-list">
        {object.items.map((item, index) => <span key={index}><i />{item}</span>)}
      </div>
    </Surface>
  );
}

function GoalProgressPath({ object }: { object: GoalProgressPathObject }) {
  return (
    <Surface object={object}>
      {object.progress != null && (
        <div className="skill-reliability"><span style={{ width: `${Math.max(object.progress * 100, 3)}%` }} /></div>
      )}
      <div className="timeline-events">
        {object.milestones.map((milestone, index) => (
          <div className={`timeline-event event-${milestone.status === "done" ? "complete" : milestone.status === "in_progress" ? "active" : "upcoming"}`} key={index}>
            <i aria-hidden="true" />
            <div><strong>{milestone.title}</strong></div>
          </div>
        ))}
      </div>
      {object.nextAction && <p className="business-empty">Next: {object.nextAction}</p>}
    </Surface>
  );
}

function HabitTrend({ object }: { object: HabitTrendObject }) {
  return (
    <Surface object={object}>
      {object.consistencyPct != null && (
        <div className="metric-reading">
          <div><span>Consistency</span><strong>{object.consistencyPct}%</strong></div>
        </div>
      )}
      <p className="business-empty">{object.message}</p>
      {object.intervention && <div className="evidence-list"><span><i />{object.intervention}</span></div>}
    </Surface>
  );
}

function RoutineSequence({ object }: { object: RoutineSequenceObject }) {
  return (
    <Surface object={object}>
      <div className="timeline-events">
        {object.steps.map((step, index) => (
          <div className={`timeline-event event-${step.status === "completed" ? "complete" : step.status === "failed" ? "upcoming" : "active"}`} key={index}>
            <i aria-hidden="true" />
            <div><strong>{step.type}</strong><small>{step.detail || step.status}</small></div>
          </div>
        ))}
      </div>
    </Surface>
  );
}

function FocusMission({ object }: { object: FocusMissionObject }) {
  return (
    <Surface object={object}>
      <div className={`automation-state`}><i /><strong>{object.status}</strong></div>
      <p className="business-empty">Session {object.sessionId}</p>
    </Surface>
  );
}

function ObjectRenderer({ object }: { object: UIObject }) {
  switch (object.type) {
    case "status-summary": return <StatusSummary object={object} />;
    case "agent-status": return <AgentStatus object={object} />;
    case "approval-action": return <ApprovalAction object={object} />;
    case "metric": return <Metric object={object} />;
    case "line-chart": return <LineChart object={object} />;
    case "pipeline-funnel": return <PipelineFunnel object={object} />;
    case "timeline": return <Timeline object={object} />;
    case "verified-result": return <VerifiedResult object={object} />;
    case "causal-diagram": return <CausalDiagram object={object} />;
    case "model-routing": return <ModelRouting object={object} />;
    case "task-mission": return <TaskMission object={object} />;
    case "terminal-output": return <TerminalOutput object={object} />;
    case "code-diff": return <CodeDiff object={object} />;
    case "browser-preview": return <BrowserPreview object={object} />;
    case "memory-cluster": return <MemoryCluster object={object} />;
    case "brain-graph": return <BrainGraph object={object} />;
    case "skill-procedure": return <SkillProcedure object={object} />;
    case "email-thread": return <EmailThread object={object} />;
    case "lead-profile": return <LeadProfile object={object} />;
    case "outreach-message": return <OutreachMessage object={object} />;
    case "automation-status": return <AutomationStatus object={object} />;
    case "research-map": return <ResearchMap object={object} />;
    case "confidence-indicator": return <ConfidenceIndicator object={object} />;
    case "evidence-card-group": return <EvidenceCardGroup object={object} />;
    case "contradiction-panel": return <ContradictionPanel object={object} />;
    case "comparison-table": return <ComparisonTable object={object} />;
    case "artifact-preview": return <ArtifactPreview object={object} />;
    case "delivery-manifest": return <DeliveryManifest object={object} />;
    case "native-app-status": return <NativeAppStatus object={object} />;
    case "screenshot-preview": return <ScreenshotPreview object={object} />;
    case "device-node": return <DeviceNode object={object} />;
    case "price-chart": return <PriceChart object={object} />;
    case "trade-setup": return <TradeSetup object={object} />;
    case "risk-panel": return <RiskPanel object={object} />;
    case "equity-curve": return <EquityCurve object={object} />;
    case "daily-plan-timeline": return <DailyPlanTimeline object={object} />;
    case "priority-stack": return <PriorityStack object={object} />;
    case "goal-progress-path": return <GoalProgressPath object={object} />;
    case "habit-trend": return <HabitTrend object={object} />;
    case "routine-sequence": return <RoutineSequence object={object} />;
    case "focus-mission": return <FocusMission object={object} />;
  }
}

// The Brain's WebSocket stream can deliver many events per second during
// an active mission, and the parent runtime hook updates several other
// pieces of state (operational message, VYOM Core state, connection
// status, ...) on most of them. Composition/visibleObjectIds/phase only
// actually change when the visible workspace itself changes, so memo
// skips re-rendering this (large, nested) tree on every unrelated parent
// re-render - it only re-renders when one of its own props changes.
export const UIComposer = memo(function UIComposer({ composition, visibleObjectIds, phase }: UIComposerProps) {
  if (!composition) return null;
  const visible = new Set(visibleObjectIds);

  return (
    <section
      className={`ui-composer composer-${phase} composer-mode-${composition.mode}`}
      aria-label={`${composition.label} generated workspace`}
      data-composition={composition.mode}
    >
      <div className="composition-label">
        <span><i />{composition.label}</span>
        <small>{formatGeneratedAt(composition.generatedAt)}</small>
      </div>
      <div className="composition-axis" aria-hidden="true"><span /><i /><span /></div>
      {composition.objects.filter((object) => visible.has(object.id)).map((object) => (
        <ObjectRenderer key={`${composition.id}-${object.id}`} object={object} />
      ))}
    </section>
  );
});
