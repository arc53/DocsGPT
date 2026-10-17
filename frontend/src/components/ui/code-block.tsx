import * as React from 'react';

import { cn } from '@/lib/utils';

import CopyButton from '../CopyButton';
import { Card } from './card';

/*
 * The code-block family (DESIGN.md › Code blocks): app output, a value to
 * copy, a labelled panel and a markdown fence. Every copy button in it is the
 * icon-only `CopyButton` at its default `sm` (32px), drawn here, never at the
 * call site.
 */

const MAX_HEIGHT = {
  sm: 'max-h-40',
  md: 'max-h-60',
  lg: 'max-h-80',
} as const;

const TONE = {
  default: 'text-foreground',
  muted: 'text-muted-foreground',
  destructive: 'text-destructive',
} as const;

const WRAP = {
  word: 'wrap-break-word',
  anywhere: 'wrap-anywhere',
} as const;

type CodeBlockProps = {
  /**
   * The box, picked by the surface underneath: `filled` (a muted well) on a
   * card or background, `subtle` on a muted surface, `bare` (no box) inside
   * an Alert or a CodePanel. `pane` is a full-pane file viewer: no box, the
   * pane's p-4, and it scrolls inside the pane's height.
   */
  surface?: 'filled' | 'subtle' | 'bare' | 'pane';
  /**
   * The scroll cap, on an inner div so the scrollbar never runs into the
   * Card's corners: `sm` 160px, `md` 240px, `lg` 320px. `parent` scrolls
   * inside a height the caller sets (`flex-1`, `h-full`, `max-h-full`).
   */
  maxHeight?: keyof typeof MAX_HEIGHT | 'parent';
  /** `anywhere` for URLs and tokens, `word` (default) for prose and commands. */
  wrap?: keyof typeof WRAP;
  tone?: keyof typeof TONE;
  /** `sans` for a recorded query or answer text rather than code. */
  font?: 'mono' | 'sans';
  /** Layout only (margins, flex sizing, a viewer's padding), on the root. */
  className?: string;
  children: React.ReactNode;
};

/** A block of app output: a run's output, an error trace, a JSON payload. */
function CodeBlock({
  surface = 'filled',
  maxHeight,
  wrap = 'word',
  tone = 'default',
  font = 'mono',
  className,
  children,
}: CodeBlockProps) {
  let node: React.ReactNode = (
    <pre
      data-slot="code-block"
      className={cn(
        'text-xs whitespace-pre-wrap',
        font === 'mono' ? 'font-mono' : 'font-sans',
        WRAP[wrap],
        TONE[tone],
      )}
    >
      {children}
    </pre>
  );
  if (surface === 'pane') {
    return (
      <div
        className={cn(
          'scrollbar-overlay h-full min-h-0 overflow-auto p-4',
          className,
        )}
      >
        {node}
      </div>
    );
  }
  const bare = surface === 'bare';
  if (maxHeight) {
    node = (
      <div
        className={cn(
          'scrollbar-overlay',
          maxHeight === 'parent'
            ? 'min-h-0 overflow-auto'
            : `${MAX_HEIGHT[maxHeight]} overflow-y-auto`,
          bare && className,
        )}
      >
        {node}
      </div>
    );
  } else if (bare && className) {
    node = <div className={className}>{node}</div>;
  }
  if (bare) return node;
  return (
    <Card variant={surface} padding="sm" className={className}>
      {node}
    </Card>
  );
}

type CopyFieldProps = {
  /** The text the button copies; no button while it is empty. */
  value: string;
  /** What the row shows instead of `value` (a placeholder while it loads). */
  children?: React.ReactNode;
  wrap?: keyof typeof WRAP;
  /** `display` sets a short code (a pairing code) at 30px, centred. */
  size?: 'default' | 'display';
  /** Lands on the value element. */
  'data-testid'?: string;
  className?: string;
};

/**
 * A value to copy (a URL, a token, a command): a filled Card row with the
 * value and the copy button. The value's `py-2` puts its first line on the
 * button centre, one line or many.
 */
function CopyField({
  value,
  children,
  wrap = 'word',
  size = 'default',
  'data-testid': testId,
  className,
}: CopyFieldProps) {
  const display = size === 'display';
  return (
    <Card
      variant="filled"
      padding="sm"
      className={cn(
        'flex-row gap-2',
        display ? 'items-center' : 'items-start',
        className,
      )}
    >
      <pre
        data-testid={testId}
        className={cn(
          'text-foreground min-w-0 flex-1 font-mono whitespace-pre-wrap select-all',
          WRAP[wrap],
          display ? 'text-center text-3xl tracking-widest' : 'py-2 text-xs',
        )}
      >
        {children ?? value}
      </pre>
      {value && <CopyButton textToCopy={value} />}
    </Card>
  );
}

type CodePanelProps = {
  title: string;
  copyText: string;
  /** Usually a `CodeBlock surface="bare"`. */
  children: React.ReactNode;
};

/**
 * A labelled panel under an answer or in a trace: the `answer-surface` strip
 * with the label and copy button, its body below.
 */
function CodePanel({ title, copyText, children }: CodePanelProps) {
  return (
    <div className="bg-answer-surface overflow-hidden rounded-xl">
      <div className="flex items-center justify-between px-3 py-1.5">
        <span className="text-muted-foreground text-xs font-medium">
          {title}
        </span>
        <CopyButton textToCopy={copyText} />
      </div>
      <div className="px-3 pb-2">{children}</div>
    </div>
  );
}

type CodeFrameProps = {
  /** The language, or `mermaid`. */
  label: React.ReactNode;
  copyText: string;
  /** More header controls, after the copy button. */
  actions?: React.ReactNode;
  /** `answer` in a chat answer (the answer-surface token), `muted` elsewhere. */
  surface?: 'answer' | 'muted';
  children: React.ReactNode;
};

/**
 * The bordered frame of a markdown fence (and a Mermaid diagram): a header
 * with the label, the copy button and any actions, the body below.
 */
function CodeFrame({
  label,
  copyText,
  actions,
  surface = 'answer',
  children,
}: CodeFrameProps) {
  return (
    <div className="group border-border relative overflow-hidden rounded-xl border">
      <div
        className={cn(
          'flex items-center justify-between px-2 py-1',
          surface === 'answer' ? 'bg-answer-surface' : 'bg-muted',
        )}
      >
        <span className="text-foreground text-xs font-medium">{label}</span>
        <div className="flex items-center gap-2">
          <CopyButton textToCopy={copyText} side="bottom" />
          {actions}
        </div>
      </div>
      {children}
    </div>
  );
}

export { CodeBlock, CodeFrame, CodePanel, CopyField };
