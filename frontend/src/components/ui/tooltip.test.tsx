import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip';

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

describe('Tooltip timing', () => {
  it('opens after 400ms', async () => {
    const { TOOLTIP_DELAY_MS } = await import('./tooltip');
    expect(TOOLTIP_DELAY_MS).toBe(400);
  });

  it('renders inside an app-level provider without adding its own', async () => {
    const { TooltipProvider } = await import('./tooltip');
    const html = renderToStaticMarkup(
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <button type="button">Copy</button>
          </TooltipTrigger>
          <TooltipContent>Copy</TooltipContent>
        </Tooltip>
      </TooltipProvider>,
    );
    expect(html).toContain('data-slot="tooltip-trigger"');
  });
});
