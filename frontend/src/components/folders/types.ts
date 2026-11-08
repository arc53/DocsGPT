import type { ResourceUsage } from '../../settings/types';

/** What a folder holds: agents (the Agents page) or sources (Knowledge). */
export type FolderType = 'agent' | 'source';

/**
 * One of the caller's folders, as `GET /api/folders?type=` lists it. Folders
 * are personal: each user files the items they can see into their own.
 */
export type Folder = {
  id: string;
  name: string;
  /** The parent folder, or null at the top level. */
  parent_id: string | null;
  type?: FolderType;
  created_at?: string;
  updated_at?: string;
  /** Direct children the caller can see (items, then folders). */
  item_count?: number;
  folder_count?: number;
  /** Source folders: the agents that read the folder live. */
  used_by?: ResourceUsage;
};

/** Folders nest at most this many levels (a top-level folder is level 1). */
export const MAX_FOLDER_DEPTH = 3;
