import 'katex/dist/katex.min.css';

import { Fragment, type ReactNode, useMemo } from 'react';
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
import {
  resolveSandboxLink,
  type SandboxArtifact,
  sandboxUrlTransform,
} from './sandboxLinks';

// One fenced block or inline code span. Backtick runs are length-matched, so a
// ```` fence closes only on ```` and nested fences stay masked. The
// unterminated alternatives keep an open span matched too: answers stream in,
// so a fence is open for most of its life and needs protecting the whole time,
// not just once the closing fence arrives. A backtick fence's info string may
// not itself contain backticks, so a line that opens with an inline span stays
// an inline span. Four-space indented blocks are deliberately not masked —
// list continuation lines are indented the same way, and masking those would
// drop real citations out of nested lists.
const CODE_SPAN =
  /(?<![^\n])[ \t]*(`{3,})[^`\n]*(?![^\n])(?:[\s\S]*?\n[ \t]*\1`*[ \t]*\r?(?![^\n])|[\s\S]*$)|(?<![^\n])[ \t]*(~{3,})[^\n]*(?:[\s\S]*?\n[ \t]*\2~*[ \t]*\r?(?![^\n])|[\s\S]*$)|(`+)(?:[^\n]|\n(?![ \t\r]*\n))*?(?<!`)\3(?!`)|`+[^`\n]*$/g;

// ``\[ \]`` and ``\( \)`` LaTeX, which remark-math does not recognise.
const LATEX_SPAN = /\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)/g;

// Applies `transform` to everything outside the regions `mask` matches, and
// `onMasked` to those regions themselves.
function transformOutside(
  content: string,
  mask: RegExp,
  transform: (segment: string) => string,
  onMasked: (segment: string) => string = (segment) => segment,
): string {
  const pattern = new RegExp(mask.source, mask.flags); // its own lastIndex
  let result = '';
  let index = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(content)) !== null) {
    result += transform(content.slice(index, match.index)) + onMasked(match[0]);
    index = pattern.lastIndex;
  }
  return result + transform(content.slice(index));
}

// Runs `transform` over the prose in `content`, leaving code untouched.
//
// The rewrites below are plain regex over the whole document, and both used to
// corrupt the user's own code: `print(row[0])` rendered as
// `print(row[0](#cite-0))`, and `PS1="\[\e[0m\]"` as `PS1="$$\e[0m$$"`. Neither
// can move into a remark plugin: remark-math tokenises `$`/`$$` while parsing,
// so the LaTeX pass has to run on the raw string before remark ever sees it.
export function applyOutsideCode(
  content: string,
  transform: (segment: string) => string,
): string {
  return transformOutside(content, CODE_SPAN, transform);
}

// Rewrites one LaTeX span into the ``$$``/``$`` form remark-math parses.
function toDollarMath(span: string): string {
  const equation = span.slice(2, -2);
  return span.startsWith('\\[') ? `$$${equation}$$` : `$${equation}$`;
}

// Replaces block-level ``\[ \]`` and inline ``\( \)`` LaTeX delimiters with the
// ``$$``/``$`` forms remark-math understands.
export function preprocessLaTeX(content: string): string {
  return applyOutsideCode(content, (prose) =>
    prose.replace(LATEX_SPAN, toDollarMath),
  );
}

// Turns citation references ``[N]`` into ``[N](#cite-N)`` links so
// ReactMarkdown renders them as <a> tags we can style. The lookarounds skip
// references that are already links.
function linkCitations(prose: string): string {
  return prose.replace(
    /(?<!\[)\[(\d+)\](?!\()/g,
    (_, num) => `[${num}](#cite-${num})`,
  );
}

type ContentSegment = { type: 'text' | 'mermaid'; content: string };

export function processMarkdownContent(content: string): ContentSegment[] {
  // Citations are linked outside code — an index subscript like `row[0]` is not
  // a citation — and outside the math this same pass produces. Math the answer
  // already wrote as ``$…$`` stays unmasked, since ``$`` is also a currency
  // sign. This has to run before the ```mermaid split below, so diagram source
  // needs the same guard.
  const processedContent = applyOutsideCode(content, (prose) =>
    transformOutside(prose, LATEX_SPAN, linkCitations, toDollarMath),
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
  artifacts,
  turnArtifacts,
  onOpenArtifact,
}: {
  content: string;
  isStreaming?: boolean;
  /**
   * Every artifact in the conversation, in creation order (``A1`` is the
   * first) — refs are conversation-scoped, so a link may name an earlier turn's
   * file.
   */
  artifacts?: SandboxArtifact[];
  /** This turn's own artifacts; the filename fallback prefers them. */
  turnArtifacts?: SandboxArtifact[];
  onOpenArtifact?: (artifact: { id: string; toolName: string }) => void;
}) {
  const [isDarkTheme] = useDarkTheme();
  // Re-runs on every streamed token otherwise.
  const contentSegments = useMemo(
    () => processMarkdownContent(content),
    [content],
  );

  // Shared by the `a` and `img` renderers: a generated file is already on the
  // turn as a download chip, so both point at the chip rather than at a URL no
  // browser can open.
  const renderArtifactChip = (
    artifact: SandboxArtifact,
    content: ReactNode,
  ) => {
    if (!onOpenArtifact) return <>{content}</>;
    return (
      <Button
        type="button"
        variant="link"
        onClick={() =>
          onOpenArtifact({
            id: artifact.id,
            toolName: artifact.toolName ?? '',
          })
        }
        /* Sits mid-sentence: no pill background, no fixed height, and it must
           wrap with the surrounding text. */
        className="text-primary h-auto w-auto bg-transparent p-0 whitespace-normal underline underline-offset-2"
        title={artifact.label}
      >
        {content}
      </Button>
    );
  };

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
              urlTransform={sandboxUrlTransform}
              components={{
                a({ href, children }) {
                  // A generated file is already on the turn as a download
                  // chip, but the model links it with a `sandbox:`/`artifact:`
                  // URL no browser can open. Point the link at the chip
                  // instead, and never leave a dead anchor behind.
                  const sandboxLink = resolveSandboxLink(
                    href,
                    artifacts,
                    turnArtifacts,
                  );
                  if (sandboxLink.kind === 'plain') {
                    return <>{children}</>;
                  }
                  if (sandboxLink.kind === 'artifact') {
                    return renderArtifactChip(sandboxLink.artifact, children);
                  }
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
                img({ src, alt }) {
                  // `![chart](sandbox:/mnt/data/chart.png)` is how a model
                  // announces a plot it produced. react-markdown runs
                  // urlTransform over `src` too, so without this the invented
                  // scheme survives and renders a broken-image box beside the
                  // chip that opens the very same file.
                  const source = typeof src === 'string' ? src : undefined;
                  const sandboxLink = resolveSandboxLink(
                    source,
                    artifacts,
                    turnArtifacts,
                  );
                  if (sandboxLink.kind === 'artifact') {
                    const { artifact } = sandboxLink;
                    return renderArtifactChip(
                      artifact,
                      alt || artifact.label || 'Open file',
                    );
                  }
                  if (sandboxLink.kind === 'plain') {
                    return <>{alt ?? ''}</>;
                  }
                  return <img src={source} alt={alt} className="max-w-full" />;
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
