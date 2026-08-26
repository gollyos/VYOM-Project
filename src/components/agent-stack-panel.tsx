import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowUpRight,
  BookOpen,
  CheckCircle2,
  CirclePlus,
  Database,
  GitBranch,
  Layers,
  Plug,
  RefreshCw,
  Search,
  Shield,
  Sparkles,
  Wrench,
  X,
  Zap,
} from "lucide-react";

const BRAIN = (import.meta.env.VITE_VYOM_BRAIN_URL as string | undefined) ?? "http://127.0.0.1:7788";

/* ------------------------------------------------------------------ *
 * Real Brain API response shapes. These MUST match the FastAPI
 * serialisation in services/brain/app/api/*.py — nothing here is a
 * mock. A change to a schema on the backend is a change here.
 * ------------------------------------------------------------------ */

type KnowledgeFact = {
  id: string;
  subject: string;
  predicate: string;
  value: string;
  source_url?: string | null;
  source_title?: string | null;
  confidence: number;
  first_learned_at: string;
  last_confirmed_at: string;
  confirmations: number;
  task_id?: string | null;
  memory_id?: string | null;
  metadata: Record<string, unknown>;
};
type KnowledgeRecall = {
  subject: string;
  facts: KnowledgeFact[];
  stale: boolean;
  needs_research: boolean;
  reason: string;
};

type MCPServerView = {
  server_id: string;
  name: string;
  transport: string;
  status: string; // connected | disconnected | connecting | error
  capabilities: string[];
  tools: Array<Record<string, unknown>>;
  last_health_check?: string | null;
  trust_level: string;
};
type MCPCatalogEntry = {
  catalog_id: string;
  display_name: string;
  description: string;
  command: string;
  args_template: string[];
  requires_path_arg: boolean;
  trust_level: string;
  homepage: string;
};

type Lesson = {
  id: string;
  title: string;
  content: string;
  confidence: number;
  task_id?: string | null;
  created_at: string;
};
type LessonsResponse = { lessons: Lesson[]; count: number };

type KanbanCard = {
  id: string;
  board: string;
  title: string;
  goal: string;
  status: "pending" | "claimed" | "in_progress" | "completed" | "blocked" | "failed";
  worker_pid: number | null;
  completed_at?: string | null;
  error?: string | null;
};
type KanbanCardsResponse = { count: number; cards: KanbanCard[] };
type KanbanStatusResponse = { active_workers: number; max_concurrent_workers: number };

type PluginInfo = { name: string; version: string; description: string; hooks: string[] };
type PluginsResponse = { loaded: PluginInfo[]; errors: Record<string, string> };

type CuratorRun = {
  id: string;
  started_at: string;
  completed_at?: string | null;
  status: string;
  summary: {
    knowledge_lint?: { totals?: { contradicted?: number; stale?: number; orphans?: number } } | null;
    stale_automations?: Array<{ id: string; name: string }>;
    dialectic_findings?: Array<{ subject: string; predicate: string; value: string; confidence: number }>;
  };
};
type CuratorRunsResponse = { count: number; runs: CuratorRun[] };


type RouterBiasModel = {
  success_rate?: number | null;
  calls?: number | null;
  domain_bias?: Record<string, { bias: number; reason?: string }>;
};
type RouterBiasResponse = { attached: boolean; models: Record<string, RouterBiasModel> };

/* ------------------------------------------------------------------ *
 * Helpers
 * ------------------------------------------------------------------ */

function apiBase() {
  return BRAIN.replace(/\/$/, "");
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, { signal: AbortSignal.timeout(5000) });
  if (!response.ok) throw new Error(`GET ${path} failed (${response.status})`);
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(6000),
  });
  const text = await response.text();
  let payload: unknown = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { raw: text };
  }
  if (!response.ok) {
    const detail =
      (payload as { detail?: string } | null)?.detail ||
      `${path} failed (${response.status})`;
    throw new Error(String(detail));
  }
  return payload as T;
}

