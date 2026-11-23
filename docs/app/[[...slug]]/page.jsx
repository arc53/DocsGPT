import { searchPath } from 'fumadocs-core/breadcrumb';
import { createRelativeLink } from 'fumadocs-ui/mdx';
import {
  DocsBody,
  DocsPage,
  DocsTitle,
  MarkdownCopyButton,
  PageLastUpdate,
  ViewOptionsPopover,
} from 'fumadocs-ui/layouts/docs/page';
import { notFound } from 'next/navigation';

import { OpenAPIPage } from '../../components/api-page';
import { SiteFooter } from '../../components/SiteFooter';
import { getMDXComponents } from '../../mdx-components';
import {
  SITE_URL,
  jsonLd,
  lastUpdatedOf,
  pageMetadata,
  routeOf,
  structuredData,
  timestampOf,
} from '../../page-meta';
import { source } from '../../lib/source';

const GITHUB = 'https://github.com/arc53/DocsGPT';

/**
 * The sidebar folders above a page that have a page of their own (their
 * index page, listed as the folder's first item), from the top level down.
 *
 * @param {string} route The page's route.
 * @returns {Array<{name: unknown, url: string}>} The folders, for the breadcrumb JSON-LD.
 */
function parentFolders(route) {
  const path = searchPath(source.getPageTree().children, route) ?? [];
  return path
    .filter((node) => node.type === 'folder')
    .map((folder) => {
      const index =
        folder.index ?? folder.children.find((child) => child.type === 'page' && route.startsWith(`${child.url}/`));
      return index ? { name: folder.name, url: index.url } : null;
    })
    .filter(Boolean);
}

function JsonLd({ route, metadata }) {
  const parents = parentFolders(route);
  return structuredData({ route, metadata, parents }).map((data) => (
    <script
      key={data['@type']}
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: jsonLd(data) }}
    />
  ));
}

function EditLink({ path }) {
  return (
    <a
      href={`${GITHUB}/blob/main/docs/content/${encodeURI(path)}`}
      target="_blank"
      rel="noreferrer noopener"
      className="text-sm text-fd-muted-foreground hover:text-fd-accent-foreground"
    >
      Edit this page on GitHub
    </a>
  );
}

export default async function Page(props) {
  const params = await props.params;
  const route = routeOf(params.slug);
  const page = source.getPage(params.slug);
  if (!page) notFound();

  if (page.type === 'openapi') {
    const metadata = { title: page.data.title, description: page.data.description };
    return (
      <DocsPage full>
        <JsonLd route={route} metadata={metadata} />
        <DocsTitle>{page.data.title}</DocsTitle>
        <DocsBody>
          <OpenAPIPage {...page.data.getOpenAPIPageProps()} />
        </DocsBody>
        <SiteFooter />
      </DocsPage>
    );
  }

  const MDX = page.data.body;
  // "Last updated" reads the frontmatter's lastUpdated, not git, so it moves
  // only when an author says the content changed (see docs/AGENTS.md).
  const timestamp = timestampOf(lastUpdatedOf(page.data));

  const markdownUrl = route === '/' ? '/llms.mdx' : `/llms.mdx${route}`;
  // The page's own "# Title" heading opens the body, so it stays out of "On this page".
  const toc = page.data.toc.filter((item) => item.depth > 1);

  return (
    <DocsPage toc={toc} full={page.data.full} tableOfContent={{ style: 'clerk' }}>
      <JsonLd route={route} metadata={page.data} />
      <div className="flex flex-row flex-wrap items-center justify-end gap-2">
        <MarkdownCopyButton markdownUrl={markdownUrl} />
        <ViewOptionsPopover
          markdownUrl={markdownUrl}
          githubUrl={`${GITHUB}/blob/main/docs/content/${encodeURI(page.path)}`}
          pageUrl={`${SITE_URL}${route === '/' ? '/' : route}`}
        />
      </div>
      {/* Each page opens with its own "# Title" heading, so the layout adds none. */}
      <DocsBody>
        <MDX components={getMDXComponents({ a: createRelativeLink(source, page) })} />
      </DocsBody>
      <div className="flex flex-row flex-wrap items-center justify-between gap-4 empty:hidden">
        <EditLink path={page.path} />
        {timestamp && <PageLastUpdate date={new Date(timestamp)} />}
      </div>
      <SiteFooter />
    </DocsPage>
  );
}

export function generateStaticParams() {
  return source.generateParams();
}

export async function generateMetadata(props) {
  const params = await props.params;
  const page = source.getPage(params.slug);
  if (!page) notFound();
  return pageMetadata(routeOf(params.slug), page.data);
}
