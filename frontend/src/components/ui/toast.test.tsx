import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import {
  Toast,
  ToastContent,
  ToastHeader,
  ToastItem,
  ToastMessage,
  ToastStatus,
  ToastTitle,
  ToastViewport,
} from './toast';

describe('Toast', () => {
  it('is a bordered card with the toast shadow', () => {
    const html = renderToStaticMarkup(<Toast>x</Toast>);
    expect(html).toContain('shadow-toast');
    expect(html).toContain('rounded-2xl');
  });

  it('leaves the live region to the viewport', () => {
    const html = renderToStaticMarkup(
      <ToastViewport>
        <Toast>a</Toast>
        <Toast>b</Toast>
      </ToastViewport>,
    );
    // Exactly one live region: the viewport. Cards must not nest another.
    expect(html.match(/role="status"/g)).toHaveLength(1);
    expect(html).toMatch(
      /^<div role="status" aria-live="polite" data-slot="toast-viewport"/,
    );
    expect(renderToStaticMarkup(<Toast>x</Toast>)).not.toContain('role=');
  });

  it('lets a caller override the viewport politeness', () => {
    const html = renderToStaticMarkup(<ToastViewport aria-live="assertive" />);
    expect(html).toContain('aria-live="assertive"');
    expect(html).not.toContain('aria-live="polite"');
  });

  it('truncates the title unless it wraps', () => {
    const truncated = renderToStaticMarkup(<ToastTitle>t</ToastTitle>);
    expect(truncated).toContain('truncate');
    const wrapped = renderToStaticMarkup(<ToastTitle wrap>t</ToastTitle>);
    expect(wrapped).not.toContain('truncate');
    expect(wrapped).not.toContain('wrap=');
  });

  it('sizes the message xs by default and sm on request', () => {
    const xs = renderToStaticMarkup(<ToastMessage>m</ToastMessage>);
    expect(xs).toContain('text-xs');
    expect(xs).not.toContain('text-sm');
    const sm = renderToStaticMarkup(<ToastMessage size="sm">m</ToastMessage>);
    expect(sm).toContain('text-sm');
    expect(sm).toContain('leading-4.5');
    expect(sm).not.toContain('text-xs');
  });

  it('pads a message that is the only content under the header', () => {
    const html = renderToStaticMarkup(<ToastMessage>m</ToastMessage>);
    // pb-3 always; pt-3 only when nothing sits above it in ToastContent.
    expect(html).toContain('pb-3');
    expect(html).toContain('first:pt-3');
  });

  it('keeps a message under its row instead of below a divider', () => {
    const html = renderToStaticMarkup(
      <ToastItem label="1.png">
        <ToastStatus status="destructive" />
      </ToastItem>,
    );
    expect(html).toContain(
      '[&amp;:has(+[data-slot=toast-message])]:border-b-0',
    );
  });

  it('renders an optional icon before the label', () => {
    const html = renderToStaticMarkup(
      <ToastItem label="Conversation" icon={<ToastStatus status="warning" />}>
        <button>Review</button>
      </ToastItem>,
    );
    expect(html.indexOf('data-status="warning"')).toBeLessThan(
      html.indexOf('Conversation'),
    );
    expect(html).not.toContain('icon=');
  });

  it('tints the header by variant and colours the message', () => {
    const html = renderToStaticMarkup(
      <Toast>
        <ToastHeader variant="destructive">
          <ToastTitle>Upload failed</ToastTitle>
        </ToastHeader>
        <ToastContent>
          <ToastItem label="1.png">
            <ToastStatus status="destructive" />
          </ToastItem>
          <ToastMessage variant="destructive">
            No text could be extracted.
          </ToastMessage>
        </ToastContent>
      </Toast>,
    );
    expect(html).toContain('bg-destructive/10');
    expect(html).toContain('data-status="destructive"');
    expect(html).toContain('text-destructive');
    expect(html).toContain('No text could be extracted.');
  });

  it('never uses raw palette colours', () => {
    const html = renderToStaticMarkup(
      <Toast>
        <ToastHeader variant="success">
          <ToastTitle>Done</ToastTitle>
        </ToastHeader>
        <ToastItem label="a.md" meta="1.2k tokens">
          <ToastStatus status="success" />
        </ToastItem>
      </Toast>,
    );
    expect(html).not.toMatch(
      /\b(bg|text)-(red|green|amber|gray|black|white)\b/,
    );
  });
});
