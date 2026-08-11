import { SyntheticEvent } from 'react';

export interface FileNode {
  type?: string;
  token_count?: number;
  size_bytes?: number;
  display_name?: string;
  [key: string]: any;
}

export interface DirectoryStructure {
  [key: string]: FileNode;
}

export interface SearchResult {
  name: string;
  path: string;
  isFile: boolean;
}

export type TreeMenuOption = {
  icon: string;
  label: string;
  onClick: (event: SyntheticEvent) => void;
  variant: 'default' | 'destructive';
  iconWidth?: number;
  iconHeight?: number;
};

/**
 * Row context passed to consumers' getRowMenuOptions callbacks so they
 * can build per-row menus (e.g. add a Delete option for upload trees).
 */
export interface RowMenuContext {
  name: string;
  isFile: boolean;
  itemId: string;
  displayName?: string;
  /** Default "View" option already provided by TreeBrowser. */
  defaultViewOption: TreeMenuOption;
}

/**
 * Controller exposed to wrappers via the controllerRef prop so they can
 * trigger a refresh of the directory structure after a successful
 * mutation (upload, delete, sync, etc.).
 */
export interface TreeBrowserController {
  refreshDirectory: () => Promise<boolean>;
  /** Resets the breadcrumb path back to the root. */
  resetPath: () => void;
}
