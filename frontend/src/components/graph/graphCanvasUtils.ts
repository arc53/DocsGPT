import type {
  FoldedGraphTypes,
  GraphEdge,
  GraphNode,
  GraphRelationship,
} from '../graphViewUtils';

/** The legend's key for everything folded into "Other". */
export const OTHER_GROUP_KEY = '__other';

/** How many of the busiest nodes keep a label while nothing is selected. */
const HUB_LABEL_COUNT = 10;

/** How much of a node or edge outside the selection stays visible. */
export const DIM_ALPHA = 0.15;

// Static class strings so Tailwind sees them: series 0..3, then Other.
const SERIES_DOT_CLASSES = [
  'bg-chart-1',
  'bg-chart-2',
  'bg-chart-3',
  'bg-chart-4',
] as const;
const OTHER_DOT_CLASS = 'bg-muted-foreground';

/**
 * The dot colour class for a fold series.
 *
 * @param series The series index from `foldGraphTypes().seriesOf`, or null for Other.
 * @returns A static `bg-*` class.
 */
export function seriesDotClass(series: number | null | undefined): string {
  if (series == null) return OTHER_DOT_CLASS;
  return SERIES_DOT_CLASSES[series] ?? OTHER_DOT_CLASS;
}

/**
 * The legend group a type belongs to: its fold group's key, or Other.
 *
 * @param fold The shared type fold.
 * @param type A node's raw type.
 * @returns A group key, or `OTHER_GROUP_KEY`.
 */
export function legendGroupOf(
  fold: FoldedGraphTypes,
  type: string | null | undefined,
): string {
  const series = fold.seriesOf(type);
  if (series == null) return OTHER_GROUP_KEY;
  return (
    fold.groups.find((group) => group.series === series)?.key ?? OTHER_GROUP_KEY
  );
}

type LinkEnd = string | { id?: string | number } | undefined | null;

/**
 * The node id at one end of a link. The force simulation swaps the ids for
 * the node objects once it starts, so both shapes are read.
 */
export function endpointId(end: LinkEnd): string {
  if (end == null) return '';
  if (typeof end === 'object') return String(end.id ?? '');
  return String(end);
}

/** Neighbour ids per node id, from the loaded links (both directions). */
export function buildAdjacency(
  links: Pick<GraphEdge, 'source' | 'target'>[],
): Map<string, Set<string>> {
  const adjacency = new Map<string, Set<string>>();
  const add = (from: string, to: string) => {
    const set = adjacency.get(from) ?? new Set<string>();
    set.add(to);
    adjacency.set(from, set);
  };
  for (const link of links) {
    const source = endpointId(link.source as LinkEnd);
    const target = endpointId(link.target as LinkEnd);
    if (!source || !target || source === target) continue;
    add(source, target);
    add(target, source);
  }
  return adjacency;
}

/** Ids of the `count` highest-degree nodes (ties by id, so the pick is stable). */
export function topHubIds(
  nodes: Pick<GraphNode, 'id' | 'degree'>[],
  count = HUB_LABEL_COUNT,
): Set<string> {
  return new Set(
    [...nodes]
      .sort(
        (a, b) => (b.degree || 0) - (a.degree || 0) || a.id.localeCompare(b.id),
      )
      .slice(0, count)
      .map((node) => node.id),
  );
}

/**
 * The nodes that stay at full strength while one is selected: the selection
 * and its neighbours. Null when nothing on the canvas is selected (a pick
 * outside the loaded overview draws no highlight).
 */
export function focusSet(
  selectedId: string | null | undefined,
  adjacency: Map<string, Set<string>>,
  loadedIds: Set<string>,
): Set<string> | null {
  if (!selectedId || !loadedIds.has(selectedId)) return null;
  return new Set([selectedId, ...(adjacency.get(selectedId) ?? [])]);
}

interface LabelContext {
  hubs: Set<string>;
  focus: Set<string> | null;
  hoveredId: string | null | undefined;
}

/**
 * Whether a node gets a label: with a selection, the selection and its
 * neighbours; without one, the hubs. The hovered node always does.
 */
export function nodeHasLabel(
  id: string,
  { hubs, focus, hoveredId }: LabelContext,
): boolean {
  if (id === hoveredId) return true;
  return focus ? focus.has(id) : hubs.has(id);
}

/** Whether a link touches the node. */
export function linkTouches(
  link: Pick<GraphEdge, 'source' | 'target'>,
  nodeId: string | null | undefined,
): boolean {
  if (!nodeId) return false;
  return (
    endpointId(link.source as LinkEnd) === nodeId ||
    endpointId(link.target as LinkEnd) === nodeId
  );
}

