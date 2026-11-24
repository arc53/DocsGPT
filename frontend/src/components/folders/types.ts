import type { ResourceUsage } from '../../settings/types';

/**
 * What a folder can hold, each kind on its own page: agents (Agents), sources
 * (Knowledge), tools (Tools) and prompts (Prompts).
 */
export type ItemKind = 'agent' | 'source' | 'tool' | 'prompt';

/** The four kinds in the order a folder lists them. */
export const ITEM_KINDS: readonly ItemKind[] = [
  'agent',
  'source',
  'tool',
  'prompt',
];

/**
 * A folder of the current workspace's one tree, as `GET /api/folders` lists
 * it: the caller's own in Personal, the team's in a team. It holds items of
 * every kind; each page shows its own part of it.
 */
export type Folder = {
  id: string;
  name: string;
  /** The parent folder, or null at the top level. */
  parent_id: string | null;
  /** The kind the request named; folders have no kind of their own. */
  type?: ItemKind;
  created_at?: string;
  updated_at?: string;
  /** Who made it ("You" or a teammate), or null when unknown. */
  created_by?: { user_id?: string | null; label?: string | null } | null;
  /** Items of each kind filed directly in it that the caller can see. */
  counts?: Partial<Record<ItemKind, number>>;
  /**
   * Direct items the caller can see: of the requested kind, or of every kind
   * when the request named none. Read `counts` for one kind.
   */
  item_count?: number;
  /** Folders directly in it. */
  folder_count?: number;
  /** The agents that read the folder's sources live. */
  used_by?: ResourceUsage;
};

/** Folders nest at most this many levels (a top-level folder is level 1). */
export const MAX_FOLDER_DEPTH = 3;
