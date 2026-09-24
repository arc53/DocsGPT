import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Progress } from './progress';
import { Skeleton } from './skeleton';
import { Spinner } from './spinner';
import { Textarea, textareaVariants } from './textarea';
import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip';

describe('Textarea', () => {
  it('shares the Input field styling and resizes vertically by default', () => {
    const classes = textareaVariants();
    expect(classes).toContain('border-border');
    expect(classes).toContain('focus-visible:ring-3');
    expect(classes).toContain('resize-y');
    expect(classes).toContain('min-h-16');
  });

  it('renders size and resize as data attributes and classes', () => {
    const html = renderToStaticMarkup(<Textarea size="lg" resize="none" />);
    expect(html).toContain('data-size="lg"');
    expect(html).toContain('resize-none');
    expect(html).toContain('rounded-2xl');
  });
});

describe('Spinner', () => {
  it('is an accessible status element drawn by the ring utility', () => {
    const html = renderToStaticMarkup(<Spinner size="sm" />);
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-label="Loading"');
    expect(html).toContain('spinner-ring');
    expect(html).toContain('size-5');
    expect(html).toContain('data-size="sm"');
  });
});

describe('Skeleton', () => {
  it('is a pulsing muted block hidden from assistive tech', () => {
    const html = renderToStaticMarkup(<Skeleton className="h-4 w-32" />);
    expect(html).toContain('animate-pulse');
    expect(html).toContain('bg-muted');
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain('w-32');
  });
});

describe('Progress', () => {
  it('clamps the value and exposes it as a custom property', () => {
    const html = renderToStaticMarkup(
      <Progress value={140} variant="warning" />,
    );
    expect(html).toContain('--progress:100%');
    expect(html).toContain('bg-warning');
    expect(html).toContain('aria-valuenow="100"');
  });

  it('never uses raw palette colours', () => {
    for (const variant of [
      'default',
      'success',
      'warning',
      'destructive',
      'info',
    ] as const) {
      expect(
        renderToStaticMarkup(<Progress value={50} variant={variant} />),
      ).not.toMatch(
        /\b(bg|text)-(red|green|amber|yellow|blue|gray|purple)-\d+/,
      );
    }
  });
});

describe('Tooltip', () => {
  it('renders its trigger without needing an app-level provider', () => {
    const html = renderToStaticMarkup(
      <Tooltip>
        <TooltipTrigger asChild>
          <button type="button">Delete</button>
        </TooltipTrigger>
        <TooltipContent>Delete this source</TooltipContent>
      </Tooltip>,
    );
    expect(html).toContain('data-slot="tooltip-trigger"');
    expect(html).toContain('Delete');
  });
});
