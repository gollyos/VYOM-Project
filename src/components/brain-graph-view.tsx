import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls, Html } from "@react-three/drei";
import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import * as THREE from "three";
import { X, RefreshCw, Search, Maximize2 } from "lucide-react";

/* ------------------------------------------------------------------ *
 * VYOM's own native Brain Graph - a real 3D view of the SAME unified
 * knowledge graph backend (/api/brain-graph, app/brain_graph/service.py)
 * that already fuses tasks, memories, goals, agents, tools, CRM,
 * automations and the auto-linked memory web into one traversable
 * structure. This is VYOM's OWN visualization, drawn entirely with the
 * project's existing three.js/react-three-fiber stack - no external
 * app, no Obsidian, nothing installed outside this repo.
 * ------------------------------------------------------------------ */

const BRAIN = (import.meta.env.VITE_VYOM_BRAIN_URL as string | undefined) ?? "http://127.0.0.1:7788";

type BrainNode = {
  id: string;
  native_id: string;
  kind: string;
  label: string;
  summary: string;
  status: string | null;
  source_store: string;
  updated_at: string | null;
  metadata: Record<string, unknown>;
};

type BrainEdge = {
  id: string;
  source_id: string;
  target_id: string;
  relation: string;
  confidence: number;
  verified: boolean;
  origin: string;
  provenance: string;
};

type BrainGraphResponse = {
  root_id: string | null;
  depth: number;
  nodes: BrainNode[];
  edges: BrainEdge[];
  truncated: boolean;
  refreshed_at: string;
};

type LayoutNode = BrainNode & { position: THREE.Vector3 };

/* Same teal palette as the rest of VYOM's presence UI (neural-biome.tsx
 * / vyom-state.ts) so the graph reads as part of the same organism,
 * with one distinct hue per node kind for legibility at scale. */
const KIND_COLORS: Record<string, string> = {
  core: "#e0f7f2",
  memory: "#9adbd5",
  task: "#58a6ff",
  agent: "#f0b429",
  goal: "#f85149",
  milestone: "#ff9d5c",
  habit: "#c297ff",
  project: "#79aaa8",
  client: "#79aaa8",
  crm: "#79aaa8",
  tool: "#8bc4c0",
  model: "#8bbab7",
  skill: "#7ee787",
  capability: "#6ee7b7",
  automation: "#ffd166",
  automation_run: "#ffd166",
  artifact: "#d2a8ff",
  evidence: "#5f6b73",
  experience: "#4f8e91",
  integration: "#79aaa8",
  device: "#79aaa8",
};

function colorForKind(kind: string): string {
  return KIND_COLORS[kind] ?? "#79aaa8";
}

/* Force-directed layout done ONCE on the CPU when data arrives (not
 * per-frame): this is a real knowledge graph, not a decorative
 * animation, so node positions should be a stable read of the actual
 * data - shared entities cluster together, isolated nodes drift out.
 * Cheap Fruchterman-Reingold-style relaxation is more than enough for
 * a few hundred nodes and keeps the whole view snappy. */
