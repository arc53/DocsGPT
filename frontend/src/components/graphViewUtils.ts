import i18next from 'i18next';

import { readCssVar, SERIES_TOKENS } from '../utils/chartUtils';
import { intlLocale } from '../utils/dateTimeUtils';

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

/** One edge touching a node, joined to the node at its other end. */
export interface GraphRelationship {
  id: string;
  name: string;
  type?: string | null;
  degree: number;
  edge_type?: string | null;
  direction?: 'out' | 'in';
}

export interface GraphNodeDetail extends GraphNode {
  doc_freq?: number;
  chunks: GraphNodeChunk[];
  /** The strongest edges, capped server-side (`MAX_NODE_RELATIONSHIPS`). */
  relationships?: GraphRelationship[];
  /** Every edge the node takes part in; above `relationships.length` when capped. */
  relationships_total?: number;
}

/** A row of the paged `/graph/nodes` list. */
export interface GraphNodeSummary {
  id: string;
  name: string;
  type?: string | null;
  degree: number;
  doc_freq?: number | null;
}

/** One type key over every node of the source (the `/graph/nodes` facet). */
export interface GraphTypeFacet {
  key: string;
  label: string | null;
  count: number;
}

/** Totals for the whole graph, beyond the loaded overview. */
export interface GraphStats {
  nodes: number;
  edges: number;
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

/** Resolved canvas colours for the graph view. */
export interface GraphPalette {
  /** The four type series (`--chart-1` to `--chart-4`). */
  series: string[];
  /** Nodes folded into "Other" (`--muted-foreground`, not chart-5's red). */
  other: string;
  /** The selection's edges (`--primary`). */
  primary: string;
  /** Ring around the hovered and selected node (`--foreground`). */
  hoverStroke: string;
  /** Edge colour (`--border`). */
  link: string;
  /** Label text (`--foreground`). */
  label: string;
  /** Label halo (`--background`, the canvas surface, so it works in both themes). */
  halo: string;
  /** The app font (`--font-sans`) for labels. */
  font: string;
}

/**
 * Resolve the graph canvas colours from the current theme tokens.
 *
 * The canvas can't read CSS variables, so the view re-reads this on every
 * theme change. Fallbacks are the light-theme values from src/index.css.
 *
 * @returns Concrete colour strings for the canvas.
 */
export function readGraphPalette(): GraphPalette {
  const foreground = readCssVar('--foreground', '#171717');
  return {
    series: SERIES_TOKENS.slice(0, GRAPH_TYPE_SERIES).map(([name, fallback]) =>
      readCssVar(name, fallback),
    ),
    other: readCssVar('--muted-foreground', '#737373'),
    primary: readCssVar('--primary', '#7d54d1'),
    hoverStroke: foreground,
    link: readCssVar('--border', '#d9d9d9'),
    label: foreground,
    halo: readCssVar('--background', '#ffffff'),
    font: readCssVar('--font-sans', 'sans-serif'),
  };
}

/** How many entity types get their own colour; the rest fold into Other. */
const GRAPH_TYPE_SERIES = 4;

/**
 * The key that folds spelling variants of one type together ("Service Lane",
 * "ServiceLane", "SERVICE_LANE"): lower-cased, letters and digits only. The
 * backend's `/graph/nodes?type=` filter uses the same rule.
 */
export function graphTypeKey(type: string | null | undefined): string {
  return (type ?? '').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
}

export interface GraphTypeGroup {
  key: string;
  /** The most frequent spelling of the key. */
  label: string;
  count: number;
  /** Index into the palette's series. */
  series: number;
}

export interface FoldedGraphTypes {
  groups: GraphTypeGroup[];
  /** Everything outside the groups, untyped nodes included. */
  other: { count: number; labels: string[] };
  /** The series index of a type, or null for Other. */
  seriesOf: (type: string | null | undefined) => number | null;
  /** The display spelling of a type's key. */
  labelOf: (type: string | null | undefined) => string;
}

/**
 * Fold the loaded nodes' types for colour: the largest keys keep a series
 * each, and the rest (and untyped nodes) fold into one "Other".
 *
 * @param nodes Nodes with a `type`.
 * @param seriesCount How many keys keep their own colour.
 * @returns The groups, the Other bucket and lookups by raw type.
 */
export function foldGraphTypes(
  nodes: { type?: string | null }[],
  seriesCount = GRAPH_TYPE_SERIES,
): FoldedGraphTypes {
  const spellings = new Map<string, Map<string, number>>();
  let untyped = 0;
  for (const node of nodes) {
    const key = graphTypeKey(node.type);
    if (!key) {
      untyped += 1;
      continue;
    }
    const counts = spellings.get(key) ?? new Map<string, number>();
    const raw = (node.type ?? '').trim();
    counts.set(raw, (counts.get(raw) ?? 0) + 1);
    spellings.set(key, counts);
  }
  const ranked = [...spellings.entries()]
    .map(([key, counts]) => {
      const [label] = [...counts.entries()].sort(
        (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]),
      )[0];
      const count = [...counts.values()].reduce((a, b) => a + b, 0);
      return { key, label, count };
    })
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  const groups = ranked
    .slice(0, seriesCount)
    .map((group, series) => ({ ...group, series }));
  const rest = ranked.slice(seriesCount);
  const labels = new Map(ranked.map((g) => [g.key, g.label]));
  const seriesByKey = new Map(groups.map((g) => [g.key, g.series]));
  return {
    groups,
    other: {
      count: untyped + rest.reduce((sum, g) => sum + g.count, 0),
      labels: rest.map((g) => g.label),
    },
    seriesOf: (type) => seriesByKey.get(graphTypeKey(type)) ?? null,
    labelOf: (type) => labels.get(graphTypeKey(type)) ?? (type ?? '').trim(),
  };
}

