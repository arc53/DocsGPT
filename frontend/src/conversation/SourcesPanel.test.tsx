import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'count' in opts ? `${key}:${opts.count}` : key,
  }),
}));

vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

import { SidePanel } from '../components/ui/side-panel';
import SourcesPanel from './SourcesPanel';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('SourcesPanel', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const sources = [
    { title: 'Guide', text: 'Guide text', link: 'https://example.com/guide' },
    {
      title: 'Notes',
      text: 'Notes text',
      link: 'local',
      connector_key: 'google_drive',
      connector_name: 'Google Drive',
    },
  ];

  const render = async () => {
    await act(async () => {
      root.render(
        <SidePanel variant="docked" open onOpenChange={vi.fn()}>
          <SourcesPanel sources={sources} />
        </SidePanel>,
      );
    });
  };

  it('heads the panel with the title and the count for this answer', async () => {
    await render();
    const header = container.querySelector('[data-slot="panel-header"]')!;
    expect(header.querySelector('h2')?.textContent).toBe(
      'conversation.sources.title',
    );
    expect(header.textContent).toContain('conversation.sources.forAnswer:2');
  });

  it('lists each source as a filled tile, an external one as a new-tab link', async () => {
    await render();
    const tiles = Array.from(
      container.querySelectorAll<HTMLElement>(
        '[data-slot="panel-body"] [data-slot="card"]',
      ),
    );
    expect(tiles).toHaveLength(2);
    expect(tiles.map((tile) => tile.dataset.variant)).toEqual([
      'filled',
      'filled',
    ]);
    const [external, local] = tiles;
    expect(external.tagName).toBe('A');
    expect(external.getAttribute('href')).toBe('https://example.com/guide');
    expect(external.getAttribute('target')).toBe('_blank');
    expect(external.getAttribute('rel')).toBe('noopener noreferrer');
    expect(external.textContent).toContain('1. Guide');
    expect(local.tagName).toBe('DIV');
    expect(local.textContent).toContain('2. Notes');
    expect(local.textContent).toContain('conversation.sources.fromConnector');
  });
});
