import { docsTree } from '../lib/source';

/**
 * One sidebar level as a list.
 *
 * @param {{nodes: Array<Record<string, any>>}} props The nodes.
 * @returns {import('react').JSX.Element} The list.
 */
function Level({ nodes }) {
  return (
    <ul className="ms-3 list-none space-y-1">
      {nodes.map((node, index) => {
        if (node.type === 'page') {
          return (
            <li key={node.url}>
              <a href={node.url} className="hover:text-fd-foreground">
                {node.name}
              </a>
            </li>
          );
        }
        if (node.type !== 'folder') return null;
        return (
          <li key={node.$id ?? index}>
            {node.index ? (
              <a href={node.index.url} className="hover:text-fd-foreground">
                {node.name}
              </a>
            ) : (
              <span>{node.name}</span>
            )}
            <Level nodes={node.children} />
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Every docs page, linked from every page: a collapsed list at the foot of the
 * page. The sidebar renders only the folders that are open, so without it a
 * page deep in a folder would be linked from only a handful of pages. The REST
 * endpoint pages are reached through their overview, /API/endpoints.
 *
 * @returns {import('react').JSX.Element} The index.
 */
export function SiteIndex() {
  return (
    <details className="mt-4">
      <summary className="cursor-pointer hover:text-fd-foreground">All documentation pages</summary>
      <nav aria-label="All documentation pages" className="mt-3 columns-1 gap-8 sm:columns-2 lg:columns-3">
        <Level nodes={docsTree().children} />
      </nav>
    </details>
  );
}
