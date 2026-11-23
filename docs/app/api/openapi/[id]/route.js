import { openapi } from '../../../../lib/openapi';

// The OpenAPI document behind the endpoint pages, fetched once by the browser.
export const revalidate = false;
export const dynamicParams = false;

export async function GET(_request, { params }) {
  return Response.json((await openapi.getSchema((await params).id)).bundled);
}

export async function generateStaticParams() {
  return Object.keys(await openapi.getSchemas()).map((id) => ({ id }));
}
