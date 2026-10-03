import { normalizePages } from 'nextra/normalize-pages';
import { getPageMap } from 'nextra/page-map';
import { generateStaticParamsFor, importPage } from 'nextra/pages';

import {
  flattenPages,
  jsonLd,
  lastUpdatedOf,
  pageMetadata,
  routeOf,
  structuredData,
  timestampOf,
} from '../../page-meta';
import { useMDXComponents } from '../../mdx-components';

export const generateStaticParams = generateStaticParamsFor('mdxPath');

export async function generateMetadata(props) {
  const params = await props.params;
  const { metadata } = await importPage(params?.mdxPath);
  return pageMetadata(routeOf(params?.mdxPath), metadata);
}

const Wrapper = useMDXComponents().wrapper;

export default async function Page(props) {
  const params = await props.params;
  const route = routeOf(params?.mdxPath);
  const result = await importPage(params?.mdxPath);
  const { default: MDXContent, sourceCode, toc } = result;
  // The theme's "Last updated on" line reads metadata.timestamp. It comes from
  // the frontmatter's lastUpdated, not from git, so it moves only when an
  // author says the content changed.
  const metadata = {
    ...result.metadata,
    timestamp: timestampOf(lastUpdatedOf(result.metadata)),
  };

  const pageMap = await getPageMap();
  const { activePath } = normalizePages({ list: pageMap, route });
  const pageRoutes = new Set(flattenPages(pageMap).map((page) => page.route));
  const schema = structuredData({ route, metadata, activePath, pageRoutes });

  return (
    <Wrapper metadata={metadata} sourceCode={sourceCode} toc={toc}>
      {schema.map((data) => (
        <script
          key={data['@type']}
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd(data) }}
        />
      ))}
      <MDXContent {...props} params={params} />
    </Wrapper>
  );
}