function layoutGraph(nodes: BrainNode[], edges: BrainEdge[]): LayoutNode[] {
  const positions = new Map<string, THREE.Vector3>();
  const seeded = (seed: number) => {
    let value = seed;
    return () => {
      value = (value * 16807) % 2147483647;
      return (value - 1) / 2147483646;
    };
  };
  const random = seeded(20260826);
  nodes.forEach((node, index) => {
    const angle = random() * Math.PI * 2;
    const radius = 1.5 + random() * 5.5;
    positions.set(
      node.id,
      new THREE.Vector3(
        Math.cos(angle) * radius,
        (random() - 0.5) * 4,
        Math.sin(angle) * radius,
      ),
    );
  });

  const adjacency = new Map<string, string[]>();
  edges.forEach((edge) => {
    if (!positions.has(edge.source_id) || !positions.has(edge.target_id)) return;
    adjacency.set(edge.source_id, [...(adjacency.get(edge.source_id) ?? []), edge.target_id]);
    adjacency.set(edge.target_id, [...(adjacency.get(edge.target_id) ?? []), edge.source_id]);
  });

  const ITERATIONS = nodes.length > 400 ? 12 : 30;
  const REPULSION = 2.6;
  const ATTRACTION = 0.02;
  const ids = nodes.map((n) => n.id);
  for (let iter = 0; iter < ITERATIONS; iter += 1) {
    const forces = new Map<string, THREE.Vector3>();
    ids.forEach((id) => forces.set(id, new THREE.Vector3()));

    // Repel every pair a little (capped sample for large graphs so
    // this stays O(n) instead of O(n^2) once node counts get real).
    const sampleStep = ids.length > 250 ? Math.ceil(ids.length / 250) : 1;
    for (let i = 0; i < ids.length; i += 1) {
      for (let j = i + 1; j < ids.length; j += sampleStep) {
        const a = positions.get(ids[i])!;
        const b = positions.get(ids[j])!;
        const delta = new THREE.Vector3().subVectors(a, b);
        const distance = Math.max(0.4, delta.length());
        const push = delta.normalize().multiplyScalar(REPULSION / (distance * distance));
        forces.get(ids[i])!.add(push);
        forces.get(ids[j])!.sub(push);
      }
    }
    // Attract connected pairs toward each other.
    edges.forEach((edge) => {
      const a = positions.get(edge.source_id);
      const b = positions.get(edge.target_id);
      if (!a || !b) return;
      const delta = new THREE.Vector3().subVectors(b, a);
      const pull = delta.multiplyScalar(ATTRACTION);
      forces.get(edge.source_id)?.add(pull);
      forces.get(edge.target_id)?.sub(pull);
    });
    ids.forEach((id) => {
      const position = positions.get(id)!;
      const force = forces.get(id)!;
      position.add(force.clampLength(0, 0.6));
    });
  }

  return nodes.map((node) => ({ ...node, position: positions.get(node.id) ?? new THREE.Vector3() }));
}

function NodeSphere({
  node,
  isSelected,
  isNeighbor,
  onSelect,
}: {
  node: LayoutNode;
  isSelected: boolean;
  isNeighbor: boolean;
  onSelect: (node: LayoutNode) => void;
}) {
  const meshRef = useRef<THREE.Mesh>(null);
  const [hovered, setHovered] = useState(false);
  const color = useMemo(() => new THREE.Color(colorForKind(node.kind)), [node.kind]);
  const size = node.kind === "core" ? 0.34 : node.kind === "evidence" ? 0.05 : 0.09;
  const baseOpacity = isSelected ? 1 : isNeighbor ? 0.9 : hovered ? 0.95 : 0.55;

  useFrame(({ clock }) => {
    if (!meshRef.current) return;
    const pulse = isSelected ? 1.6 + Math.sin(clock.elapsedTime * 3) * 0.15 : 1;
    meshRef.current.scale.setScalar((hovered ? 1.6 : 1) * pulse);
  });

  return (
    <group position={node.position}>
      <mesh
        ref={meshRef}
        onClick={(event) => {
          event.stopPropagation();
          onSelect(node);
        }}
        onPointerOver={(event) => {
          event.stopPropagation();
          setHovered(true);
          document.body.style.cursor = "pointer";
        }}
        onPointerOut={() => {
          setHovered(false);
          document.body.style.cursor = "auto";
        }}
      >
        <sphereGeometry args={[size, 16, 16]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={baseOpacity}
        />
      </mesh>
      {(hovered || isSelected) && (
        <Html distanceFactor={9} center style={{ pointerEvents: "none" }}>
          <div className="brain-graph-node-label">
            <strong>{node.label}</strong>
            <span>{node.kind}</span>
          </div>
        </Html>
      )}
    </group>
  );
}

function EdgeLines({
  edges,
  positions,
  selectedId,
}: {
  edges: BrainEdge[];
  positions: Map<string, THREE.Vector3>;
  selectedId: string | null;
}) {
  const dimGeometry = useMemo(() => {
    const points: number[] = [];
    edges.forEach((edge) => {
      const a = positions.get(edge.source_id);
      const b = positions.get(edge.target_id);
      if (!a || !b) return;
      if (selectedId && edge.source_id !== selectedId && edge.target_id !== selectedId) {
        points.push(a.x, a.y, a.z, b.x, b.y, b.z);
      }
    });
    return new Float32Array(points);
  }, [edges, positions, selectedId]);

  const highlightGeometry = useMemo(() => {
    if (!selectedId) return new Float32Array([]);
    const points: number[] = [];
    edges.forEach((edge) => {
      const a = positions.get(edge.source_id);
      const b = positions.get(edge.target_id);
      if (!a || !b) return;
      if (edge.source_id === selectedId || edge.target_id === selectedId) {
        points.push(a.x, a.y, a.z, b.x, b.y, b.z);
      }
    });
    return new Float32Array(points);
  }, [edges, positions, selectedId]);

  return (
    <>
      <lineSegments>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[dimGeometry, 3]} />
        </bufferGeometry>
        <lineBasicMaterial color="#79aaa8" transparent opacity={selectedId ? 0.06 : 0.16} />
      </lineSegments>
      {selectedId && (
        <lineSegments>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[highlightGeometry, 3]} />
          </bufferGeometry>
          <lineBasicMaterial color="#c8eeea" transparent opacity={0.85} />
        </lineSegments>
      )}
    </>
  );
}

