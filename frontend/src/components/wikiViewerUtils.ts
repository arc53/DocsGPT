import type { NavigatorNode } from './tree/navigatorUtils';

export interface WikiPageNode {
  path: string;
  title?: string | null;
  token_count?: number;
  embed_status?: string;
  version?: number;
  updated_by?: string | null;
  updated_via?: string | null;
  updated_at?: string | null;
  content?: string;
}

export function provenanceKey(
  via?: string | null,
  by?: string | null,
  currentUserSub?: string | null,
): 'you' | 'agent' | 'human' | 'unknown' {
  if (by && currentUserSub && by === currentUserSub) return 'you';
  if (via === 'agent') return 'agent';
  if (via === 'human') return 'human';
  return 'unknown';
}

export type SaveOutcome =
  | { status: 'saved'; page: WikiPageNode | null }
  | { status: 'conflict'; page: WikiPageNode | null }
  | { status: 'forbidden' }
  | { status: 'error' };

interface WikiSaveService {
  updateWikiPage: (
    sourceId: string,
    data: { path: string; content: string; expected_version?: number },
    token: string | null,
  ) => Promise<Response>;
  getWikiPage: (
    sourceId: string,
    path: string,
    token: string | null,
  ) => Promise<Response>;
}

export async function saveWikiPage(
  service: WikiSaveService,
  sourceId: string,
  path: string,
  draft: string,
  expectedVersion: number | undefined,
  token: string | null,
): Promise<SaveOutcome> {
  const response = await service.updateWikiPage(
    sourceId,
    { path, content: draft, expected_version: expectedVersion },
    token,
  );
  if (response.ok) {
    const data = await response.json();
    return { status: 'saved', page: data?.page ?? null };
  }
  if (response.status === 409) {
    const refreshed = await service.getWikiPage(sourceId, path, token);
    const data = await refreshed.json();
    return { status: 'conflict', page: data?.page ?? null };
  }
  if (response.status === 403) return { status: 'forbidden' };
  return { status: 'error' };
}

const ROOT_INDEX = /^\/?index\.md$/i;

/**
 * The name a wiki page shows in the pages column: its stored title, else its
 * file name without `.md`, dashes and underscores as spaces, in sentence case.
 * The root `index.md` is the wiki's home page.
 *
 * @param page The page (only `path` and `title` are read).
 * @param homeLabel The translated name of the root index page.
 * @returns The label.
 */
export function wikiPageLabel(
  page: Pick<WikiPageNode, 'path' | 'title'>,
  homeLabel = 'Home',
): string {
  const title = page.title?.trim();
  if (title) return title;
  if (ROOT_INDEX.test(page.path)) return homeLabel;
  const file = page.path.split('/').filter(Boolean).pop() ?? page.path;
  const words = file.replace(/\.md$/i, '').replace(/[-_]+/g, ' ').trim();
  if (!words) return page.path;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * Group wiki pages for the navigator: pages at the root first (the home page
 * leading), then one group per top-level folder holding every page under it.
 *
 * @param pages The wiki's pages.
 * @param homeLabel The translated name of the root index page.
 * @returns Navigator nodes whose leaf ids are the page paths.
 */
export function buildWikiNavigator(
  pages: Pick<WikiPageNode, 'path' | 'title'>[],
  homeLabel = 'Home',
): NavigatorNode[] {
  const roots: NavigatorNode[] = [];
  const groups = new Map<string, NavigatorNode[]>();
  for (const page of pages) {
    const parts = page.path.split('/').filter(Boolean);
    const leaf: NavigatorNode = {
      id: page.path,
      kind: 'leaf',
      label: wikiPageLabel(page, homeLabel),
      path: page.path,
    };
    if (parts.length <= 1) {
      roots.push(leaf);
    } else {
      const list = groups.get(parts[0]) ?? [];
      list.push(leaf);
      groups.set(parts[0], list);
    }
  }
  const isHome = (node: NavigatorNode) => ROOT_INDEX.test(node.path);
  roots.sort(
    (a, b) =>
      Number(isHome(b)) - Number(isHome(a)) || a.label.localeCompare(b.label),
  );
  const folders = [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, children]): NavigatorNode => {
      children.sort((a, b) => a.path.localeCompare(b.path));
      return {
        id: `folder:/${name}`,
        kind: 'folder',
        label: name,
        path: `/${name}`,
        count: children.length,
        children,
      };
    });
  return [...roots, ...folders];
}

/** A page path without its leading slashes: the API writes `/a.md`, links may not. */
const barePath = (path: string) => path.replace(/^\/+/, '');

/**
 * The wiki page a link inside a page points at, as a path without its
 * leading slash: `/a/b.md` from the wiki's root, `b.md`, `./b.md` or
 * `../b.md` from the linking page's folder.
 *
 * @param href The link as written.
 * @param fromPath The path of the page the link is on.
 * @returns The target path, or null for a link that leaves the wiki (a web
 *   address, mail, an in-page `#anchor`).
 */
export function wikiLinkTarget(href: string, fromPath: string): string | null {
  const raw = href.trim();
  if (!raw || raw.startsWith('#') || raw.startsWith('//')) return null;
  if (/^[a-z][a-z0-9+.-]*:/i.test(raw)) return null;
  let path = raw.split(/[?#]/)[0];
  try {
    path = decodeURIComponent(path);
  } catch {
    // A stray % stays as written.
  }
  const base = path.startsWith('/')
    ? []
    : barePath(fromPath).split('/').slice(0, -1);
  const segments: string[] = [];
  for (const part of [...base, ...path.split('/')]) {
    if (!part || part === '.') continue;
    if (part === '..') segments.pop();
    else segments.push(part);
  }
  return segments.length ? segments.join('/') : null;
}

/**
 * The page of `pages` at `path`, ignoring leading slashes; a link may also
 * leave off the `.md`.
 *
 * @param pages The wiki's pages.
 * @param path A page path, as `wikiLinkTarget` or a citation names it.
 * @returns The page, or undefined when the wiki has none there.
 */
export function findWikiPage(
  pages: WikiPageNode[],
  path: string,
): WikiPageNode | undefined {
  const wanted = barePath(path);
  return (
    pages.find((page) => barePath(page.path) === wanted) ??
    pages.find((page) => barePath(page.path) === `${wanted}.md`)
  );
}
