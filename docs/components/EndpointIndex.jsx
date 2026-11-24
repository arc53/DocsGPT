import { ENDPOINTS_URL, source } from '../lib/source';
import { useMDXComponents } from '../mdx-components';

/**
 * The REST endpoint groups, each with its endpoint pages, from the page tree.
 *
 * @returns {Array<{name: unknown, slug: string, pages: Array<{url: string, title: string, method: string, path: string}>}>}
 *   The groups in sidebar order.
 */
function endpointGroups() {
  const find = (nodes) => {
    for (const node of nodes) {
      if (node.type !== 'folder') continue;
      if (node.index?.url === ENDPOINTS_URL) return node;
      const found = find(node.children);
      if (found) return found;
    }
    return null;
  };
  const folder = find(source.getPageTree().children);
  if (!folder) return [];
  return folder.children
    .filter((node) => node.type === 'folder')
    .map((group) => ({
      name: group.name,
      slug: group.children.find((child) => child.type === 'page')?.url.split('/').at(-2) ?? '',
      pages: group.children
        .filter((child) => child.type === 'page')
        .map((child) => {
          const page = source.getPage(child.url.slice(1).split('/'));
          const [operation] = page?.data.getOpenAPIPageProps?.().operations ?? [];
          return {
            url: child.url,
            title: String(page?.data.title ?? child.name),
            method: operation?.method?.toUpperCase() ?? '',
            path: operation?.path ?? '',
          };
        }),
    }));
}

/**
 * Every REST endpoint page, grouped as in the sidebar: method, route and title.
 *
 * @returns {import('react').JSX.Element} The index.
 */
export function EndpointIndex() {
  const { h2: H2, ul: Ul, li: Li, a: A, code: Code } = useMDXComponents();
  return endpointGroups().map((group) => (
    <section key={group.slug}>
      <H2 id={group.slug}>{group.name}</H2>
      <Ul>
        {group.pages.map((page) => (
          <Li key={page.url}>
            <A href={page.url}>{page.title}</A>
            {page.method && (
              <>
                {' '}
                <Code>
                  {page.method} {page.path}
                </Code>
              </>
            )}
          </Li>
        ))}
      </Ul>
    </section>
  ));
}