/**
 * An edge label for reading: lower-cased, underscores as spaces, trimmed.
 * `PREFERRED_CARRIER_FOR` and `preferred_carrier_for` become one label.
 */
export function normalizeEdgeLabel(label: string | null | undefined): string {
  return (label ?? '')
    .replace(/_+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

export interface RelationshipRow {
  id: string;
  name: string;
  type?: string | null;
  degree: number;
  /** Distinct normalised labels, first seen first; empty when none had one. */
  labels: string[];
}

/**
 * One row per neighbour: the node's edges grouped by the node at the other
 * end, their labels normalised and deduplicated, the busiest neighbour first.
 *
 * @param relationships The node detail's `relationships`.
 * @returns Rows for the node panel's Relationships list.
 */
export function groupRelationships(
  relationships: GraphRelationship[],
): RelationshipRow[] {
  const rows = new Map<string, RelationshipRow>();
  for (const rel of relationships) {
    const row = rows.get(rel.id) ?? {
      id: rel.id,
      name: rel.name,
      type: rel.type,
      degree: rel.degree,
      labels: [],
    };
    const label = normalizeEdgeLabel(rel.edge_type);
    if (label && !row.labels.includes(label)) row.labels.push(label);
    rows.set(rel.id, row);
  }
  return [...rows.values()].sort(
    (a, b) => b.degree - a.degree || a.name.localeCompare(b.name),
  );
}

/**
 * Whether a keydown should clear the graph's selection: Escape, unless a
 * field is being typed in (the Graph tab's search) or something else already
 * handled the key.
 *
 * @param event The keydown event.
 * @returns True when the selection should be cleared.
 */
export function escapeDeselects(event: KeyboardEvent): boolean {
  if (event.key !== 'Escape' || event.defaultPrevented) return false;
  const target = event.target as HTMLElement | null;
  if (
    target &&
    (target.isContentEditable ||
      ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
  )
    return false;
  return true;
}

/** Folded type names the "Other: …" line spells out before "and N more". */
export const OTHER_TYPES_SHOWN = 6;

/**
 * The folded types as a list in the UI language ("A, B, and C"; "A, B und 3
 * weitere"): the first six, then the rest as one last item.
 *
 * @param labels The folded type names, in legend order.
 * @param more Words the rest ("3 more"); gets how many were left out.
 * @param language An app language code; defaults to the current one.
 * @returns The joined list.
 */
export function otherTypesList(
  labels: string[],
  more: (count: number) => string,
  language: string = i18next.language,
): string {
  const items = labels.slice(0, OTHER_TYPES_SHOWN);
  if (labels.length > OTHER_TYPES_SHOWN) {
    items.push(more(labels.length - OTHER_TYPES_SHOWN));
  }
  return new Intl.ListFormat(intlLocale(language), {
    type: 'conjunction',
  }).format(items);
}
