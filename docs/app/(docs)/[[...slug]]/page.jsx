import { createRelativeLink } from 'fumadocs-ui/mdx';
import {
  DocsBody,
  DocsPage,
  MarkdownCopyButton,
  PageLastUpdate,
  ViewOptionsPopover,
} from 'fumadocs-ui/layouts/docs/page';
import { notFound } from 'next/navigation';

import { PageJsonLd } from '../../../components/PageJsonLd';
import { SiteFooter } from '../../../components/SiteFooter';
import { getMDXComponents } from '../../../mdx-components';
import { SITE_URL, lastUpdatedOf, pageMetadata, routeOf, timestampOf } from '../../../page-meta';
import { source } from '../../../lib/source';

const GITHUB = 'https://github.com/arc53/DocsGPT';

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
  // The REST endpoint pages have their own route, app/API/endpoints/[...slug].
  if (!page || page.type !== 'docs') notFound();

  const MDX = page.data.body;
  // "Last updated" reads the frontmatter's lastUpdated, not git, so it moves
  // only when an author says the content changed (see docs/AGENTS.md).
  const timestamp = timestampOf(lastUpdatedOf(page.data));

  const markdownUrl = route === '/' ? '/llms.mdx' : `/llms.mdx${route}`;
  // The page's own "# Title" heading opens the body, so it stays out of "On this page".
  const toc = page.data.toc.filter((item) => item.depth > 1);

  return (
    <DocsPage toc={toc} full={page.data.full} tableOfContent={{ style: 'clerk' }}>
      <PageJsonLd route={route} metadata={page.data} />
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
  return source
    .getPages()
    .filter((page) => page.type === 'docs')
    .map((page) => ({ slug: page.slugs }));
}

export async function generateMetadata(props) {
  const params = await props.params;
  const page = source.getPage(params.slug);
  if (!page || page.type !== 'docs') notFound();
  return pageMetadata(routeOf(params.slug), page.data);
}
