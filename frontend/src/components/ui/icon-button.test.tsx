import { Copy } from 'lucide-react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { IconButton } from './icon-button';
import { TooltipProvider } from './tooltip';

describe('IconButton', () => {
  it('names the button with its label and hides the icon', () => {
    const html = renderToStaticMarkup(
      <IconButton
        label="Copy"
        icon={Copy}
        variant="ghost-muted"
        size="icon-sm"
      />,
    );
    expect(html).toContain('aria-label="Copy"');
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain('data-slot="tooltip-trigger"');
    expect(html).toContain('size-8');
  });

  it('never sets a native title, even with a hint', () => {
    const html = renderToStaticMarkup(
      <IconButton label="Undo" hint="Undo (Ctrl+Z)" icon={Copy} />,
    );
    expect(html).not.toContain('title=');
    expect(html).toContain('aria-label="Undo"');
  });

  it('defaults to a 36px square icon button', () => {
    const html = renderToStaticMarkup(<IconButton label="Copy" icon={Copy} />);
    expect(html).toContain('size-9');
    expect(html).toContain('type="button"');
  });

  it('renders children in place of the icon', () => {
    const html = renderToStaticMarkup(
      <IconButton label="Send">
        <svg data-testid="custom" />
      </IconButton>,
    );
    expect(html).toContain('data-testid="custom"');
  });

  it('works inside an app-level provider', () => {
    const html = renderToStaticMarkup(
      <TooltipProvider>
        <IconButton label="Copy" icon={Copy} />
      </TooltipProvider>,
    );
    expect(html).toContain('aria-label="Copy"');
  });
});
