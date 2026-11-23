import { source } from '../../../lib/source';

// Each docs page as Markdown, for the "Copy page" button and the "Open in…"
// menu (app/[[...slug]]/page.jsx). Search engines keep to the HTML pages:
// the noindex header leaves these out of their results.
export const revalidate = false;
export const dynamicParams = false;

export async function GET(_request, { params }) {
  const { slug } = await params;
  const page = source.getPage(slug);
  if (!page || page.type !== 'docs') return new Response(null, { status: 404 });
  const markdown = await page.data.getText('processed');
  return new Response(markdown, {
    headers: {
      'Content-Type': 'text/markdown; charset=utf-8',
      'X-Robots-Tag': 'noindex',
    },
  });
}

export function generateStaticParams() {
  return source
    .getPages()
    .filter((page) => page.type === 'docs')
    .map((page) => ({ slug: page.slugs }));
}
