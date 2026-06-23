export interface GraphNode {
  id: string;
  name: string;
  type?: string | null;
  description?: string | null;
  degree: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  type?: string | null;
  weight?: number | null;
}

export interface GraphOverview {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphNodeChunk {
  chunk_id: string;
  text: string;
  metadata?: Record<string, unknown>;
}

export interface GraphNodeDetail extends GraphNode {
  doc_freq?: number;
  chunks: GraphNodeChunk[];
}

export interface ForceGraphData {
  nodes: GraphNode[];
  links: GraphEdge[];
}

export function toForceGraphData(overview: GraphOverview): ForceGraphData {
  const nodeIds = new Set(overview.nodes.map((node) => node.id));
  const links = overview.edges.filter(
    (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target),
  );
  return { nodes: overview.nodes, links };
}

const MIN_NODE_RADIUS = 3;
const MAX_NODE_RADIUS = 12;
const COLLIDE_PAD = 4;

export function nodeRadius(degree: number, maxDegree: number): number {
  if (maxDegree <= 0) return MIN_NODE_RADIUS;
  const scale = Math.sqrt(Math.max(0, degree) / maxDegree);
  return MIN_NODE_RADIUS + scale * (MAX_NODE_RADIUS - MIN_NODE_RADIUS);
}

/** Collision radius spacing node centres apart for a readable layout. */
export function collideRadius(visualRadius: number): number {
  return visualRadius + COLLIDE_PAD;
}

export function maxDegree(nodes: GraphNode[]): number {
  return nodes.reduce((acc, node) => Math.max(acc, node.degree || 0), 0);
}

type PositionedNode = GraphNode & { x?: number; y?: number };

/**
 * Geometric hit test in graph coordinates: returns the node whose centre is
 * nearest to (gx, gy) and within its visual radius plus `slop`, or null.
 * Resolves overlaps to the closest centre and skips nodes without a position.
 */
export function nodeAtPoint(
  nodes: GraphNode[],
  gx: number,
  gy: number,
  maxDegree: number,
  slop: number,
): GraphNode | null {
  let best: GraphNode | null = null;
  let bestDistSq = Infinity;
  for (const node of nodes) {
    const positioned = node as PositionedNode;
    if (positioned.x == null || positioned.y == null) continue;
    const hitRadius = nodeRadius(node.degree, maxDegree) + slop;
    const dx = positioned.x - gx;
    const dy = positioned.y - gy;
    const distSq = dx * dx + dy * dy;
    if (distSq <= hitRadius * hitRadius && distSq < bestDistSq) {
      best = node;
      bestDistSq = distSq;
    }
  }
  return best;
}

export function nodeLabelEl(name: string): HTMLDivElement {
  const el = document.createElement('div');
  el.textContent = name ?? '';
  return el;
}
