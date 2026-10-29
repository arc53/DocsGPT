import type { Edge, Node, XYPosition } from 'reactflow';

import type { LoopNodeConfig } from '../types/workflow';

/** Node types a loop body may hold; the backend refuses any other. */
export const LOOP_BODY_TYPES = new Set([
  'agent',
  'code',
  'state',
  'condition',
  'note',
]);

/** A new loop's size on the canvas, room for a node or two. */
export const LOOP_DEFAULT_SIZE = { width: 420, height: 240 };
export const LOOP_MIN_SIZE = { width: 300, height: 180 };

/** Where the first node dropped into an empty loop lands, inside its header. */
export const LOOP_BODY_ORIGIN = { x: 24, y: 72 };

/** Names an item variable may not take (mirrors the backend's list). */
export const LOOP_RESERVED_VARIABLES = new Set([
  'agent',
  'artifacts',
  'system',
  'source',
  'tools',
  'passthrough',
  'query',
  'chat_history',
  'input_documents',
]);

const ITEMS_PATH_RE = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*$/;
const IDENTIFIER_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** Default config applied when a fresh loop node is dropped onto the canvas. */
export function createDefaultLoopConfig(): LoopNodeConfig {
  return {
    items: '',
    item_variable: 'item',
    concurrency: 4,
    max_items: 50,
    on_item_error: 'fail',
    output_variable: '',
  };
}

/** Whether `items` is a dotted state path such as `extracted.items`. */
export function isValidItemsPath(path: string | undefined): boolean {
  return ITEMS_PATH_RE.test((path ?? '').trim());
}

/** Whether `name` can be an item variable. */
export function isValidItemVariable(name: string | undefined): boolean {
  const trimmed = (name ?? '').trim();
  return IDENTIFIER_RE.test(trimmed) && !LOOP_RESERVED_VARIABLES.has(trimmed);
}

/** A loop's canvas size, from its style (set by the resizer) or the default. */
export function loopSize(node: Node): { width: number; height: number } {
  const width = Number(node.style?.width ?? node.width);
  const height = Number(node.style?.height ?? node.height);
  return {
    width: width > 0 ? width : LOOP_DEFAULT_SIZE.width,
    height: height > 0 ? height : LOOP_DEFAULT_SIZE.height,
  };
}

/**
 * The innermost loop under a canvas point, so a palette drop lands inside it.
 *
 * Args:
 *   nodes: The canvas nodes.
 *   point: A flow position.
 *
 * Returns:
 *   The loop node, or undefined when the point is outside every loop.
 */
export function findLoopAt(nodes: Node[], point: XYPosition): Node | undefined {
  // Loops are never nested, so a loop's position is already absolute.
  return nodes.find((node) => {
    if (node.type !== 'loop') return false;
    const origin = node.position;
    const { width, height } = loopSize(node);
    return (
      point.x >= origin.x &&
      point.x <= origin.x + width &&
      point.y >= origin.y &&
      point.y <= origin.y + height
    );
  });
}

/** A body node's position inside its loop, for a flow position. */
export function toLoopPosition(loop: Node, point: XYPosition): XYPosition {
  return { x: point.x - loop.position.x, y: point.y - loop.position.y };
}

/**
 * The saved `data` keys a canvas node's container adds: `parent_id` for a
 * body node, the canvas `size` for a loop.
 */
export function containerData(node: Node): Record<string, unknown> {
  const extra: Record<string, unknown> = {};
  if (node.parentNode) extra.parent_id = node.parentNode;
  if (node.type === 'loop') extra.size = loopSize(node);
  return extra;
}

/**
 * Splits the container keys back off a saved node's `data`.
 *
 * Returns:
 *   The data without them, and the canvas fields they stand for.
 */
export function readContainerData(data: Record<string, unknown> | undefined): {
  data: Record<string, unknown>;
  canvas: Partial<Pick<Node, 'parentNode' | 'extent' | 'style'>>;
} {
  const { parent_id: parentId, size, ...rest } = data ?? {};
  const canvas: Partial<Pick<Node, 'parentNode' | 'extent' | 'style'>> = {};
  if (typeof parentId === 'string' && parentId) {
    canvas.parentNode = parentId;
    canvas.extent = 'parent';
  }
  const savedSize = size as { width?: unknown; height?: unknown } | undefined;
  if (
    savedSize &&
    typeof savedSize.width === 'number' &&
    typeof savedSize.height === 'number'
  ) {
    canvas.style = { width: savedSize.width, height: savedSize.height };
  }
  return { data: rest, canvas };
}

/** React Flow draws a child only after its parent: loops go first. */
export function parentsFirst<T extends Pick<Node, 'parentNode'>>(
  nodes: T[],
): T[] {
  return [
    ...nodes.filter((node) => !node.parentNode),
    ...nodes.filter((node) => node.parentNode),
  ];
}

/** Whether an edge between two nodes stays on one side of every loop boundary. */
export function sameContainer(
  nodes: Node[],
  source: string | null,
  target: string | null,
): boolean {
  const parentOf = (id: string | null) =>
    nodes.find((node) => node.id === id)?.parentNode || undefined;
  return parentOf(source) === parentOf(target);
}

/**
 * Validation problems of one loop: its items path, item variable and body.
 *
 * Returns:
 *   Locale keys, each a problem; none when the loop is fine.
 */
export function loopProblems(
  loop: Node,
  nodes: Node[],
  edges: Edge[],
): string[] {
  const problems: string[] = [];
  const config: Partial<LoopNodeConfig> = loop.data?.config ?? {};
  if (!(config.items ?? '').trim()) {
    problems.push('agents.workflow.validation.loopItems');
  } else if (!isValidItemsPath(config.items)) {
    problems.push('agents.workflow.validation.loopItemsPath');
  }
  if (!isValidItemVariable(config.item_variable ?? 'item')) {
    problems.push('agents.workflow.validation.loopItemVariable');
  }
  const bodyIds = new Set(
    nodes
      .filter((node) => node.parentNode === loop.id && node.type !== 'note')
      .map((node) => node.id),
  );
  if (bodyIds.size === 0) {
    problems.push('agents.workflow.validation.loopEmpty');
    return problems;
  }
  const targets = new Set(
    edges.filter((edge) => bodyIds.has(edge.source)).map((edge) => edge.target),
  );
  const entries = [...bodyIds].filter((id) => !targets.has(id));
  if (entries.length !== 1) {
    problems.push('agents.workflow.validation.loopEntry');
  }
  return problems;
}
