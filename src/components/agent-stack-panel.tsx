import { useEffect, useState } from "react";
import { Database, Plug, Sparkles, RefreshCw } from "lucide-react";

const BRAIN = (import.meta.env.VITE_VYOM_BRAIN_URL as string | undefined) ?? "http://127.0.0.1:7788";

type MCPTool = { server_id: string; status: string; name: string };
type KnowledgeFact = {
  title: string;
  summary: string;
  source_url?: string;
  confidence?: number;
};
type KnowledgeResult = {
  subject: string;
  facts: KnowledgeFact[];
  stale: boolean;
  needs_research: boolean;
  reason?: string;
};
type RouterModel = {
  success_rate?: number;
  calls?: number;
  domain_bias?: Record<string, { bias: number; reason?: string }>;
};

/** Self-contained agent-stack panel: surfaces VYOM's persistent knowledge
 * base, connected MCP servers, and the self-improvement loop's lessons /
 * router bias — all fetched from the real Brain API on mount / refresh. */
export function AgentStackPanel() {
  const [knowledge, setKnowledge] = useState<KnowledgeResult | null>(null);
  const [knowQuery, setKnowQuery] = useState("");
  const [servers, setServers] = useState<Array<{ server_id: string; status: string; tools: unknown[] }>>([]);
  const [routerBias, setRouterBias] = useState<Record<string, RouterModel>>({});
  const [loading, setLoading] = useState(false);
  const [src, setSrc] = useState("");

  async function refresh() {
    setLoading(true);
    try {
      const [svr, bias] = await Promise.all([
        fetch(`${BRAIN}/api/mcp/servers`).then((r) => r.json()),
        fetch(`${BRAIN}/api/adaptive/router-bias`).then((r) => r.json()),
      ]);
      setServers(svr.servers ?? []);
      setRouterBias(bias.models ?? {});
    } catch {
      setServers([]);
      setRouterBias({});
    } finally {
      setLoading(false);
    }
  }

  async function searchKnowledge(e: React.FormEvent) {
    e.preventDefault();
    if (!knowQuery.trim()) return;
    try {
      const r = await fetch(`${BRAIN}/api/knowledge/search?q=${encodeURIComponent(knowQuery.trim())}`).then((x) => x.json());
      setKnowledge(r);
      setSrc(knowQuery.trim());
    } catch {
      setKnowledge(null);
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 15000);
    return () => clearInterval(id);
  }, []);

  return (
    <section className="agent-stack-panel" aria-label="Agent stack">
      <header className="agent-stack-header">
        <h3>Agent Stack</h3>
        <button onClick={refresh} className="agent-stack-refresh" aria-label="Refresh" disabled={loading}>
          <RefreshCw size={14} />
        </button>
      </header>

      <div className="agent-stack-grid">
        <div className="agent-stack-card">
          <h4>
            <Database size={14} /> Knowledge Base
          </h4>
          <form onSubmit={searchKnowledge} className="agent-stack-know">
            <input
              value={knowQuery}
              onChange={(e) => setKnowQuery(e.target.value)}
              placeholder='Ask "Model Context Protocol"…'
              aria-label="Knowledge search"
            />
            <button type="submit">Recall</button>
          </form>
          {knowledge && (
            <div className="agent-stack-know-result">
              {knowledge.facts.length === 0 ? (
                <p className="muted">
                  No facts known about "{src}" yet
                  {knowledge.needs_research ? " — research recommended." : "."}
                </p>
              ) : (
                <ul>
                  {knowledge.facts.slice(0, 4).map((fact, i) => (
                    <li key={i}>
                      <strong>{fact.title}</strong>
                      <span>{fact.summary.slice(0, 140)}</span>
                      {fact.source_url && <em>{fact.source_url}</em>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        <div className="agent-stack-card">
          <h4>
            <Plug size={14} /> MCP Servers
          </h4>
          {servers.length === 0 ? (
            <p className="muted">No MCP servers connected yet.</p>
          ) : (
            <ul>
              {servers.map((s) => (
                <li key={s.server_id}>
                  <span className={`agent-stack-dot mcp-${s.status}`} />
                  <strong>{s.server_id}</strong>
                  <em>({s.status}, {Array.isArray(s.tools) ? s.tools.length : 0} tools)</em>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="agent-stack-card">
          <h4>
            <Sparkles size={14} /> Learned Router Bias
          </h4>
          {Object.keys(routerBias).length === 0 ? (
            <p className="muted">No learned routing signal yet.</p>
          ) : (
            <ul>
              {Object.entries(routerBias).slice(0, 5).map(([model, m]) => (
                <li key={model}>
                  <strong>{model}</strong>
                  <em>
                    {m.success_rate !== undefined ? `${(m.success_rate * 100).toFixed(0)}%` : "—"} success
                    {m.calls !== undefined ? ` · ${m.calls} calls` : ""}
                  </em>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
