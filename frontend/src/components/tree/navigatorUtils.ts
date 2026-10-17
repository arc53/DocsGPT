/**
 * Pure helpers for the source navigator (the file tree and the wiki pages
 * column): the node model, filtering and lookups. Kept free of React so the
 * rules are unit-testable.
 */

import type { DirectoryStructure } from './types';

export interface NavigatorNode {
  /** Unique within the tree; a file's path, a folder's path, a wiki page's path. */
  id: string;
  kind: 'folder' | 'leaf';
  label: string;
  /** Full path, matched by the filter and shown as a folder's second line. */
  path: string;
  /** Leaves under a folder. */
  count?: number;
  children?: NavigatorNode[];
}

export interface NavigatorMatch {
  node: NavigatorNode;
  /** The leaf's own folder, its path minus the name ('' at the root). */
  parentPath: string;
}

/** A path minus its last segment: 'a/b/c.md' → 'a/b', '/x.md' → ''. */
function parentOf(path: string): string {
  const cut = path.lastIndexOf('/');
  return cut > 0 ? path.slice(0, cut) : '';
}

/**
 * Leaves whose label or path contains the query, in tree order.
 *
 * @param nodes The navigator tree.
 * @param query What the user typed; blank returns nothing.
 * @returns Each match with its parent path, taken from the leaf's own path
 *   so a page deep inside a wiki group reads its full folder, not the group's.
 */
export function filterNavigatorLeaves(
  nodes: NavigatorNode[],
  query: string,
): NavigatorMatch[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const matches: NavigatorMatch[] = [];
  const walk = (list: NavigatorNode[]) => {
    for (const node of list) {
      if (node.kind === 'folder') {
        walk(node.children ?? []);
      } else if (
        node.label.toLowerCase().includes(q) ||
        node.path.toLowerCase().includes(q)
      ) {
        matches.push({ node, parentPath: parentOf(node.path) });
      }
    }
  };
  walk(nodes);
  return matches;
}

/**
 * The ids of the folders above a node, outermost first.
 *
 * @param nodes The navigator tree.
 * @param id The node to look for.
 * @returns Folder ids, or an empty list at the root or when not found.
 */
export function ancestorIds(nodes: NavigatorNode[], id: string): string[] {
  const walk = (list: NavigatorNode[], trail: string[]): string[] | null => {
    for (const node of list) {
      if (node.id === id) return trail;
      if (node.children) {
        const found = walk(node.children, [...trail, node.id]);
        if (found) return found;
      }
    }
    return null;
  };
  return walk(nodes, []) ?? [];
}

/**
 * Find a node anywhere in the tree.
 *
 * @param nodes The navigator tree.
 * @param id The node id.
 * @returns The node, or undefined.
 */
export function findNode(
  nodes: NavigatorNode[],
  id: string,
): NavigatorNode | undefined {
  for (const node of nodes) {
    if (node.id === id) return node;
    const found = node.children ? findNode(node.children, id) : undefined;
    if (found) return found;
  }
  return undefined;
}

/**
 * Count the leaves under a list of nodes.
 *
 * @param nodes Nodes to count through.
 * @returns The number of leaves.
 */
export function countLeaves(nodes: NavigatorNode[]): number {
  return nodes.reduce(
    (sum, node) =>
      sum + (node.kind === 'leaf' ? 1 : countLeaves(node.children ?? [])),
    0,
  );
}

function parseStructure(
  structure: DirectoryStructure | string | null | undefined,
): DirectoryStructure {
  if (!structure) return {};
  if (typeof structure === 'string') {
    try {
      const parsed = JSON.parse(structure);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  }
  return structure;
}

/**
 * Turn a source's directory structure into navigator nodes: folders first,
 * then files, each group sorted by name; a file shows its display name.
 *
 * @param structure The source's `directory_structure` (object or JSON string).
 * @param parent The path prefix (used by the recursion).
 * @returns Navigator nodes whose ids are the file and folder paths.
 */
export function directoryToNavigator(
  structure: DirectoryStructure | string | null | undefined,
  parent = '',
): NavigatorNode[] {
  const entries = Object.entries(parseStructure(structure));
  const folders: NavigatorNode[] = [];
  const files: NavigatorNode[] = [];
  for (const [name, node] of entries) {
    const path = parent ? `${parent}/${name}` : name;
    if (node && typeof node === 'object' && !node.type) {
      const children = directoryToNavigator(
        node as unknown as DirectoryStructure,
        path,
      );
      folders.push({
        id: path,
        kind: 'folder',
        label: name,
        path,
        count: countLeaves(children),
        children,
      });
    } else {
      const displayName =
        typeof node?.display_name === 'string' && node.display_name.trim()
          ? node.display_name
          : name;
      files.push({ id: path, kind: 'leaf', label: displayName, path });
    }
  }
  const byName = (a: NavigatorNode, b: NavigatorNode) =>
    a.path.localeCompare(b.path);
  return [...folders.sort(byName), ...files.sort(byName)];
}
