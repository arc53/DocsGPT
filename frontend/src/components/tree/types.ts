import type { MenuOption } from '../ui/dropdown-menu';

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

/**
 * Row context passed to consumers' getRowMenuOptions callbacks so they
 * can build per-row menus (e.g. add a Delete option for upload trees).
 */
export interface RowMenuContext {
  name: string;
  isFile: boolean;
  itemId: string;
  displayName?: string;
  /** The file's node (a web page's carries its `url`); absent for folders. */
  node?: FileNode;
  /** Default "View" option already provided by TreeBrowser. */
  defaultViewOption: MenuOption;
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
  /**
   * Lists the open file's chunks again (its content changed: a refreshed
   * page). With a path, only when that file is the open one.
   */
  reloadFile: (path?: string) => void;
}
