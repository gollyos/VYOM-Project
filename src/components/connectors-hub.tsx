import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Cpu,
  ExternalLink,
  GitBranch,
  Globe,
  HardDrive,
  Key,
  Layers,
  Link2,
  Loader2,
  Mail,
  MessageSquare,
  Play,
  Plug,
  Plus,
  RefreshCw,
  Search,
  Server,
  Settings2,
  Shield,
  Sparkles,
  Terminal,
  Trash2,
  X,
  Zap,
} from "lucide-react";

const BRAIN = (import.meta.env.VITE_VYOM_BRAIN_URL as string | undefined) ?? "http://127.0.0.1:7788";

function apiBase() {
  return BRAIN.replace(/\/$/, "");
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, { signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error(`GET ${path} failed (${response.status})`);
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(30000),
  });
  const text = await response.text();
  let payload: unknown = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { raw: text };
  }
  if (!response.ok) {
    const detail = (payload as { detail?: string } | null)?.detail || `${path} failed (${response.status})`;
    throw new Error(String(detail));
  }
  return payload as T;
}

export interface ToolDef {
  id: string;
  name: string;
  display_name: string;
  description: string;
  category: string;
  risk_level: "low" | "medium" | "high";
  requires_approval: boolean;
  input_schema?: Record<string, any>;
}

export interface ConnectorItem {
  id: string;
  name: string;
  slug: string;
  description: string;
  icon: string;
  category: string;
  auth_type: string;
  capabilities: string[];
  permissions: string[];
  status: "connected" | "disconnected" | "error" | "disabled";
  installed: boolean;
  error?: string | null;
  tools: ToolDef[];
}

export interface AutomationItem {
  id: string;
  name: string;
  type: string;
  action: string;
  status: string;
  next_run_at?: string | null;
  run_count?: number;
  condition?: Record<string, any>;
}

export interface WorkflowRunItem {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: string;
  started_at: string;
  completed_at?: string | null;
  error?: string | null;
  step_runs: Array<{
    id: string;
    step_id: string;
    name: string;
    type: string;
    status: string;
    duration_ms: number;
    error?: string | null;
    output_data?: any;
  }>;
}

