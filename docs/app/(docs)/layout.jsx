import { DocsShell } from '../../components/DocsShell';
import { docsTree } from '../../lib/source';

// The sidebar of the docs pages; the REST endpoint pages have their own (app/API/endpoints/layout.jsx).
export default function DocsPagesLayout({ children }) {
  return <DocsShell tree={docsTree()}>{children}</DocsShell>;
}
