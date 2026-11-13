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

describe('Tooltip on focus', () => {
  async function focusTrigger(visible: boolean) {
    const { act } = await import('react');
    const { createRoot } = await import('react-dom/client');
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () =>
      root.render(
        <Tooltip>
          <TooltipTrigger asChild>
            <button type="button">Resume</button>
          </TooltipTrigger>
          <TooltipContent>Resume drafting</TooltipContent>
        </Tooltip>,
      ),
    );
    const button = host.querySelector('button')!;
    const matches = button.matches.bind(button);
    Object.defineProperty(button, 'matches', {
      value: (selector: string) =>
        selector === ':focus-visible' ? visible : matches(selector),
    });
    await act(async () => button.focus());
    const state = button.getAttribute('data-state');
    await act(async () => root.unmount());
    host.remove();
    return state;
  }

  it('opens when the keyboard brings focus to its trigger', async () => {
    expect(await focusTrigger(true)).not.toBe('closed');
  });

  it('stays closed when focus returns to its trigger after a tap or click', async () => {
    // A sheet closing on a phone hands focus back to the button that opened it.
    expect(await focusTrigger(false)).toBe('closed');
  });

  // A trigger that wraps the focusable control (a switch or radio, whose own
  // data-state the trigger would overwrite): focus lands on the child, and
  // the wrapper never matches :focus-visible itself.
  async function focusWrappedChild(visible: boolean) {
    const { act } = await import('react');
    const { createRoot } = await import('react-dom/client');
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () =>
      root.render(
        <Tooltip>
          <TooltipTrigger asChild>
            <span>
              <button type="button">Use in my chats</button>
            </span>
          </TooltipTrigger>
          <TooltipContent>In chats: on</TooltipContent>
        </Tooltip>,
      ),
    );
    const wrapper = host.querySelector('[data-slot="tooltip-trigger"]')!;
    const button = host.querySelector('button')!;
    const matches = button.matches.bind(button);
    Object.defineProperty(button, 'matches', {
      value: (selector: string) =>
        selector === ':focus-visible' ? visible : matches(selector),
    });
    await act(async () => button.focus());
    const state = wrapper.getAttribute('data-state');
    await act(async () => root.unmount());
    host.remove();
    return state;
  }

  it('opens when the keyboard focuses a control its trigger wraps', async () => {
    expect(await focusWrappedChild(true)).not.toBe('closed');
  });

  it('stays closed when focus returns to a wrapped control after a tap', async () => {
    expect(await focusWrappedChild(false)).toBe('closed');
  });
});