export function ConnectorsHub({ onClose }: { onClose: () => void }) {
  const [activeTab, setActiveTab] = useState<"marketplace" | "mcp" | "automations" | "runs">("marketplace");
  const [connectors, setConnectors] = useState<ConnectorItem[]>([]);
  const [automations, setAutomations] = useState<AutomationItem[]>([]);
  const [runs, setRuns] = useState<WorkflowRunItem[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Selected Connector for details / modal
  const [selectedConnector, setSelectedConnector] = useState<ConnectorItem | null>(null);
  const [connectingModal, setConnectingModal] = useState<ConnectorItem | null>(null);
  const [credentialInput, setCredentialInput] = useState<string>("");
  const [connectingBusy, setConnectingBusy] = useState(false);

  // Add Custom MCP Server Modal State
  const [showAddMcpModal, setShowAddMcpModal] = useState(false);
  const [mcpId, setMcpId] = useState("");
  const [mcpName, setMcpName] = useState("");
  const [mcpTransport, setMcpTransport] = useState("stdio");
  const [mcpCommand, setMcpCommand] = useState("");
  const [mcpArgs, setMcpArgs] = useState("");
  const [mcpTestResult, setMcpTestResult] = useState<any>(null);
  const [mcpTestBusy, setMcpTestBusy] = useState(false);

  // Natural Language Automation Prompt
  const [promptWorkflow, setPromptWorkflow] = useState("");
  const [promptGenerating, setPromptGenerating] = useState(false);
  const [generatedWorkflow, setGeneratedWorkflow] = useState<any>(null);

  const fetchAll = async () => {
    setLoading(true);
    setError(null);
    try {
      const [connRes, autoRes] = await Promise.all([
        getJson<{ connectors: ConnectorItem[] }>("/api/connectors").catch(() => ({ connectors: [] })),
        getJson<AutomationItem[]>("/api/automations").catch(() => []),
      ]);
      setConnectors(connRes.connectors || []);
      setAutomations(autoRes || []);
    } catch (err: any) {
      setError(err.message || "Failed to load marketplace data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchAll();
  }, []);

  const filteredConnectors = useMemo(() => {
    return connectors.filter((c) => {
      const matchSearch =
        c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        c.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
        c.category.toLowerCase().includes(searchQuery.toLowerCase());
      const matchCategory =
        categoryFilter === "all"
          ? true
          : categoryFilter === "installed"
          ? c.status === "connected"
          : c.category.toLowerCase() === categoryFilter.toLowerCase();
      return matchSearch && matchCategory;
    });
  }, [connectors, searchQuery, categoryFilter]);

  const handleConnect = async (connector: ConnectorItem) => {
    setConnectingBusy(true);
    try {
      await postJson(`/api/connectors/${connector.id}/connect`, {
        credentials: { token: credentialInput, api_key: credentialInput, address: credentialInput },
      });
      setConnectingModal(null);
      setCredentialInput("");
      await fetchAll();
    } catch (err: any) {
      setError(err.message || "Connection failed");
    } finally {
      setConnectingBusy(false);
    }
  };

  const handleDisconnect = async (connectorId: string) => {
    setLoading(true);
    try {
      await postJson(`/api/connectors/${connectorId}/disconnect`);
      await fetchAll();
    } catch (err: any) {
      setError(err.message || "Failed to disconnect");
    } finally {
      setLoading(false);
    }
  };

  const handleTestMcp = async () => {
    setMcpTestBusy(true);
    setMcpTestResult(null);
    try {
      const argsArray = mcpArgs
        .split(" ")
        .map((s) => s.trim())
        .filter(Boolean);
      const res = await postJson("/api/mcp/test-config", {
        id: mcpId || "custom-mcp",
        name: mcpName || "Custom MCP",
        transport: mcpTransport,
        command: mcpCommand,
        args: argsArray,
      });
      setMcpTestResult(res);
    } catch (err: any) {
      setMcpTestResult({ status: "error", error: err.message });
    } finally {
      setMcpTestBusy(false);
    }
  };

  const handleSaveMcp = async (e: FormEvent) => {
    e.preventDefault();
    setMcpTestBusy(true);
    try {
      const argsArray = mcpArgs
        .split(" ")
        .map((s) => s.trim())
        .filter(Boolean);
      await postJson("/api/mcp/servers", {
        id: mcpId.trim().toLowerCase().replace(/\s+/g, "-"),
        name: mcpName.trim(),
        transport: mcpTransport,
        command: mcpCommand.trim(),
        args: argsArray,
      });
      setShowAddMcpModal(false);
      setMcpId("");
      setMcpName("");
      setMcpCommand("");
      setMcpArgs("");
      setMcpTestResult(null);
      await fetchAll();
    } catch (err: any) {
      setError(err.message || "Failed to add MCP server");
    } finally {
      setMcpTestBusy(false);
    }
  };

  const handleGenerateWorkflow = async (e: FormEvent) => {
    e.preventDefault();
    if (!promptWorkflow.trim()) return;
    setPromptGenerating(true);
    try {
      const res = await postJson<any>("/api/automations/generate", { prompt: promptWorkflow });
      setGeneratedWorkflow(res);
    } catch (err: any) {
      setError(err.message || "Failed to generate workflow");
    } finally {
      setPromptGenerating(false);
    }
  };

  const handleCreateGeneratedAutomation = async () => {
    if (!generatedWorkflow) return;
    setLoading(true);
    try {
      await postJson("/api/automations", {
        name: generatedWorkflow.name,
        type: generatedWorkflow.trigger_type === "recurring" ? "recurring" : "one_time",
        action: "run_vyom_command",
        cron_expression: generatedWorkflow.cron_expression,
        interval_minutes: generatedWorkflow.interval_minutes,
        condition: { steps: generatedWorkflow.steps, command: generatedWorkflow.description },
        run_at: new Date(Date.now() + 60000).toISOString(),
      });
      setGeneratedWorkflow(null);
      setPromptWorkflow("");
      await fetchAll();
    } catch (err: any) {
      setError(err.message || "Failed to save automation");
    } finally {
      setLoading(false);
    }
  };

  const handleRunAutomation = async (automationId: string) => {
    try {
      const res = await postJson<WorkflowRunItem>(`/api/automations/${automationId}/run`, {});
      setRuns((prev) => [res, ...prev]);
      setActiveTab("runs");
    } catch (err: any) {
      setError(err.message || "Failed to trigger automation");
    }
  };

  return (
    <div className="hub-modal-overlay" role="dialog" aria-modal="true" aria-label="Vyom Connectors & Automation Hub">
      <div className="hub-window">
        {/* Top Header */}
        <header className="hub-header">
          <div className="hub-header-brand">
            <div className="hub-icon-pill">
              <Plug size={16} />
            </div>
            <div>
              <h2>Vyom Connectors & Automation Hub</h2>
              <p>Connect integrations, dynamically discover MCP tools, and build autonomous multi-step pipelines.</p>
            </div>
          </div>
          <div className="hub-header-actions">
            <button type="button" className="hub-btn-ghost" onClick={() => void fetchAll()} title="Refresh">
              <RefreshCw size={14} className={loading ? "hub-spin" : ""} />
            </button>
            <button type="button" className="hub-btn-close" onClick={onClose} aria-label="Close">
              <X size={16} />
            </button>
          </div>
        </header>

        {/* Navigation Tabs */}
        <nav className="hub-tabs">
          <button
            type="button"
            className={`hub-tab ${activeTab === "marketplace" ? "hub-tab-active" : ""}`}
            onClick={() => setActiveTab("marketplace")}
          >
            <Layers size={14} />
            <span>Marketplace</span>
            <span className="hub-badge">{connectors.length}</span>
          </button>
          <button
            type="button"
            className={`hub-tab ${activeTab === "mcp" ? "hub-tab-active" : ""}`}
            onClick={() => setActiveTab("mcp")}
          >
            <Server size={14} />
            <span>MCP Servers</span>
          </button>
          <button
            type="button"
            className={`hub-tab ${activeTab === "automations" ? "hub-tab-active" : ""}`}
            onClick={() => setActiveTab("automations")}
          >
            <Zap size={14} />
            <span>Workflows & Automations</span>
            <span className="hub-badge">{automations.length}</span>
          </button>
          <button
            type="button"
            className={`hub-tab ${activeTab === "runs" ? "hub-tab-active" : ""}`}
            onClick={() => setActiveTab("runs")}
          >
            <Activity size={14} />
            <span>Observability & Logs</span>
          </button>
        </nav>

        {/* Global Error Banner */}
        {error && (
          <div className="hub-error-banner">
            <AlertCircle size={14} />
            <span>{error}</span>
            <button type="button" onClick={() => setError(null)}>
              <X size={12} />
            </button>
          </div>
        )}

        {/* Tab Body */}
        <div className="hub-body">
          {/* 1. MARKETPLACE TAB */}
          {activeTab === "marketplace" && (
            <div className="hub-marketplace-view">
              <div className="hub-controls-bar">
                <div className="hub-search-box">
                  <Search size={14} />
                  <input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search connectors, MCP tools, capabilities..."
                  />
                </div>
                <div className="hub-category-pills">
                  {["all", "installed", "dev_tools", "communication", "productivity", "custom_mcp", "custom_rest"].map(
                    (cat) => (
                      <button
                        key={cat}
                        type="button"
                        className={`hub-pill ${categoryFilter === cat ? "hub-pill-active" : ""}`}
                        onClick={() => setCategoryFilter(cat)}
                      >
                        {cat === "all"
                          ? "All"
                          : cat === "installed"
                          ? "Installed"
                          : cat.replace("_", " ").replace(/\b\w/g, (l) => l.toUpperCase())}
                      </button>
                    )
                  )}
                </div>
                <button type="button" className="hub-btn-primary" onClick={() => setShowAddMcpModal(true)}>
                  <Plus size={14} />
                  <span>Add Custom MCP</span>
                </button>
              </div>

              <div className="hub-grid">
                {filteredConnectors.map((c) => {
                  const isConnected = c.status === "connected";
                  return (
                    <div key={c.id} className={`hub-card ${isConnected ? "hub-card-connected" : ""}`}>
                      <div className="hub-card-top">
                        <div className="hub-card-icon">
                          {c.id.includes("github") ? (
                            <GitBranch size={18} />
                          ) : c.id.includes("mail") ? (
                            <Mail size={18} />
                          ) : c.id.includes("calendar") ? (
                            <Clock size={18} />
                          ) : c.auth_type === "mcp" ? (
                            <Server size={18} />
                          ) : (
                            <Globe size={18} />
                          )}
                        </div>
                        <div className="hub-card-title-group">
                          <div className="hub-card-title-row">
                            <h4>{c.name}</h4>
                            <span className={`hub-status-tag tag-${c.status}`}>
                              {isConnected ? "Connected" : "Available"}
                            </span>
                          </div>
                          <span className="hub-category-tag">{c.category}</span>
                        </div>
                      </div>

                      <p className="hub-card-desc">{c.description}</p>

                      <div className="hub-card-meta">
                        <div className="hub-tool-count">
                          <Cpu size={12} />
                          <span>{c.tools.length} Tools</span>
                        </div>
                        <div className="hub-auth-tag">
                          <Key size={11} />
                          <span>{c.auth_type.toUpperCase()}</span>
                        </div>
                      </div>

                      <div className="hub-card-actions">
                        <button
                          type="button"
                          className="hub-btn-secondary"
                          onClick={() => setSelectedConnector(c)}
                        >
                          Tools ({c.tools.length})
                        </button>
                        {isConnected ? (
                          <button
                            type="button"
                            className="hub-btn-danger"
                            onClick={() => void handleDisconnect(c.id)}
                            disabled={loading}
                          >
                            Disconnect
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="hub-btn-connect"
                            onClick={() => setConnectingModal(c)}
                            disabled={loading}
                          >
                            Connect
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 2. MCP SERVERS TAB */}
          {activeTab === "mcp" && (
            <div className="hub-mcp-view">
              <div className="hub-section-header">
                <div>
                  <h3>Model Context Protocol (MCP) Servers</h3>
                  <p>Vyom dynamically connects to external MCP servers, discovering tool schemas and execution protocols JIT.</p>
                </div>
                <button type="button" className="hub-btn-primary" onClick={() => setShowAddMcpModal(true)}>
                  <Plus size={14} />
                  <span>Add MCP Server</span>
                </button>
              </div>

              <div className="hub-mcp-list">
                {connectors
                  .filter((c) => c.auth_type === "mcp" || c.id.startsWith("mcp"))
                  .map((m) => (
                    <div key={m.id} className="hub-mcp-row">
                      <div className="hub-mcp-row-info">
                        <Server size={18} />
                        <div>
                          <h4>{m.name}</h4>
                          <p>{m.description}</p>
                          <div className="hub-caps-row">
                            {m.tools.map((t) => (
                              <span key={t.id} className="hub-cap-chip">
                                {t.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                      <div className="hub-mcp-row-actions">
                        <span className={`hub-status-tag tag-${m.status}`}>{m.status}</span>
                        <button type="button" className="hub-btn-secondary" onClick={() => setSelectedConnector(m)}>
                          Inspect Schemas
                        </button>
                        <button
                          type="button"
                          className="hub-btn-danger"
                          onClick={() => void handleDisconnect(m.id)}
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* 3. AUTOMATIONS TAB */}
          {activeTab === "automations" && (
            <div className="hub-automations-view">
              {/* Natural Language Builder Bar */}
              <div className="hub-nl-box">
                <div className="hub-nl-header">
                  <Sparkles size={16} />
                  <h4>Natural Language Workflow Synthesizer</h4>
                </div>
                <p>Describe what you want Vyom to automate across your connected apps in plain English or Hinglish.</p>
                <form className="hub-nl-form" onSubmit={handleGenerateWorkflow}>
                  <input
                    value={promptWorkflow}
                    onChange={(e) => setPromptWorkflow(e.target.value)}
                    placeholder="e.g. Every weekday at 9 AM check my GitHub issues, summarize high priority ones and prepare an email digest"
                  />
                  <button type="submit" className="hub-btn-primary" disabled={promptGenerating || !promptWorkflow.trim()}>
                    {promptGenerating ? <Loader2 size={14} className="hub-spin" /> : <Sparkles size={14} />}
                    <span>Generate Pipeline</span>
                  </button>
                </form>

                {/* Generated Preview */}
                {generatedWorkflow && (
                  <div className="hub-generated-card">
                    <div className="hub-gen-top">
                      <div>
                        <h5>{generatedWorkflow.name}</h5>
                        <span className="hub-badge">Trigger: {generatedWorkflow.trigger_type}</span>
                        {generatedWorkflow.cron_expression && (
                          <span className="hub-badge">Cron: {generatedWorkflow.cron_expression}</span>
                        )}
                      </div>
                      <button type="button" className="hub-btn-primary" onClick={() => void handleCreateGeneratedAutomation()}>
                        <Check size={14} />
                        <span>Save & Enable Automation</span>
                      </button>
                    </div>

                    <div className="hub-steps-timeline">
                      {generatedWorkflow.steps.map((step: any, idx: number) => (
                        <div key={idx} className="hub-step-item">
                          <div className="hub-step-idx">{idx + 1}</div>
                          <div className="hub-step-content">
                            <strong>{step.name}</strong>
                            <span>Type: {step.type} {step.tool ? `· Tool: ${step.tool}` : ""}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Active Automations List */}
              <div className="hub-active-automations">
                <h3>Active Workflows ({automations.length})</h3>
                <div className="hub-auto-list">
                  {automations.map((a) => (
                    <div key={a.id} className="hub-auto-row">
                      <div className="hub-auto-info">
                        <Zap size={16} />
                        <div>
                          <h4>{a.name}</h4>
                          <p>
                            Trigger: <strong>{a.type}</strong> · Action: <code>{a.action}</code>
                          </p>
                        </div>
                      </div>
                      <div className="hub-auto-actions">
                        <button
                          type="button"
                          className="hub-btn-primary"
                          onClick={() => void handleRunAutomation(a.id)}
                        >
                          <Play size={12} />
                          <span>Run Now</span>
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* 4. OBSERVABILITY & RUN LOGS TAB */}
          {activeTab === "runs" && (
            <div className="hub-runs-view">
              <div className="hub-section-header">
                <div>
                  <h3>Execution Observability & Traces</h3>
                  <p>Step-by-step audit logs, execution duration, and tool results across all runs.</p>
                </div>
              </div>

              <div className="hub-runs-list">
                {runs.length === 0 ? (
                  <div className="hub-empty-state">
                    <Activity size={32} />
                    <p>No recent automation runs triggered yet. Click "Run Now" on any workflow to view real-time traces.</p>
                  </div>
                ) : (
                  runs.map((r) => (
                    <div key={r.id} className="hub-run-card">
                      <div className="hub-run-header">
                        <div>
                          <h4>{r.workflow_name}</h4>
                          <span className="hub-run-id">ID: {r.id}</span>
                        </div>
                        <span className={`hub-status-tag tag-${r.status}`}>{r.status.toUpperCase()}</span>
                      </div>

                      <div className="hub-run-steps">
                        {r.step_runs.map((s, idx) => (
                          <div key={s.id || idx} className="hub-run-step-row">
                            <div className="hub-step-dot" />
                            <div className="hub-step-details">
                              <div className="hub-step-header">
                                <strong>{s.name}</strong>
                                <span>{Math.round(s.duration_ms)}ms</span>
                              </div>
                              <span className="hub-step-type">Type: {s.type} · Status: {s.status}</span>
                              {s.output_data && (
                                <pre className="hub-step-output">{JSON.stringify(s.output_data, null, 2)}</pre>
                              )}
                              {s.error && <p className="hub-step-error">{s.error}</p>}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>

        {/* TOOL INSPECTION DRAWER / MODAL */}
        {selectedConnector && (
          <div className="hub-details-drawer" role="dialog" aria-modal="true">
            <div className="hub-drawer-content">
              <div className="hub-drawer-header">
                <div>
                  <h3>{selectedConnector.name} Tools</h3>
                  <p>Exposed normalized tools and schemas registered into Vyom's Tool Registry.</p>
                </div>
                <button type="button" className="hub-btn-close" onClick={() => setSelectedConnector(null)}>
                  <X size={16} />
                </button>
              </div>

              <div className="hub-drawer-body">
                {selectedConnector.tools.map((t) => (
                  <div key={t.id} className="hub-tool-spec-card">
                    <div className="hub-tool-spec-header">
                      <div>
                        <h4>{t.name}</h4>
                        <span className="hub-tool-id">{t.id}</span>
                      </div>
                      <span className={`hub-risk-pill risk-${t.risk_level}`}>
                        <Shield size={11} />
                        {t.risk_level.toUpperCase()} RISK
                      </span>
                    </div>
                    <p className="hub-tool-desc">{t.description}</p>
                    {t.input_schema && (
                      <div className="hub-schema-view">
                        <span>Input Parameters:</span>
                        <pre>{JSON.stringify(t.input_schema, null, 2)}</pre>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* CONNECT CREDENTIALS MODAL */}
        {connectingModal && (
          <div className="hub-connect-modal" role="dialog" aria-modal="true">
            <div className="hub-modal-box">
              <div className="hub-modal-header">
                <h3>Connect {connectingModal.name}</h3>
                <button type="button" onClick={() => setConnectingModal(null)}>
                  <X size={16} />
                </button>
              </div>
              <p>Enter your API credentials, Personal Access Token, or authorization key for {connectingModal.name}.</p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void handleConnect(connectingModal);
                }}
              >
                <div className="hub-form-group">
                  <label>API Key / Access Token</label>
                  <input
                    type="password"
                    value={credentialInput}
                    onChange={(e) => setCredentialInput(e.target.value)}
                    placeholder="ghp_... / secret_token"
                    required
                  />
                </div>
                <div className="hub-modal-footer">
                  <button type="button" className="hub-btn-secondary" onClick={() => setConnectingModal(null)}>
                    Cancel
                  </button>
                  <button type="submit" className="hub-btn-primary" disabled={connectingBusy || !credentialInput.trim()}>
                    {connectingBusy ? <Loader2 size={14} className="hub-spin" /> : <Check size={14} />}
                    <span>Authenticate & Connect</span>
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* ADD CUSTOM MCP SERVER MODAL */}
        {showAddMcpModal && (
          <div className="hub-connect-modal" role="dialog" aria-modal="true">
            <div className="hub-modal-box hub-modal-large">
              <div className="hub-modal-header">
                <div className="hub-brand-icon">
                  <Server size={18} />
                  <h3>Add Custom Model Context Protocol (MCP) Server</h3>
                </div>
                <button type="button" onClick={() => setShowAddMcpModal(false)}>
                  <X size={16} />
                </button>
              </div>

              <form onSubmit={handleSaveMcp}>
                <div className="hub-form-grid">
                  <div className="hub-form-group">
                    <label>Server Identifier (ID)</label>
                    <input
                      value={mcpId}
                      onChange={(e) => setMcpId(e.target.value)}
                      placeholder="e.g. github-mcp"
                      required
                    />
                  </div>
                  <div className="hub-form-group">
                    <label>Display Name</label>
                    <input
                      value={mcpName}
                      onChange={(e) => setMcpName(e.target.value)}
                      placeholder="e.g. GitHub MCP Server"
                      required
                    />
                  </div>
                </div>

                <div className="hub-form-grid">
                  <div className="hub-form-group">
                    <label>Transport</label>
                    <select value={mcpTransport} onChange={(e) => setMcpTransport(e.target.value)}>
                      <option value="stdio">stdio (Local Subprocess)</option>
                      <option value="http">Streamable HTTP / REST</option>
                      <option value="sse">Server-Sent Events (SSE)</option>
                    </select>
                  </div>
                  <div className="hub-form-group">
                    <label>Executable Command</label>
                    <input
                      value={mcpCommand}
                      onChange={(e) => setMcpCommand(e.target.value)}
                      placeholder="e.g. npx"
                      required
                    />
                  </div>
                </div>

                <div className="hub-form-group">
                  <label>Command Arguments (Space-separated)</label>
                  <input
                    value={mcpArgs}
                    onChange={(e) => setMcpArgs(e.target.value)}
                    placeholder="e.g. -y @modelcontextprotocol/server-everything"
                  />
                </div>

                {mcpTestResult && (
                  <div className={`hub-test-result ${mcpTestResult.healthy ? "test-success" : "test-fail"}`}>
                    {mcpTestResult.healthy ? (
                      <div>
                        <CheckCircle2 size={16} />
                        <span>Connected! Discovered {mcpTestResult.tool_count} dynamic MCP tools: {mcpTestResult.tools?.join(", ")}</span>
                      </div>
                    ) : (
                      <div>
                        <AlertTriangle size={16} />
                        <span>Test connection failed: {mcpTestResult.error}</span>
                      </div>
                    )}
                  </div>
                )}

                <div className="hub-modal-footer">
                  <button
                    type="button"
                    className="hub-btn-secondary"
                    onClick={() => void handleTestMcp()}
                    disabled={mcpTestBusy || !mcpCommand.trim()}
                  >
                    {mcpTestBusy ? <Loader2 size={14} className="hub-spin" /> : <Terminal size={14} />}
                    <span>Test Connection</span>
                  </button>
                  <button type="submit" className="hub-btn-primary" disabled={mcpTestBusy || !mcpId.trim() || !mcpCommand.trim()}>
                    <Check size={14} />
                    <span>Save & Register Server</span>
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