/**
 * A relationship row's label line: the first two labels joined by " · ",
 * then "+N" for the rest; the fallback ("related to") when there are none.
 */
export function relationshipLabelText(
  labels: string[],
  fallback: string,
): string {
  if (labels.length === 0) return fallback;
  const shown = labels.slice(0, 2).join(' · ');
  return labels.length > 2 ? `${shown} · +${labels.length - 2}` : shown;
}

const pickString = (value: unknown): string =>
  typeof value === 'string' && value.trim() ? value.trim() : '';

/**
 * The tree path a chunk belongs to, as the Files tab (`directory_structure`)
 * keys it: `metadata.file_path`, else `key`, else `source` unless it is a URL
 * (a web page's source is its address, not its tree path), else `title`.
 * Mirrors the backend's `_chunk_matches_path`.
 *
 * @param metadata The chunk's metadata.
 * @returns The path, or '' when the chunk names none.
 */
export function chunkFilePath(
  metadata: Record<string, unknown> | undefined,
): string {
  const filePath = pickString(metadata?.file_path);
  if (filePath) return filePath;
  const key = pickString(metadata?.key);
  if (key) return key;
  const source = pickString(metadata?.source);
  if (source && !source.includes('://')) return source;
  return pickString(metadata?.title);
}

/**
 * The file a chunk came from, for its tile's meta row: the last segment of
 * its tree path (see `chunkFilePath`), or its title as is.
 */
export function chunkFileName(
  metadata: Record<string, unknown> | undefined,
): string {
  // A title is a name, not a path: shown whole.
  const path = chunkFilePath({ ...metadata, title: undefined });
  if (!path) return pickString(metadata?.title);
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

/**
 * The relationships of a node as the loaded overview knows them: one entry
 * per link touching it, joined to the node at the other end. The fallback
 * for an API whose node detail predates `relationships`.
 *
 * @param nodeId The node.
 * @param links The overview links (ids or simulation node objects at the ends).
 * @param nodes The overview nodes, for the neighbour's name, type and degree.
 * @returns Relationships in the shape of `GraphNodeDetail.relationships`.
 */
export function overviewRelationships(
  nodeId: string,
  links: Pick<GraphEdge, 'source' | 'target' | 'type'>[],
  nodes: Pick<GraphNode, 'id' | 'name' | 'type' | 'degree'>[],
): GraphRelationship[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const out: GraphRelationship[] = [];
  for (const link of links) {
    const source = endpointId(link.source as LinkEnd);
    const target = endpointId(link.target as LinkEnd);
    if (source === target) continue;
    const direction =
      source === nodeId ? 'out' : target === nodeId ? 'in' : null;
    if (!direction) continue;
    const other = byId.get(direction === 'out' ? target : source);
    if (!other) continue;
    out.push({
      id: other.id,
      name: other.name,
      type: other.type,
      degree: other.degree,
      edge_type: link.type ?? null,
      direction,
    });
  }
  return out;
}

/** A label's text box on the canvas: centred on `x`, its top at `y`. */
export interface LabelBox {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  /** Drawn whatever it overlaps (the selection, the hovered node). */
  always?: boolean;
}

/** Whether two label boxes intersect, with `gap` of clearance kept between them. */
export function labelBoxesOverlap(a: LabelBox, b: LabelBox, gap = 0): boolean {
  return (
    Math.abs(a.x - b.x) * 2 < a.width + b.width + gap * 2 &&
    a.y < b.y + b.height + gap &&
    b.y < a.y + a.height + gap
  );
}

/**
 * Which labels to draw so none sits on another: walk the boxes in priority
 * order and keep each one that clears every box kept so far. `always` boxes
 * are kept regardless (and still block the ones after them).
 *
 * @param boxes Label boxes, highest priority first.
 * @param gap Clearance between two kept boxes.
 * @returns The ids to draw.
 */
export function pickLabels(boxes: LabelBox[], gap = 0): Set<string> {
  const kept: LabelBox[] = [];
  for (const box of boxes) {
    if (box.always || !kept.some((other) => labelBoxesOverlap(box, other, gap)))
      kept.push(box);
  }
  return new Set(kept.map((box) => box.id));
}

/**
 * A chunk's heading for its drawer title: the first line's text when that
 * line is a markdown heading (the `#`s stripped), else null.
 */
export function chunkHeading(text: string | null | undefined): string | null {
  const first = (text ?? '').trimStart().split(/\r?\n/, 1)[0] ?? '';
  const match = /^#{1,6}\s+(.*?)\s*#*\s*$/.exec(first);
  const heading = match?.[1]?.trim();
  return heading ? heading : null;
}
