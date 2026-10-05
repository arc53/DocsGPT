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

describe('Tooltip wrapping', () => {
  it('fills its box before wrapping instead of balancing the lines', async () => {
    const { act } = await import('react');
    const { createRoot } = await import('react-dom/client');
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () =>
      root.render(
        <Tooltip open>
          <TooltipTrigger asChild>
            <button type="button">Hover</button>
          </TooltipTrigger>
          <TooltipContent>
            A reason long enough to wrap onto a second line of the tooltip
          </TooltipContent>
        </Tooltip>,
      ),
    );
    const content = document.body.querySelector(
      '[data-slot="tooltip-content"]',
    )!;
    // text-balance evens the lines out but leaves the box at max-w-xs, so a
    // two-line tooltip used half its width; pretty fills each line first.
    expect(content.className).toContain('text-pretty');
    expect(content.className).not.toContain('text-balance');
    await act(async () => root.unmount());
    host.remove();
  });
});
