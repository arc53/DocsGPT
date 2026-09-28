import 'katex/dist/katex.min.css';
// Registers `\ce` and `\pu` with the KaTeX that rehype-katex renders with.
import 'katex/contrib/mhchem';

import { Fragment, memo, type ReactNode, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import ReactMarkdown, { type Components } from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import {
  oneLight,
  vscDarkPlus,
} from 'react-syntax-highlighter/dist/cjs/styles/prism';
import rehypeKatex from 'rehype-katex';
import type { PluggableList } from 'unified';

import { markdownHeadings } from '@/lib/markdown';

import CopyButton from '../components/CopyButton';
import MermaidRenderer from '../components/MermaidRenderer';
import { Button } from '../components/ui/button';
import { useDarkTheme } from '../hooks';
import classes from './ConversationBubble.module.css';
import {
  answerSyntaxPlugins,
  healStreamingMarkdown,
  normalizeMathFences,
  splitAnswerBlocks,
} from './markdown/answerMarkdown';
import { remarkCitations } from './markdown/remarkCitations';
import { remarkDisplayMath } from './markdown/remarkDisplayMath';
import {
  resolveSandboxLink,
  type SandboxArtifact,
  sandboxUrlTransform,
} from './sandboxLinks';
import { cn } from '@/lib/utils';

// A formula KaTeX cannot typeset (a half-streamed one, most often) shows its
// source in the muted text colour rather than KaTeX's red.
const rehypePlugins: PluggableList = [
  [rehypeKatex, { errorColor: 'var(--muted-foreground)' }],
];

// One top-level block of the answer. Memoised, so while an answer streams only
// the block that is still growing is parsed and typeset again.
const MarkdownBlock = memo(function MarkdownBlock({
  content,
  remarkPlugins,
  components,
}: {
  content: string;
  remarkPlugins: PluggableList;
  components: Components;
}) {
  return (
    <ReactMarkdown
      remarkPlugins={remarkPlugins}
      rehypePlugins={rehypePlugins}
      urlTransform={sandboxUrlTransform}
      components={components}
    >
      {content}
    </ReactMarkdown>
  );
});

// Artifact lists are rebuilt on every render of the bubble; keep one identity
// per content so the memoised blocks are not re-rendered for nothing.
function useStableArtifacts(list?: SandboxArtifact[]) {
  const signature = JSON.stringify(
    list?.map(({ id, label, toolName, ref }) => [id, label, toolName, ref]),
  );
  return useMemo(() => list, [signature]);
}

type AnswerGroup =
  { type: 'markdown'; blocks: string[] } | { type: 'mermaid'; content: string };

export default function MarkdownAnswer({
  content,
  isStreaming,
  sourceCount,
  artifacts: artifactsProp,
  turnArtifacts: turnArtifactsProp,
  onOpenArtifact,
}: {
  content: string;
  isStreaming?: boolean;
  /**
   * How many sources the answer cites from; ``[N]`` beyond it is left as
   * text, with no source to jump to. Unset links every ``[N]``.
   */
  sourceCount?: number;
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
  const { t } = useTranslation();
  const [isDarkTheme] = useDarkTheme();
  const artifacts = useStableArtifacts(artifactsProp);
  const turnArtifacts = useStableArtifacts(turnArtifactsProp);

  const groups = useMemo(() => {
    const normalized = normalizeMathFences(content);
    const blocks = splitAnswerBlocks(
      isStreaming ? healStreamingMarkdown(normalized) : normalized,
    );
    // Consecutive markdown blocks share one column; a diagram breaks it.
    const grouped: AnswerGroup[] = [];
    for (const block of blocks) {
      const last = grouped[grouped.length - 1];
      if (block.type === 'mermaid') grouped.push(block);
      else if (last?.type === 'markdown') last.blocks.push(block.content);
      else grouped.push({ type: 'markdown', blocks: [block.content] });
    }
    return grouped;
  }, [content, isStreaming]);

  const remarkPlugins = useMemo<PluggableList>(
    () => [
      ...answerSyntaxPlugins,
      remarkDisplayMath,
      [remarkCitations, { sourceCount }],
    ],
    [sourceCount],
  );

  const components = useMemo<Components>(() => {
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
          size="inline"
          onClick={() =>
            onOpenArtifact({
              id: artifact.id,
              toolName: artifact.toolName ?? '',
            })
          }
          /* Sits mid-sentence, so it must wrap with the surrounding text. */
          className="whitespace-normal"
        >
          {content}
        </Button>
      );
    };

    return {
      ...markdownHeadings,
      a({ href, children }) {
        // A generated file is already on the turn as a download
        // chip, but the model links it with a `sandbox:`/`artifact:`
        // URL no browser can open. Point the link at the chip
        // instead, and never leave a dead anchor behind.
        const sandboxLink = resolveSandboxLink(href, artifacts, turnArtifacts);
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
              variant="secondary"
              size="xs"
              shape="pill"
              onClick={() => {
                const el = document.getElementById(`source-${sourceIdx}`);
                if (el) {
                  el.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center',
                  });
                  el.classList.add('ring-3', 'ring-primary');
                  setTimeout(
                    () => el.classList.remove('ring-3', 'ring-primary'),
                    2000,
                  );
                }
              }}
              className="mx-0.5 h-5 min-w-5"
              title={t('conversation.jumpToSource', { num })}
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
            alt || artifact.label || t('conversation.openFile'),
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
              <span className="text-foreground text-xs font-medium">
                {language}
              </span>
              <CopyButton
                textToCopy={String(children).replace(/\n$/, '')}
                side="bottom"
              />
            </div>
            <SyntaxHighlighter
              {...rest}
              PreTag="div"
              language={language}
              /* eslint-disable-next-line shadcn/no-inline-styles -- SyntaxHighlighter's style prop is its Prism theme object (oneLight / vscDarkPlus), picked by theme at runtime; it is not CSS. See DESIGN.md, Approved exceptions. */
              style={isDarkTheme ? vscDarkPlus : oneLight}
              className="mt-0!"
              customStyle={{ margin: 0, borderRadius: 0 }}
            >
              {String(children).replace(/\n$/, '')}
            </SyntaxHighlighter>
          </div>
        ) : (
          <code className="bg-accent text-foreground rounded-md px-2 py-1 text-xs font-normal whitespace-pre-line">
            {children}
          </code>
        );
      },
      ul({ children }) {
        return (
          <ul
            className={cn(
              'list-inside list-disc pl-4 whitespace-normal',
              classes.list,
            )}
          >
            {children}
          </ul>
        );
      },
      ol({ children }) {
        return (
          <ol
            className={cn(
              'list-inside list-decimal pl-4 whitespace-normal',
              classes.list,
            )}
          >
            {children}
          </ol>
        );
      },
      table({ children }) {
        return (
          <div className="border-border relative overflow-x-auto rounded-lg border">
            <table className="text-foreground w-full text-left">
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
    };
  }, [t, isDarkTheme, artifacts, turnArtifacts, onOpenArtifact]);

  return (
    <>
      {groups.map((group, index) => (
        <Fragment key={index}>
          {group.type === 'markdown' ? (
            <div
              className={cn(
                'animate-in fade-in flex flex-col gap-3 leading-normal wrap-break-word whitespace-pre-wrap duration-160 ease-out motion-reduce:animate-none',
                classes.answer,
              )}
            >
              {group.blocks.map((block, blockIndex) => (
                <MarkdownBlock
                  key={blockIndex}
                  content={block}
                  remarkPlugins={remarkPlugins}
                  components={components}
                />
              ))}
            </div>
          ) : (
            <div className="my-4 w-full min-w-full">
              <MermaidRenderer code={group.content} isLoading={isStreaming} />
            </div>
          )}
        </Fragment>
      ))}
    </>
  );
}