function SlowRotate({ children }: { children: React.ReactNode }) {
  const groupRef = useRef<THREE.Group>(null);
  useFrame((_, delta) => {
    if (groupRef.current) groupRef.current.rotation.y += delta * 0.015;
  });
  return <group ref={groupRef}>{children}</group>;
}

function GraphScene({
  layout,
  edges,
  selected,
  onSelect,
}: {
  layout: LayoutNode[];
  edges: BrainEdge[];
  selected: LayoutNode | null;
  onSelect: (node: LayoutNode) => void;
}) {
  const positions = useMemo(() => {
    const map = new Map<string, THREE.Vector3>();
    layout.forEach((node) => map.set(node.id, node.position));
    return map;
  }, [layout]);

  const neighborIds = useMemo(() => {
    if (!selected) return new Set<string>();
    const set = new Set<string>();
    edges.forEach((edge) => {
      if (edge.source_id === selected.id) set.add(edge.target_id);
      if (edge.target_id === selected.id) set.add(edge.source_id);
    });
    return set;
  }, [edges, selected]);

  return (
    <>
      <ambientLight intensity={0.6} />
      <pointLight position={[6, 6, 6]} intensity={0.8} color="#9adbd5" />
      <SlowRotate>
        <EdgeLines edges={edges} positions={positions} selectedId={selected?.id ?? null} />
        {layout.map((node) => (
          <NodeSphere
            key={node.id}
            node={node}
            isSelected={selected?.id === node.id}
            isNeighbor={neighborIds.has(node.id)}
            onSelect={onSelect}
          />
        ))}
      </SlowRotate>
    </>
  );
}

function CameraRig() {
  const { camera } = useThree();
  useEffect(() => {
    camera.position.set(0, 2.5, 11);
  }, [camera]);
  return null;
}

