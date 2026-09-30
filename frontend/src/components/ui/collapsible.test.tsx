import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Collapsible } from './collapsible';

const parse = (html: string) => {
  const host = document.createElement('div');
  host.innerHTML = html;
  return host.firstElementChild as HTMLElement;
};

describe('Collapsible', () => {
  it('opens to its content height with the collapsible transition', () => {
    const root = parse(
      renderToStaticMarkup(
        <Collapsible open id="audit" className="mt-2">
          <p>Body</p>
        </Collapsible>,
      ),
    );
    expect(root.dataset.slot).toBe('collapsible');
    expect(root.dataset.state).toBe('open');
    expect(root.id).toBe('audit');
    const classes = root.className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining([
        'grid',
        'transition-[grid-template-rows,opacity]',
        'duration-300',
        'ease-out',
        'motion-reduce:transition-none',
        'grid-rows-[1fr]',
        'opacity-100',
        'mt-2',
      ]),
    );
    const inner = root.firstElementChild as HTMLElement;
    // Open from the start: nothing moves, so nothing is clipped.
    expect(inner.className.split(' ')).toEqual(
      expect.arrayContaining(['min-h-0', 'min-w-0']),
    );
    expect(inner.className).not.toContain('overflow-hidden');
    expect(inner.textContent).toBe('Body');
  });

  it('collapses to zero rows and fades out when closed, keeping the content mounted', () => {
    const root = parse(
      renderToStaticMarkup(
        <Collapsible open={false}>
          <p>Body</p>
        </Collapsible>,
      ),
    );
    expect(root.dataset.state).toBe('closed');
    const classes = root.className.split(' ');
    expect(classes).toContain('grid-rows-[0fr]');
    expect(classes).toContain('opacity-0');
    expect(classes).not.toContain('grid-rows-[1fr]');
    expect((root.firstElementChild as HTMLElement).className).toContain(
      'overflow-hidden',
    );
    expect(root.textContent).toBe('Body');
  });

  it('makes closed content inert, so hidden fields leave the tab order', () => {
    const closed = parse(
      renderToStaticMarkup(
        <Collapsible open={false}>
          <input aria-label="Name" />
        </Collapsible>,
      ),
    );
    expect(closed.hasAttribute('inert')).toBe(true);
    const open = parse(
      renderToStaticMarkup(
        <Collapsible open>
          <input aria-label="Name" />
        </Collapsible>,
      ),
    );
    expect(open.hasAttribute('inert')).toBe(false);
  });
});