async function deleteRequest<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, { method: "DELETE", signal: AbortSignal.timeout(5000) });
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

function formatDate(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function factSentence(fact: KnowledgeFact): string {
  return `${fact.subject} ${fact.predicate} ${fact.value}`.trim();
}

/** Map a server status to a human label. */
function statusLabel(status: string): string {
  const map: Record<string, string> = {
    connected: "Connected",
    connecting: "Connecting",
    disconnected: "Disconnected",
    error: "Error",
  };
  return map[status] ?? status;
}

/* ------------------------------------------------------------------ *
 * Panel
 * ------------------------------------------------------------------ */

export function AgentStackPanel() {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  // Knowledge base
  const [knowQuery, setKnowQuery] = useState("");
  const [knowledge, setKnowledge] = useState<KnowledgeRecall | null>(null);
  const [knowSearched, setKnowSearched] = useState("");
  const [knowBusy, setKnowBusy] = useState(false);
  const [knowError, setKnowError] = useState<string | null>(null);

  // MCP
  const [servers, setServers] = useState<MCPServerView[]>([]);
  const [catalog, setCatalog] = useState<MCPCatalogEntry[]>([]);
  const [busyServerId, setBusyServerId] = useState<string | null>(null);
  const [pathInputs, setPathInputs] = useState<Record<string, string>>({});
  const [mcpError, setMcpError] = useState<string | null>(null);

  // Self-improvement
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [routerBias, setRouterBias] = useState<RouterBiasResponse>({ attached: false, models: {} });
  const [learningError, setLearningError] = useState<string | null>(null);

  // Kanban / Plugins / Curator - the Hermes-parity autonomy features
  const [kanbanCards, setKanbanCards] = useState<KanbanCard[]>([]);
  const [kanbanStatus, setKanbanStatus] = useState<KanbanStatusResponse>({ active_workers: 0, max_concurrent_workers: 0 });
  const [plugins, setPlugins] = useState<PluginsResponse>({ loaded: [], errors: {} });
  const [curatorRuns, setCuratorRuns] = useState<CuratorRun[]>([]);
  const [autonomyError, setAutonomyError] = useState<string | null>(null);
  const [curatorBusy, setCuratorBusy] = useState(false);

  // Refresh only while the drawer is open.
  const refreshTimer = useRef<number | null>(null);

  const loadServers = useCallback(async () => {
    setMcpError(null);
    try {
      const [serversResp, catalogResp] = await Promise.all([
        getJson<{ servers: MCPServerView[] }>("/api/mcp/servers"),
        getJson<{ catalog: MCPCatalogEntry[] }>("/api/mcp/catalog"),
      ]);
      setServers(serversResp.servers ?? []);
      setCatalog(catalogResp.catalog ?? []);
    } catch (error) {
      setMcpError(error instanceof Error ? error.message : "Could not reach the Brain MCP API");
    }
  }, []);

  const loadLearning = useCallback(async () => {
    setLearningError(null);
    try {
      const [lessonsResp, biasResp] = await Promise.all([
        getJson<LessonsResponse>("/api/adaptive/lessons"),
        getJson<RouterBiasResponse>("/api/adaptive/router-bias"),
      ]);
      setLessons(lessonsResp.lessons ?? []);
      setRouterBias(biasResp);
    } catch (error) {
      setLearningError(error instanceof Error ? error.message : "Could not reach the Brain adaptive API");
    }
  }, []);

  const loadAutonomy = useCallback(async () => {
    setAutonomyError(null);
    try {
      const [cardsResp, statusResp, pluginsResp, curatorResp] = await Promise.all([
        getJson<KanbanCardsResponse>("/api/kanban/cards?limit=10"),
        getJson<KanbanStatusResponse>("/api/kanban/status"),
        getJson<PluginsResponse>("/api/plugins"),
        getJson<CuratorRunsResponse>("/api/curator/runs?limit=5"),
      ]);
      setKanbanCards(cardsResp.cards ?? []);
      setKanbanStatus(statusResp);
      setPlugins(pluginsResp);
      setCuratorRuns(curatorResp.runs ?? []);
    } catch (error) {
      setAutonomyError(error instanceof Error ? error.message : "Could not reach the Brain autonomy APIs");
    }
  }, []);

  const runCuratorNow = useCallback(async () => {
    setCuratorBusy(true);
    try {
      await fetch(`${apiBase()}/api/curator/run-now`, { method: "POST" });
      await loadAutonomy();
    } catch {
      // loadAutonomy's own error state already surfaces reachability issues
    } finally {
      setCuratorBusy(false);
    }
  }, [loadAutonomy]);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    await Promise.all([loadServers(), loadLearning(), loadAutonomy()]);
    setLoading(false);
  }, [loadServers, loadLearning, loadAutonomy]);

  // Load data the first time the drawer opens, then keep it warm.
  useEffect(() => {
    if (!open || refreshTimer.current !== null) return;
    void (async () => {
      setLoading(true);
      await Promise.all([loadServers(), loadLearning(), loadAutonomy()]);
      setLoading(false);
    })();
    refreshTimer.current = window.setInterval(() => {
      void refreshAll();
    }, 15000);
    return () => {
      if (refreshTimer.current !== null) {
        window.clearInterval(refreshTimer.current);
        refreshTimer.current = null;
      }
    };
  }, [open, loadServers, loadLearning, loadAutonomy, refreshAll]);

  async function searchKnowledge(event: FormEvent) {
    event.preventDefault();
    const q = knowQuery.trim();
    if (!q) return;
    setKnowBusy(true);
    setKnowError(null);
    try {
      const result = await getJson<KnowledgeRecall>(`/api/knowledge/search?q=${encodeURIComponent(q)}`);
      setKnowledge(result);
      setKnowSearched(q);
    } catch (error) {
      setKnowError(error instanceof Error ? error.message : "Knowledge recall failed");
      setKnowledge(null);
    } finally {
      setKnowBusy(false);
    }
  }

  async function connectFromCatalog(entry: MCPCatalogEntry) {
    const path = pathInputs[entry.catalog_id]?.trim() ?? "";
    if (entry.requires_path_arg && !path) {
      setMcpError(`"${entry.display_name}" requires a directory path before it can be connected.`);
      return;
    }
    setBusyServerId(`catalog:${entry.catalog_id}`);
    setMcpError(null);
    try {
      await postJson<{ server_id: string; status: string }>("/api/mcp/servers/from-catalog", {
        catalog_id: entry.catalog_id,
        path: path || null,
      });
      await loadServers();
    } catch (error) {
      setMcpError(error instanceof Error ? error.message : `Could not connect "${entry.display_name}"`);
    } finally {
      setBusyServerId(null);
    }
  }

  async function reconnectServer(serverId: string) {
    setBusyServerId(serverId);
    setMcpError(null);
    try {
      await postJson<{ server_id: string; status: string }>(`/api/mcp/servers/${encodeURIComponent(serverId)}/reconnect`);
      await loadServers();
    } catch (error) {
      setMcpError(error instanceof Error ? error.message : `Could not reconnect "${serverId}"`);
    } finally {
      setBusyServerId(null);
    }
  }

  async function removeServer(serverId: string) {
    setBusyServerId(serverId);
    setMcpError(null);
    try {
      await deleteRequest<{ server_id: string; status: string }>(`/api/mcp/servers/${encodeURIComponent(serverId)}`);
      await loadServers();
    } catch (error) {
      setMcpError(error instanceof Error ? error.message : `Could not remove "${serverId}"`);
    } finally {
      setBusyServerId(null);
    }
  }

  const totalTools = servers.reduce((sum, server) => sum + (Array.isArray(server.tools) ? server.tools.length : 0), 0);

  return (
    <>
      {/* Toggle — always visible, opens the capabilities drawer. */}
      <button
        type="button"
        className={`cap-toggle ${open ? "cap-toggle-active" : ""}`}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label="Toggle VYOM capabilities panel"
      >
        <Layers size={13} />
        <span>Capabilities</span>
        {open && <span className="cap-toggle-count" />}
      </button>

      {open && (
        <aside className="cap-drawer" role="dialog" aria-modal="false" aria-label="VYOM capabilities">
          <header className="cap-drawer-header">
            <div className="cap-drawer-title">
              <Sparkles size={14} />
              <div>
                <h3>VYOM Capabilities</h3>
                <p>
                  live from the local Brain · {servers.length} MCP server{servers.length === 1 ? "" : "s"} · {totalTools} tool
                  {totalTools === 1 ? "" : "s"} · {lessons.length} lesson{lessons.length === 1 ? "" : "s"}
                </p>
              </div>
            </div>
            <div className="cap-drawer-actions">
              <button
                type="button"
                className="cap-icon-button"
                onClick={() => void refreshAll()}
                aria-label="Refresh all capabilities"
                disabled={loading}
              >
                <RefreshCw size={14} className={loading ? "cap-spin" : ""} />
              </button>
              <button
                type="button"
                className="cap-icon-button"
                onClick={() => setOpen(false)}
                aria-label="Close capabilities panel"
              >
                <X size={14} />
              </button>
            </div>
          </header>

          <div className="cap-drawer-body">
            {/* ---------- Knowledge Base ---------- */}
            <section className="cap-card" aria-label="Persistent knowledge base">
              <header className="cap-card-header">
                <span className="cap-card-icon cap-card-icon-knowledge">
                  <Database size={14} />
                </span>
                <div>
                  <h4>Persistent Knowledge Base</h4>
                  <p>What VYOM already knows — recall without re-researching.</p>
                </div>
              </header>

              <form className="cap-know-form" onSubmit={searchKnowledge}>
                <div className="cap-input-wrap">
                  <Search size={13} />
                  <input
                    value={knowQuery}
                    onChange={(event) => setKnowQuery(event.target.value)}
                    placeholder="Search the knowledge base…"
                    aria-label="Knowledge base search"
                    spellCheck={false}
                  />
                </div>
                <button className="cap-primary" type="submit" disabled={!knowQuery.trim() || knowBusy}>
                  {knowBusy ? "Recalling…" : "Recall"}
                </button>
              </form>

              {knowError && (
                <p className="cap-error">
                  <AlertCircle size={11} /> {knowError}
                </p>
              )}

              {knowledge && (
                <div className="cap-know-result">
                  <div className="cap-know-meta">
                    <span className={`cap-badge ${knowledge.needs_research ? "cap-badge-stale" : "cap-badge-fresh"}`}>
                      {knowledge.needs_research ? "needs research" : "fresh"}
                    </span>
                    <span>{knowledge.facts.length} fact{knowledge.facts.length === 1 ? "" : "s"}</span>
                    {knowledge.reason && <span className="cap-muted">{knowledge.reason}</span>}
                  </div>
                  {knowledge.facts.length === 0 ? (
                    <p className="cap-empty">
                      No facts known about “{knowSearched}” yet{knowledge.needs_research ? " — a research pass would record them." : "."}
                    </p>
                  ) : (
                    <ul className="cap-fact-list">
                      {knowledge.facts.map((fact) => (
                        <li key={fact.id} className="cap-fact">
                          <p className="cap-fact-sentence">{factSentence(fact)}</p>
                          <div className="cap-fact-meta">
                            <span title={`confidence ${Math.round(fact.confidence * 100)}%`}>
                              {(fact.confidence * 100).toFixed(0)}% confidence
                            </span>
                            <span>{fact.confirmations} confirmation{fact.confirmations === 1 ? "" : "s"}</span>
                            <span>seen {formatDate(fact.last_confirmed_at)}</span>
                          </div>
                          {(fact.source_title || fact.source_url) && (
                            <a
                              className="cap-fact-source"
                              href={fact.source_url ?? "#"}
                              target="_blank"
                              rel="noreferrer"
                              title={fact.source_url ?? undefined}
                            >
                              <ArrowUpRight size={11} />
                              {fact.source_title ?? fact.source_url}
                            </a>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </section>

            {/* ---------- MCP Servers ---------- */}
            <section className="cap-card" aria-label="MCP server connections">
              <header className="cap-card-header">
                <span className="cap-card-icon cap-card-icon-mcp">
                  <Plug size={14} />
                </span>
                <div>
                  <h4>MCP Server Connections</h4>
                  <p>External capability servers VYOM is explicitly granted to run.</p>
                </div>
              </header>

              {mcpError && (
                <p className="cap-error">
                  <AlertCircle size={11} /> {mcpError}
                </p>
              )}

              <div className="cap-subhead">Connected</div>
              {servers.length === 0 ? (
                <p className="cap-empty">No MCP servers connected yet. Grant one below from the curated catalog.</p>
              ) : (
                <ul className="cap-server-list">
                  {servers.map((server) => {
                    const toolCount = Array.isArray(server.tools) ? server.tools.length : 0;
                    const busy = busyServerId === server.server_id;
                    return (
                      <li key={server.server_id} className="cap-server">
                        <span className={`cap-status-dot cap-status-${server.status}`} />
                        <div className="cap-server-main">
                          <strong>{server.name || server.server_id}</strong>
                          <span className="cap-muted">
                            {server.server_id} · {statusLabel(server.status)} · {toolCount} tool{toolCount === 1 ? "" : "s"} ·{" "}
                            {server.trust_level}
                          </span>
                        </div>
                        <div className="cap-server-actions">
                          <button
                            type="button"
                            className="cap-mini"
                            onClick={() => void reconnectServer(server.server_id)}
                            disabled={busy}
                            title="Reconnect this server"
                          >
                            Reconnect
                          </button>
                          <button
                            type="button"
                            className="cap-mini cap-mini-danger"
                            onClick={() => void removeServer(server.server_id)}
                            disabled={busy}
                            title="Remove this server"
                          >
                            Remove
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}

              <div className="cap-subhead">Curated Catalog</div>
              <ul className="cap-catalog-list">
                {catalog.map((entry) => {
                  const busy = busyServerId === `catalog:${entry.catalog_id}`;
                  const hasPath = Boolean(pathInputs[entry.catalog_id]?.trim());
                  const canConnect = !entry.requires_path_arg || hasPath;
                  return (
                    <li key={entry.catalog_id} className="cap-catalog">
                      <div className="cap-catalog-top">
                        <CheckCircle2 size={13} />
                        <strong>{entry.display_name}</strong>
                        <span className="cap-muted">{entry.trust_level}</span>
                      </div>
                      <p className="cap-catalog-desc">{entry.description}</p>
                      {entry.requires_path_arg && (
                        <div className="cap-input-wrap cap-input-wrap-sm">
                          <Wrench size={12} />
                          <input
                            value={pathInputs[entry.catalog_id] ?? ""}
                            onChange={(event) =>
                              setPathInputs((current) => ({ ...current, [entry.catalog_id]: event.target.value }))
                            }
                            placeholder="Allowed directory path…"
                            aria-label={`Path for ${entry.display_name}`}
                            spellCheck={false}
                          />
                        </div>
                      )}
                      <div className="cap-catalog-actions">
                        <button
                          type="button"
                          className="cap-mini cap-mini-accent"
                          onClick={() => void connectFromCatalog(entry)}
                          disabled={busy || !canConnect}
                        >
                          {busy ? "Connecting…" : "Connect"}
                        </button>
                        {entry.homepage && (
                          <a
                            className="cap-mini cap-mini-link"
                            href={entry.homepage}
                            target="_blank"
                            rel="noreferrer"
                            title="View this server's homepage"
                          >
                            Docs <ArrowUpRight size={10} />
                          </a>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>

            {/* ---------- Self-Improvement Loop ---------- */}
            <section className="cap-card" aria-label="Self-improvement loop">
              <header className="cap-card-header">
                <span className="cap-card-icon cap-card-icon-learning">
                  <BookOpen size={14} />
                </span>
                <div>
                  <h4>Self-Improvement Loop</h4>
                  <p>Lessons from real outcomes and the learned router bias.</p>
                </div>
              </header>

              {learningError && (
                <p className="cap-error">
                  <AlertCircle size={11} /> {learningError}
                </p>
              )}

              <div className="cap-subhead">
                Lessons <span className="cap-count">{lessons.length}</span>
              </div>
              {lessons.length === 0 ? (
                <p className="cap-empty">
                  No lessons recorded yet. They appear here after real task outcomes — nothing is synthesised.
                </p>
              ) : (
                <ul className="cap-lesson-list">
                  {lessons.map((lesson) => (
                    <li key={lesson.id} className="cap-lesson">
                      <div className="cap-lesson-title">
                        <strong>{lesson.title}</strong>
                        <span className="cap-muted">
                          {(lesson.confidence * 100).toFixed(0)}% · {formatDate(lesson.created_at)}
                        </span>
                      </div>
                      <p>{lesson.content}</p>
                    </li>
                  ))}
                </ul>
              )}

              <div className="cap-subhead">
                Learned Router Bias <span className="cap-count">{Object.keys(routerBias.models).length}</span>
              </div>
              {!routerBias.attached ? (
                <p className="cap-empty">The learned router is not attached to this Brain instance.</p>
              ) : Object.keys(routerBias.models).length === 0 ? (
                <p className="cap-empty">No routing evidence yet — it accumulates from real model usage.</p>
              ) : (
                <ul className="cap-router-list">
                  {Object.entries(routerBias.models).map(([modelId, model]) => (
                    <li key={modelId} className="cap-router">
                      <div className="cap-router-top">
                        <strong>{modelId}</strong>
                        <span className="cap-muted">
                          {model.calls ?? 0} call{model.calls === 1 ? "" : "s"}
                        </span>
                      </div>
                      {model.success_rate !== undefined && model.success_rate !== null && (
                        <div className="cap-meter" title={`${(model.success_rate * 100).toFixed(0)}% success`}>
                          <span
                            className="cap-meter-fill"
                            style={{ width: `${Math.max(0, Math.min(100, model.success_rate * 100))}%` }}
                          />
                        </div>
                      )}
                      <div className="cap-router-domains">
                        {Object.entries(model.domain_bias ?? {}).length === 0 ? (
                          <span className="cap-muted">No per-domain signal yet.</span>
                        ) : (
                          Object.entries(model.domain_bias ?? {}).map(([domain, bias]) => (
                            <span
                              key={domain}
                              className={`cap-bias-chip ${(bias.bias ?? 0) >= 0 ? "cap-bias-positive" : "cap-bias-negative"}`}
                              title={bias.reason ?? `${modelId} · ${domain}`}
                            >
                              {domain}: {bias.bias >= 0 ? "+" : ""}
                              {bias.bias}
                            </span>
                          ))
                        )}
                      </div>
                      {Object.entries(model.domain_bias ?? {}).map(([domain, bias]) =>
                        bias.reason ? (
                          <p key={`${domain}-reason`} className="cap-router-reason">
                            {bias.reason}
                          </p>
                        ) : null,
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="cap-card" aria-label="Autonomous multi-agent stack">
              <header className="cap-card-header">
                <span className="cap-card-icon cap-card-icon-learning">
                  <GitBranch size={14} />
                </span>
                <div>
                  <h4>Autonomous Agents</h4>
                  <p>Kanban workers, plugins, and the self-review Curator - live from the running Brain.</p>
                </div>
              </header>

              {autonomyError && (
                <p className="cap-error">
                  <AlertCircle size={11} /> {autonomyError}
                </p>
              )}

              <div className="cap-subhead">
                Kanban Workers{" "}
                <span className="cap-count">
                  {kanbanStatus.active_workers}/{kanbanStatus.max_concurrent_workers} active
                </span>
              </div>
              {kanbanCards.length === 0 ? (
                <p className="cap-empty">No kanban cards yet. Created via POST /api/kanban/cards.</p>
              ) : (
                <ul className="cap-lesson-list">
                  {kanbanCards.map((card) => (
                    <li key={card.id} className="cap-lesson">
                      <div className="cap-lesson-title">
                        <strong>{card.title}</strong>
                        <span className={`cap-badge ${card.status === "completed" ? "cap-badge-fresh" : card.status === "failed" || card.status === "blocked" ? "cap-badge-stale" : ""}`}>
                          {card.status}
                          {card.worker_pid ? ` · pid ${card.worker_pid}` : ""}
                        </span>
                      </div>
                      {card.error && <p className="cap-router-reason">{card.error}</p>}
                    </li>
                  ))}
                </ul>
              )}

              <div className="cap-subhead">
                Plugins <span className="cap-count">{plugins.loaded.length}</span>
              </div>
              {plugins.loaded.length === 0 ? (
                <p className="cap-empty">No plugins loaded. Drop one into data/plugins/&lt;name&gt;/.</p>
              ) : (
                <ul className="cap-lesson-list">
                  {plugins.loaded.map((plugin) => (
                    <li key={plugin.name} className="cap-lesson">
                      <div className="cap-lesson-title">
                        <strong>
                          {plugin.name} <span className="cap-muted">v{plugin.version}</span>
                        </strong>
                        <span className="cap-muted">{plugin.hooks.join(", ") || "no hooks"}</span>
                      </div>
                      <p>{plugin.description}</p>
                    </li>
                  ))}
                </ul>
              )}
              {Object.keys(plugins.errors).length > 0 && (
                <ul className="cap-lesson-list">
                  {Object.entries(plugins.errors).map(([name, error]) => (
                    <li key={name} className="cap-lesson">
                      <div className="cap-lesson-title">
                        <strong>{name}</strong>
                        <span className="cap-badge cap-badge-stale">failed to load</span>
                      </div>
                      <p className="cap-router-reason">{error}</p>
                    </li>
                  ))}
                </ul>
              )}

              <div className="cap-subhead">
                Curator Runs <span className="cap-count">{curatorRuns.length}</span>
                <button
                  type="button"
                  className="cap-icon-button"
                  title="Run curator now"
                  onClick={() => void runCuratorNow()}
                  disabled={curatorBusy}
                  style={{ marginLeft: "auto" }}
                >
                  <Zap size={12} className={curatorBusy ? "cap-spin" : ""} />
                </button>
              </div>
              {curatorRuns.length === 0 ? (
                <p className="cap-empty">
                  No curator runs yet. It self-triggers when idle, or run it now with the button above.
                </p>
              ) : (
                <ul className="cap-lesson-list">
                  {curatorRuns.map((run) => {
                    const findings = run.summary.dialectic_findings?.length ?? 0;
                    const staleAutomations = run.summary.stale_automations?.length ?? 0;
                    const contradicted = run.summary.knowledge_lint?.totals?.contradicted ?? 0;
                    return (
                      <li key={run.id} className="cap-lesson">
                        <div className="cap-lesson-title">
                          <strong>{formatDate(run.started_at)}</strong>
                          <span className="cap-muted">{run.status}</span>
                        </div>
                        <p>
                          {findings} learned fact{findings === 1 ? "" : "s"} · {staleAutomations} paused automation
                          {staleAutomations === 1 ? "" : "s"} · {contradicted} contradiction
                          {contradicted === 1 ? "" : "s"}
                        </p>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </div>

          <footer className="cap-drawer-footer">
            <span>
              <Shield size={11} />
              Every value above is read live from <code>127.0.0.1:7788</code> · refreshing every 15s
            </span>
            <span className="cap-runtime">
              <CirclePlus size={11} />
              {totalTools} tools registered
            </span>
          </footer>
        </aside>
      )}
    </>
  );
}