async function fetchGraph(rootId: string | null, query: string): Promise<BrainGraphResponse> {
  const params = new URLSearchParams();
  if (rootId) params.set("root_id", rootId);
  params.set("depth", rootId ? "2" : "1");
  params.set("limit", "260");
  const response = await fetch(`${BRAIN.replace(/\/$/, "")}/api/brain-graph?${params.toString()}`, {
    signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) throw new Error(`Brain graph request failed (${response.status})`);
  const data = (await response.json()) as BrainGraphResponse;
  if (query.trim()) {
    const needle = query.trim().toLowerCase();
    const matchedIds = new Set(
      data.nodes.filter((node) => node.label.toLowerCase().includes(needle)).map((node) => node.id),
    );
    const keep = new Set(matchedIds);
    data.edges.forEach((edge) => {
      if (matchedIds.has(edge.source_id)) keep.add(edge.target_id);
      if (matchedIds.has(edge.target_id)) keep.add(edge.source_id);
    });
    data.nodes = data.nodes.filter((node) => keep.has(node.id));
    data.edges = data.edges.filter((edge) => keep.has(edge.source_id) && keep.has(edge.target_id));
  }
  return data;
}

export function BrainGraphView({ onClose }: { onClose: () => void }) {
  const [graph, setGraph] = useState<BrainGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rootId, setRootId] = useState<string | null>(null);
  const [selected, setSelected] = useState<LayoutNode | null>(null);
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState<string>("");

  const load = useCallback(async (root: string | null, searchQuery: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchGraph(root, searchQuery);
      setGraph(data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to load the brain graph");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(rootId, query);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rootId]);

  const filteredNodes = useMemo(() => {
    if (!graph) return [];
    if (!kindFilter) return graph.nodes;
    return graph.nodes.filter((node) => node.kind === kindFilter);
  }, [graph, kindFilter]);

  const filteredEdges = useMemo(() => {
    if (!graph) return [];
    const ids = new Set(filteredNodes.map((node) => node.id));
    return graph.edges.filter((edge) => ids.has(edge.source_id) && ids.has(edge.target_id));
  }, [graph, filteredNodes]);

  const layout = useMemo(() => layoutGraph(filteredNodes, filteredEdges), [filteredNodes, filteredEdges]);

  const kindCounts = useMemo(() => {
    const counts = new Map<string, number>();
    (graph?.nodes ?? []).forEach((node) => counts.set(node.kind, (counts.get(node.kind) ?? 0) + 1));
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [graph]);

  return (
    <div className="brain-graph-overlay" role="dialog" aria-modal="true" aria-label="VYOM Brain Graph">
      <header className="brain-graph-header">
        <div className="brain-graph-title">
          <h3>VYOM Brain Graph</h3>
          <p>
            {graph ? `${filteredNodes.length} of ${graph.nodes.length} nodes · ${filteredEdges.length} links` : "loading…"}
            {graph?.truncated && " · truncated view"}
          </p>
        </div>
        <div className="brain-graph-search">
          <Search size={13} />
          <input
            type="text"
            placeholder="Search nodes…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void load(rootId, query);
            }}
          />
        </div>
        <div className="brain-graph-actions">
          {rootId && (
            <button type="button" className="brain-graph-icon-btn" onClick={() => { setRootId(null); setSelected(null); }} aria-label="Reset to full graph">
              <Maximize2 size={14} />
            </button>
          )}
          <button
            type="button"
            className="brain-graph-icon-btn"
            onClick={() => void load(rootId, query)}
            aria-label="Refresh graph"
            disabled={loading}
          >
            <RefreshCw size={14} className={loading ? "spin" : ""} />
          </button>
          <button type="button" className="brain-graph-icon-btn" onClick={onClose} aria-label="Close brain graph">
            <X size={16} />
          </button>
        </div>
      </header>

      <div className="brain-graph-body">
        <aside className="brain-graph-legend">
          <h4>Node types</h4>
          {kindCounts.map(([kind, count]) => (
            <button
              key={kind}
              type="button"
              className={`brain-graph-legend-item ${kindFilter === kind ? "active" : ""}`}
              onClick={() => setKindFilter((current) => (current === kind ? "" : kind))}
            >
              <span className="brain-graph-dot" style={{ background: colorForKind(kind) }} />
              <span>{kind}</span>
              <em>{count}</em>
            </button>
          ))}
        </aside>

        <div className="brain-graph-canvas">
          {error && <div className="brain-graph-error">{error}</div>}
          {!error && (
            <Canvas camera={{ fov: 55 }}>
              <CameraRig />
              <color attach="background" args={["#050a0b"]} />
              <fog attach="fog" args={["#050a0b", 8, 22]} />
              <GraphScene
                layout={layout}
                edges={filteredEdges}
                selected={selected}
                onSelect={(node) => setSelected(node)}
              />
              <OrbitControls enablePan enableZoom enableRotate minDistance={2} maxDistance={30} />
            </Canvas>
          )}
        </div>

        {selected && (
          <aside className="brain-graph-inspector">
            <header>
              <span className="brain-graph-dot" style={{ background: colorForKind(selected.kind) }} />
              <div>
                <h4>{selected.label}</h4>
                <p>{selected.kind} · {selected.source_store}</p>
              </div>
            </header>
            {selected.summary && <p className="brain-graph-inspector-summary">{selected.summary}</p>}
            {selected.status && <p className="brain-graph-inspector-status">status: {selected.status}</p>}
            <div className="brain-graph-inspector-actions">
              <button
                type="button"
                onClick={() => {
                  setRootId(selected.id);
                  setSelected(null);
                }}
              >
                Focus this node
              </button>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
