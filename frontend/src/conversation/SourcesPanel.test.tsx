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

// The reader is covered on its own; here it only has to be the second level.
vi.mock('./CitationReader', () => ({
  default: ({ number, onBack }: { number: number; onBack: () => void }) => (
    <button type="button" data-testid="reader" onClick={onBack}>
      {`reader ${number}`}
    </button>
  ),
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
    { title: 'Guide', text: 'Guide text', source: 'https://example.com/guide' },
    {
      title: 'Notes',
      text: 'Notes text',
      source: 'notes.md',
      connector_key: 'google_drive',
      connector_name: 'Google Drive',
    },
  ];

  const render = async (
    openIndex: number | null = null,
    onOpenIndexChange = vi.fn(),
  ) => {
    await act(async () => {
      root.render(
        <SidePanel variant="docked" open onOpenChange={vi.fn()}>
          <SourcesPanel
            sources={sources}
            openIndex={openIndex}
            onOpenIndexChange={onOpenIndexChange}
          />
        </SidePanel>,
      );
    });
    return onOpenIndexChange;
  };

  it('heads the panel with the title and the count for this answer', async () => {
    await render();
    const header = container.querySelector('[data-slot="panel-header"]')!;
    expect(header.querySelector('h2')?.textContent).toBe(
      'conversation.sources.title',
    );
    expect(header.textContent).toContain('conversation.sources.forAnswer:2');
  });

  it('lists each source as a filled tile that opens its reader', async () => {
    const onOpenIndexChange = await render();
    const tiles = Array.from(
      container.querySelectorAll<HTMLElement>(
        '[data-slot="panel-body"] [data-slot="card"]',
      ),
    );
    expect(tiles.map((tile) => tile.dataset.variant)).toEqual([
      'filled',
      'filled',
    ]);
    // A native button, so the web link waits in the reader instead of
    // nesting inside a clickable card.
    expect(tiles.map((tile) => tile.tagName)).toEqual(['BUTTON', 'BUTTON']);
    expect(container.querySelector('[data-slot="panel-body"] a')).toBeNull();
    expect(tiles[0].textContent).toContain('1. Guide');
    expect(tiles[1].textContent).toContain('2. Notes');
    expect(tiles[1].textContent).toContain(
      'conversation.sources.fromConnector',
    );

    await act(async () => tiles[1].click());
    expect(onOpenIndexChange).toHaveBeenCalledWith(1);
  });

  it('shows the open source as the second level, and Back returns to the list', async () => {
    const onOpenIndexChange = await render(0);
    const reader = container.querySelector<HTMLElement>(
      '[data-testid="reader"]',
    );
    expect(reader?.textContent).toBe('reader 1');
    expect(container.querySelector('[data-slot="card"]')).toBeNull();

    await act(async () => reader!.click());
    expect(onOpenIndexChange).toHaveBeenCalledWith(null);
  });

  it('shows the list for an index past the sources', async () => {
    await render(5);
    expect(container.querySelector('[data-testid="reader"]')).toBeNull();
    expect(container.querySelectorAll('[data-slot="card"]')).toHaveLength(2);
  });

  it('marks a withheld source and never shows its placeholder text', async () => {
    await act(async () => {
      root.render(
        <SidePanel variant="docked" open onOpenChange={vi.fn()}>
          <SourcesPanel
            sources={[
              {
                title: 'Planted.md',
                text: '[Withheld by a content policy.]...',
                withheld: 'policy',
                relevance: 0.9,
              },
              sources[0],
            ]}
            onOpenIndexChange={vi.fn()}
          />
        </SidePanel>,
      );
    });
    const tiles = Array.from(
      container.querySelectorAll<HTMLElement>(
        '[data-slot="panel-body"] [data-slot="card"]',
      ),
    );
    const badge = tiles[0].querySelector<HTMLElement>('[data-slot="badge"]')!;
    expect(badge.textContent).toBe('conversation.sources.withheld');
    expect(badge.dataset.variant).toBe('warning');
    expect(tiles[0].textContent).toContain('conversation.sources.withheldNote');
    expect(tiles[0].textContent).not.toContain('Withheld by a content policy');
    // Its relevance no longer matters: it was left out.
    expect(tiles[0].textContent).not.toContain(
      'conversation.sources.relevance',
    );
    expect(tiles[1].querySelector('[data-slot="badge"]')).toBeNull();
  });

  it('labels a scored source by its relevance band, and others not at all', async () => {
    await act(async () => {
      root.render(
        <SidePanel variant="docked" open onOpenChange={vi.fn()}>
          <SourcesPanel
            sources={[
              { ...sources[0], relevance: 0.82 },
              { ...sources[1], relevance: 0.12 },
              { title: 'Plain', text: 'No score' },
            ]}
            onOpenIndexChange={vi.fn()}
          />
        </SidePanel>,
      );
    });
    const tiles = Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="card"]'),
    );
    expect(tiles[0].textContent).toContain(
      'conversation.sources.relevance.strong',
    );
    expect(tiles[1].textContent).toContain(
      'conversation.sources.relevance.weak',
    );
    expect(tiles[2].textContent).not.toContain(
      'conversation.sources.relevance',
    );
    const label = [...tiles[0].querySelectorAll('span')].find(
      (span) => span.textContent === 'conversation.sources.relevance.strong',
    );
    expect(label?.getAttribute('title')).toBe(
      'conversation.sources.relevance.tooltip',
    );
  });
});
