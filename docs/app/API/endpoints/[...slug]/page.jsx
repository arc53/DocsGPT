import { DocsBody, DocsPage, DocsTitle } from 'fumadocs-ui/layouts/docs/page';
import { notFound } from 'next/navigation';

import { OpenAPIPage } from '../../../../components/api-page';
import { PageJsonLd } from '../../../../components/PageJsonLd';
import { SiteFooter } from '../../../../components/SiteFooter';
import { endpointMetadata } from '../../../../lib/endpoints';
import { source } from '../../../../lib/source';
import { pageMetadata } from '../../../../page-meta';

// The REST endpoint pages, one per operation, generated from data/swagger.json
// (lib/openapi.js). A route of their own keeps the OpenAPI renderer's
// JavaScript off the other docs pages.
const BASE = ['API', 'endpoints'];

function endpointPage(slug) {
  const page = source.getPage([...BASE, ...slug]);
  return page?.type === 'openapi' ? page : null;
}

export default async function Page(props) {
  const { slug } = await props.params;
  const page = endpointPage(slug);
  if (!page) notFound();
  const route = page.url;

  return (
    <DocsPage full>
      <PageJsonLd route={route} metadata={endpointMetadata(page)} />
      <DocsTitle>{page.data.title}</DocsTitle>
      <DocsBody>
        <OpenAPIPage {...page.data.getOpenAPIPageProps()} />
      </DocsBody>
      <SiteFooter />
    </DocsPage>
  );
}

export function generateStaticParams() {
  return source
    .getPages()
    .filter((page) => page.type === 'openapi')
    .map((page) => ({ slug: page.slugs.slice(BASE.length) }));
}

export async function generateMetadata(props) {
  const { slug } = await props.params;
  const page = endpointPage(slug);
  if (!page) notFound();
  return pageMetadata(page.url, endpointMetadata(page));
}
