import { DocsBody, DocsPage } from 'fumadocs-ui/layouts/docs/page';
import Link from 'next/link';

import { DocsShell } from '../components/DocsShell';
import { SiteFooter } from '../components/SiteFooter';
import { docsTree } from '../lib/source';

// Next.js marks a 404 noindex itself.
export const metadata = { title: 'Page not found' };

export default function NotFound() {
  return (
    <DocsShell tree={docsTree()}>
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
    </DocsShell>
  );
}
