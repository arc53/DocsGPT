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
const MIN_POINTER_RADIUS = 7;
const POINTER_RADIUS_PAD = 2;
const COLLIDE_PAD = 2;

export function nodeRadius(degree: number, maxDegree: number): number {
  if (maxDegree <= 0) return MIN_NODE_RADIUS;
  const scale = Math.sqrt(Math.max(0, degree) / maxDegree);
  return MIN_NODE_RADIUS + scale * (MAX_NODE_RADIUS - MIN_NODE_RADIUS);
}

/**
 * Hit-test disc radius for a node in the color-picking canvas.
 *
 * Kept deliberately close to the visual radius: the engine resolves
 * hover/click by reading a single pixel at the node centre, so a pick disc
 * larger than the inter-node spacing lets a neighbour's disc cover this
 * node's centre and steal its picks. Pair with {@link collideRadius}, which
 * spaces centres farther apart than the largest pick disc so a centre is
 * never covered by another node.
 */
export function pointerAreaRadius(visualRadius: number): number {
  return Math.max(visualRadius, MIN_POINTER_RADIUS) + POINTER_RADIUS_PAD;
}

/**
 * Collision radius keeping node centres farther apart than any pick disc,
 * so every centre pixel stays clean for the engine's exact-colour lookup.
 */
export function collideRadius(visualRadius: number): number {
  return pointerAreaRadius(visualRadius) + COLLIDE_PAD;
}

export function maxDegree(nodes: GraphNode[]): number {
  return nodes.reduce((acc, node) => Math.max(acc, node.degree || 0), 0);
}

export function nodeLabelEl(name: string): HTMLDivElement {
  const el = document.createElement('div');
  el.textContent = name ?? '';
  return el;
}
