import 'katex/dist/katex.min.css';

import { Fragment, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import {
  oneLight,
  vscDarkPlus,
} from 'react-syntax-highlighter/dist/cjs/styles/prism';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

import CopyButton from '../components/CopyButton';
import MermaidRenderer from '../components/MermaidRenderer';
import { Button } from '../components/ui/button';
import { useDarkTheme } from '../hooks';
import classes from './ConversationBubble.module.css';

// Replaces block-level ``\[ \]`` and inline ``\( \)`` LaTeX delimiters with the
// ``$$``/``$`` forms remark-math understands.
export function preprocessLaTeX(content: string): string {
  const blockProcessedContent = content.replace(
    /\\\[(.*?)\\\]/gs,
    (_, equation) => `$$${equation}$$`,
  );
  return blockProcessedContent.replace(
    /\\\((.*?)\\\)/gs,
    (_, equation) => `$${equation}$`,
  );
}

type ContentSegment = { type: 'text' | 'mermaid'; content: string };

export function processMarkdownContent(content: string): ContentSegment[] {
  let processedContent = preprocessLaTeX(content);

  // Convert citation references [N] into markdown links [N](#cite-N)
  // so ReactMarkdown renders them as <a> tags we can style.
  // Avoid matching inside code blocks or existing links.
  processedContent = processedContent.replace(
    /(?<!\[)\[(\d+)\](?!\()/g,
    (_, num) => `[${num}](#cite-${num})`,
  );

  const contentSegments: ContentSegment[] = [];
  let lastIndex = 0;
  const regex = /```mermaid\n([\s\S]*?)```/g;
  let match;

  while ((match = regex.exec(processedContent)) !== null) {
    const textBefore = processedContent.substring(lastIndex, match.index);
    if (textBefore) contentSegments.push({ type: 'text', content: textBefore });
    contentSegments.push({ type: 'mermaid', content: match[1].trim() });
    lastIndex = match.index + match[0].length;
  }

  const textAfter = processedContent.substring(lastIndex);
  if (textAfter) contentSegments.push({ type: 'text', content: textAfter });

  return contentSegments;
}

export default function MarkdownAnswer({
  content,
  isStreaming,
}: {
  content: string;
  isStreaming?: boolean;
}) {
  const [isDarkTheme] = useDarkTheme();
  // Re-runs on every streamed token otherwise.
  const contentSegments = useMemo(
    () => processMarkdownContent(content),
    [content],
  );

  return (
    <>
      {contentSegments.map((segment, index) => (
        <Fragment key={index}>
          {segment.type === 'text' ? (
            <ReactMarkdown
              className="fade-in flex flex-col gap-3 leading-normal wrap-break-word whitespace-pre-wrap"
              remarkPlugins={[
                remarkGfm,
                [remarkMath, { singleDollarTextMath: false }],
              ]}
              rehypePlugins={[rehypeKatex]}
              components={{
                a({ href, children }) {
                  if (href?.startsWith('#cite-')) {
                    const num = href.replace('#cite-', '');
                    const sourceIdx = parseInt(num, 10) - 1;
                    return (
                      <Button
                        type="button"
                        onClick={() => {
                          const el = document.getElementById(
                            `source-${sourceIdx}`,
                          );
                          if (el) {
                            el.scrollIntoView({
                              behavior: 'smooth',
                              block: 'center',
                            });
                            el.classList.add('ring-2', 'ring-purple-500');
                            setTimeout(
                              () =>
                                el.classList.remove(
                                  'ring-2',
                                  'ring-purple-500',
                                ),
                              2000,
                            );
                          }
                        }}
                        className="mx-0.5 h-5 min-w-5 rounded-full bg-purple-100 px-1.5 text-xs font-semibold text-purple-700 hover:bg-purple-200 dark:bg-purple-900/40 dark:text-purple-300 dark:hover:bg-purple-900/60"
                        title={`Jump to source ${num}`}
                      >
                        {num}
                      </Button>
                    );
                  }
                  return (
                    <a href={href} target="_blank" rel="noopener noreferrer">
                      {children}
                    </a>
                  );
                },
                code(props) {
                  const { children, className, node, ref, ...rest } = props;
                  const match = /language-(\w+)/.exec(className || '');
                  const language = match ? match[1] : '';

                  return match ? (
                    <div className="group border-border relative overflow-hidden rounded-xl border">
                      <div className="bg-muted flex items-center justify-between px-2 py-1">
                        <span className="text-foreground dark:text-foreground text-xs font-medium">
                          {language}
                        </span>
                        <CopyButton
                          textToCopy={String(children).replace(/\n$/, '')}
                        />
                      </div>
                      <SyntaxHighlighter
                        {...rest}
                        PreTag="div"
                        language={language}
                        style={isDarkTheme ? vscDarkPlus : oneLight}
                        className="mt-0!"
                        customStyle={{ margin: 0, borderRadius: 0 }}
                      >
                        {String(children).replace(/\n$/, '')}
                      </SyntaxHighlighter>
                    </div>
                  ) : (
                    <code className="dark:bg-accent dark:text-foreground rounded-md bg-gray-200 px-2 py-1 text-xs font-normal whitespace-pre-line">
                      {children}
                    </code>
                  );
                },
                ul({ children }) {
                  return (
                    <ul
                      className={`list-inside list-disc pl-4 whitespace-normal ${classes.list}`}
                    >
                      {children}
                    </ul>
                  );
                },
                ol({ children }) {
                  return (
                    <ol
                      className={`list-inside list-decimal pl-4 whitespace-normal ${classes.list}`}
                    >
                      {children}
                    </ol>
                  );
                },
                table({ children }) {
                  return (
                    <div className="border-border relative overflow-x-auto rounded-lg border">
                      <table className="dark:text-foreground w-full text-left text-gray-700">
                        {children}
                      </table>
                    </div>
                  );
                },
                thead({ children }) {
                  return (
                    <thead className="bg-muted text-foreground text-xs uppercase">
                      {children}
                    </thead>
                  );
                },
                tr({ children }) {
                  return (
                    <tr className="border-border odd:bg-card even:bg-muted border-b">
                      {children}
                    </tr>
                  );
                },
                th({ children }) {
                  return <th className="px-6 py-3">{children}</th>;
                },
                td({ children }) {
                  return <td className="px-6 py-3">{children}</td>;
                },
              }}
            >
              {segment.content}
            </ReactMarkdown>
          ) : (
            <div className="my-4 w-full" style={{ minWidth: '100%' }}>
              <MermaidRenderer code={segment.content} isLoading={isStreaming} />
            </div>
          )}
        </Fragment>
      ))}
    </>
  );
}
