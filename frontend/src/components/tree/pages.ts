import type { DirectoryStructure, FileNode } from './types';

const isLeaf = (node: unknown): node is FileNode =>
  !!node && typeof node === 'object' && 'token_count' in node;

// What sites put between a page's own title and the site's name.
const TITLE_SEPARATORS = [' | ', ' – ', ' — ', ' - '];

function pageTitles(structure: DirectoryStructure): string[] {
  const titles: string[] = [];
  for (const node of Object.values(structure ?? {})) {
    if (isLeaf(node)) {
      if (node.url && typeof node.title === 'string' && node.title.trim())
        titles.push(node.title.trim());
    } else if (node && typeof node === 'object') {
      titles.push(...pageTitles(node as DirectoryStructure));
    }
  }
  return titles;
}

/**
 * The site name every page title ends with (` | DocsGPT Docs`), when the
 * source has two or more pages and all of them share it; else ''.
 */
function sharedTitleSuffix(titles: string[]): string {
  if (titles.length < 2) return '';
  const suffixOf = (title: string) => {
    let best = -1;
    for (const separator of TITLE_SEPARATORS) {
      const at = title.lastIndexOf(separator);
      if (at > best) best = at;
    }
    return best > 0 ? title.slice(best) : '';
  };
  const suffix = suffixOf(titles[0]);
  return suffix && titles.every((title) => suffixOf(title) === suffix)
    ? suffix
    : '';
}

function namePages(
  structure: DirectoryStructure,
  suffix: string,
): DirectoryStructure {
  const result: DirectoryStructure = {};
  for (const [name, node] of Object.entries(structure ?? {})) {
    if (isLeaf(node)) {
      let title = typeof node.title === 'string' ? node.title.trim() : '';
      if (suffix && title.endsWith(suffix))
        title = title.slice(0, -suffix.length);
      result[name] =
        node.url && title && !node.display_name
          ? { ...node, display_name: title }
          : node;
    } else if (node && typeof node === 'object') {
      result[name] = namePages(node as DirectoryStructure, suffix) as FileNode;
    } else {
      result[name] = node;
    }
  }
  return result;
}

/**
 * A Website source's tree with each page named by its title.
 *
 * A web page's leaf carries `url` and `title` (see the worker); the tree,
 * table and crumbs name a file by `display_name`, so the title goes there,
 * without the site name when every page's title ends with the same one
 * (`Security Checklist | DocsGPT Docs`). A `display_name` already set wins.
 *
 * @param structure The source's `directory_structure`.
 * @returns A copy; the input is not changed.
 */
export function withPageTitles(
  structure: DirectoryStructure,
): DirectoryStructure {
  return namePages(structure, sharedTitleSuffix(pageTitles(structure)));
}

function firstUrl(node: unknown): string | null {
  if (isLeaf(node)) return typeof node.url === 'string' ? node.url : null;
  if (!node || typeof node !== 'object') return null;
  for (const child of Object.values(node)) {
    const url = firstUrl(child);
    if (url) return url;
  }
  return null;
}

/**
 * The section a folder of a Website source stands for (`docs.x.io/Deploying/`),
 * as removing the folder skips it: its path, under the host of a page inside.
 *
 * @param structure The source's tree.
 * @param dirPath The folder's tree path.
 * @returns The address without scheme, or null when the folder holds no page.
 */
export function folderAddress(
  structure: DirectoryStructure,
  dirPath: string,
): string | null {
  let node: unknown = structure;
  const parts = dirPath.split('/').filter(Boolean);
  for (const part of parts) {
    if (!node || typeof node !== 'object' || isLeaf(node)) return null;
    node = (node as DirectoryStructure)[part];
  }
  const url = firstUrl(node);
  if (!url || isLeaf(node)) return null;
  const host = new URL(url).host;
  const path = parts[0] === host ? parts.slice(1) : parts;
  return `${host}/${path.length ? `${path.join('/')}/` : ''}`;
}

/** A page's address as shown under its title: no scheme, no trailing slash. */
export function pageAddress(url: string): string {
  return url.replace(/^[a-z][a-z0-9+.-]*:\/\//i, '').replace(/\/(?=$|\?)/, '');
}

/**
 * A page's address as a link target, only when a browser opens it as a web
 * page (`http:` or `https:`), as `sourceHref` does for an answer's sources.
 *
 * @param url The stored address.
 * @returns The address, or null.
 */
export function webHref(url: unknown): string | null {
  return typeof url === 'string' && /^https?:\/\//i.test(url) ? url : null;
}
