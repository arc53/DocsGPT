import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { markdownCode, markdownHeadings, markdownTables } from '@/lib/markdown';

import { useDarkTheme } from '../hooks';
import { Button } from './ui/button';

/**
 * Minimal GFM markdown renderer for artifact text previews. ReactMarkdown
 * parses to React elements (no `dangerouslySetInnerHTML`), so untrusted
 * markdown bytes never become raw DOM in the app origin.
 */
export default function MarkdownPreview({ content }: { content: string }) {
  const [isDarkTheme] = useDarkTheme();
  return (
    <div className="h-full overflow-auto p-4">
      <div className="text-foreground flex flex-col gap-3 text-sm leading-normal break-words whitespace-pre-wrap">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            ...markdownHeadings,
            ...markdownTables,
            ...markdownCode({ surface: 'muted', isDarkTheme }),
            a({ children, href }) {
              return (
                <Button variant="link" size="text" asChild>
                  <a href={href} target="_blank" rel="noopener noreferrer">
                    {children}
                  </a>
                </Button>
              );
            },
            ul({ children }) {
              return (
                <ul className="list-inside list-disc pl-4 whitespace-normal">
                  {children}
                </ul>
              );
            },
            ol({ children }) {
              return (
                <ol className="list-inside list-decimal pl-4 whitespace-normal">
                  {children}
                </ol>
              );
            },
            blockquote({ children }) {
              return (
                <blockquote className="border-border border-l-4 pl-4 italic">
                  {children}
                </blockquote>
              );
            },
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </div>
  );
}
