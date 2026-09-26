import type { Components } from 'react-markdown';

/**
 * Heading renderers shared by every markdown surface (chat answers, the wiki
 * view, note artifacts, document previews). Spread into `components`.
 */
export const markdownHeadings: Components = {
  h1: ({ children }) => (
    <h1 className="mt-4 mb-2 text-xl font-semibold">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-4 mb-2 text-lg font-semibold">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-3 mb-2 text-base font-semibold">{children}</h3>
  ),
};
