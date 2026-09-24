import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/**
 * Minimal GFM markdown renderer for artifact text previews. ReactMarkdown
 * parses to React elements (no `dangerouslySetInnerHTML`), so untrusted
 * markdown bytes never become raw DOM in the app origin.
 */
export default function MarkdownPreview({ content }: { content: string }) {
  return (
    <div className="h-full overflow-auto p-4">
      <div className="text-foreground flex flex-col gap-3 text-sm leading-normal break-words whitespace-pre-wrap">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a({ children, href }) {
              return (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline"
                >
                  {children}
                </a>
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
            h1({ children }) {
              return <h1 className="text-xl font-bold">{children}</h1>;
            },
            h2({ children }) {
              return <h2 className="text-lg font-bold">{children}</h2>;
            },
            h3({ children }) {
              return <h3 className="text-base font-bold">{children}</h3>;
            },
            code({ children, ...rest }) {
              return (
                <code
                  className="bg-accent rounded-md px-2 py-1 text-xs font-normal"
                  {...rest}
                >
                  {children}
                </code>
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
