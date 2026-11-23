import { DocsBody, DocsPage } from 'fumadocs-ui/layouts/docs/page';
import Link from 'next/link';

import { SiteFooter } from '../components/SiteFooter';

export const metadata = { title: 'Page not found', robots: { index: false } };

export default function NotFound() {
  return (
    <DocsPage>
      <DocsBody>
        <h1>Page not found</h1>
        <p>
          This page doesn&apos;t exist or has moved. Search the docs (<kbd>Ctrl</kbd>/<kbd>⌘</kbd> + <kbd>K</kbd>)
          or start from the <Link href="/">home page</Link>.
        </p>
      </DocsBody>
      <SiteFooter />
    </DocsPage>
  );
}
