import React from 'react';
import ReactMarkdown, {
  type Components,
  type ExtraProps,
} from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { markdownHeadings, markdownTables } from '@/lib/markdown';

import { Button } from './ui/button';

type TableProps = React.ComponentProps<'table'> & ExtraProps;

// The shared table frame, with the paragraph's bottom margin so the next
// block does not butt against it.
const SharedTable = markdownTables.table as React.ComponentType<TableProps>;
const TableFrame = (props: TableProps) => (
  <div className="mb-3">
    <SharedTable {...props} />
  </div>
);

const components: Components = {
  ...markdownHeadings,
  ...markdownTables,
  table: TableFrame,
  p: ({ children }) => <p className="mb-3">{children}</p>,
  ul: ({ children }) => (
    <ul className="mb-3 list-outside list-disc pl-5">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-3 list-outside list-decimal pl-5">{children}</ol>
  ),
  a: ({ children, href }) => (
    <Button variant="link" size="text" asChild>
      <a href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    </Button>
  ),
  // Fenced and indented code keep their lines and scroll sideways in a
  // bordered box; the inline pill below applies to inline code only.
  pre: ({ children }) => (
    <pre className="border-border mb-3 overflow-x-auto rounded-md border p-3 font-mono text-xs leading-5 [&>code]:bg-transparent [&>code]:p-0">
      {children}
    </pre>
  ),
  code: ({ children }) => (
    <code className="bg-muted rounded-sm px-1 py-0.5 font-mono text-xs">
      {children}
    </code>
  ),
  mark: ({ children }) => (
    <mark className="bg-secondary text-foreground rounded-xs px-0.5">
      {children}
    </mark>
  ),
};

type MdNode = {
  type: string;
  value?: string;
  children?: MdNode[];
  data?: { hName?: string };
};

/**
 * A remark plugin that wraps every case-insensitive, literal match of `term`
 * in text (never in code) in a `<mark>`.
 */
function remarkHighlight(term: string) {
  const needle = term.toLowerCase();
  const split = (value: string): MdNode[] => {
    const out: MdNode[] = [];
    const lower = value.toLowerCase();
    let from = 0;
    let at = lower.indexOf(needle);
    while (at !== -1) {
      if (at > from) out.push({ type: 'text', value: value.slice(from, at) });
      const hit = value.slice(at, at + needle.length);
      out.push({
        type: 'highlight',
        data: { hName: 'mark' },
        children: [{ type: 'text', value: hit }],
      });
      from = at + needle.length;
      at = lower.indexOf(needle, from);
    }
    if (from < value.length)
      out.push({ type: 'text', value: value.slice(from) });
    return out;
  };
  const walk = (node: MdNode) => {
    if (!node.children) return;
    node.children = node.children.flatMap((child) => {
      if (child.type === 'text' && child.value) return split(child.value);
      walk(child);
      return [child];
    });
  };
  return () => (tree: MdNode) => walk(tree);
}

/**
 * Markdown as a source view renders it: a wiki page, an open chunk, the edit
 * drawer's preview. The chat answer's headings and tables, lists outside the
 * text, links as `link inline`. `highlight` marks an entity's name (the graph's
 * chunk drawer).
 */
export default function SourceMarkdown({
  content,
  highlight,
}: {
  content: string;
  highlight?: string;
}) {
  const term = highlight?.trim();
  return (
    <div className="text-foreground text-sm leading-relaxed wrap-break-word">
      <ReactMarkdown
        remarkPlugins={term ? [remarkGfm, remarkHighlight(term)] : [remarkGfm]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
