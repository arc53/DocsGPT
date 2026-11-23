import { DocsShell } from '../../../components/DocsShell';
import { source } from '../../../lib/source';

// The REST endpoint pages' sidebar: the whole page tree, every endpoint included.
export default function EndpointsLayout({ children }) {
  return <DocsShell tree={source.getPageTree()}>{children}</DocsShell>;
}
