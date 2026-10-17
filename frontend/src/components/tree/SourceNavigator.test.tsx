import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const media = vi.hoisted(() => ({ isDesktop: true }));
vi.mock('../../hooks', () => ({
  useMediaQuery: () => ({
    isMobile: !media.isDesktop,
    isDesktop: media.isDesktop,
  }),
}));

import type { NavigatorNode } from './navigatorUtils';
import SourceNavigator from './SourceNavigator';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const folder = (path: string, children: NavigatorNode[]): NavigatorNode => ({
  id: path,
  kind: 'folder',
  label: path.split('/').pop()!,
  path,
  count: children.length,
  children,
});
const leaf = (path: string): NavigatorNode => ({
  id: path,
  kind: 'leaf',
  label: path.split('/').pop()!,
  path,
});

// Six folders deep, a file at depth 6.
const DEEP: NavigatorNode[] = [
  folder('a', [
    folder('a/b', [
      folder('a/b/c', [
        folder('a/b/c/d', [
          folder('a/b/c/d/e', [
            folder('a/b/c/d/e/f', [leaf('a/b/c/d/e/f/deep.pdf')]),
          ]),
        ]),
      ]),
    ]),
  ]),
];

const TREE: NavigatorNode[] = [
  folder('europe', [
    folder('europe/germany', [
      folder('europe/germany/bremen', [leaf('europe/germany/bremen/a.pdf')]),
      leaf('europe/germany/hamburg.pdf'),
    ]),
  ]),
  folder('rate-cards', [leaf('rate-cards/q1.pdf')]),
];

describe('SourceNavigator', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    media.isDesktop = true;
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async (
    nodes: NavigatorNode[],
    selectedId: string | null,
    onSelect = vi.fn(),
  ) => {
    await act(async () => {
      root.render(
        <SourceNavigator
          nodes={nodes}
          selectedId={selectedId}
          onSelect={onSelect}
          filterLabel="Filter"
          emptyLabel="None"
          title="Files"
        />,
      );
    });
  };

  const row = (label: string) =>
    Array.from(container.querySelectorAll<HTMLElement>('[cmdk-item]')).find(
      (el) => el.textContent?.startsWith(label),
    );

  const indent = (label: string) =>
    row(label)
      ?.querySelector<HTMLElement>('span[aria-hidden]')
      ?.style.getPropertyValue('--indent') ?? '';

  it('steps 24px per level through depth 4, then 12px per level', async () => {
    await render(DEEP, 'a/b/c/d/e/f/deep.pdf');
    expect(row('a')?.querySelector('span[aria-hidden]')).toBeNull();
    expect(indent('b')).toBe('24px');
    expect(indent('c')).toBe('48px');
    expect(indent('d')).toBe('72px');
    expect(indent('e')).toBe('96px');
    expect(indent('f')).toBe('108px');
    expect(indent('deep.pdf')).toBe('120px');
  });

  it('titles folder rows with their full path, like files', async () => {
    await render(DEEP, 'a/b/c/d/e/f/deep.pdf');
    expect(row('f')?.getAttribute('title')).toBe('a/b/c/d/e/f');
    expect(row('deep.pdf')?.getAttribute('title')).toBe('a/b/c/d/e/f/deep.pdf');
  });

  it('expands a folder opened elsewhere (a crumb, a table row), keeping other open folders', async () => {
    await render(TREE, 'rate-cards/q1.pdf');
    expect(row('rate-cards')?.getAttribute('aria-expanded')).toBe('true');
    expect(row('germany')).toBeUndefined();

    await render(TREE, 'europe/germany');
    expect(row('europe')?.getAttribute('aria-expanded')).toBe('true');
    expect(row('germany')?.getAttribute('aria-expanded')).toBe('true');
    expect(row('bremen')).toBeDefined();
    expect(row('hamburg.pdf')).toBeDefined();
    // Rate cards, opened before, stays open.
    expect(row('q1.pdf')).toBeDefined();
  });

  it('expands a folder that is open on the first render', async () => {
    await render(TREE, 'europe/germany');
    expect(row('germany')?.getAttribute('aria-expanded')).toBe('true');
    expect(row('bremen')).toBeDefined();
  });

  it('clicking the open folder still collapses it', async () => {
    const onSelect = vi.fn();
    await render(TREE, 'europe/germany', onSelect);
    await act(async () => row('germany')!.click());
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'europe/germany' }),
    );
    expect(row('germany')?.getAttribute('aria-expanded')).toBe('false');
    expect(row('bremen')).toBeUndefined();
  });

  // The column caps its list; the phone sheet's body already scrolls, so a
  // cap there would nest a second scroller inside it.
  it('caps the list in the column but not in the phone sheet', async () => {
    await render(TREE, null);
    const columnList = document.body.querySelector(
      '[data-slot="command-list"]',
    )!;
    expect(columnList.className).toContain('max-h-[70svh]');

    await act(async () => root.unmount());
    root = createRoot(container);
    media.isDesktop = false;
    await render(TREE, null);
    const trigger = container.querySelector(
      'button[aria-haspopup="dialog"]',
    ) as HTMLButtonElement;
    await act(async () => trigger.click());
    const sheetList = document.body.querySelector(
      '[data-slot="command-list"]',
    )!;
    expect(sheetList).not.toBeNull();
    expect(sheetList.className).not.toContain('max-h-[70svh]');
    expect(sheetList.className).toContain('max-h-none');
  });
});
