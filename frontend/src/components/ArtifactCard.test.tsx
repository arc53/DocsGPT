import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'title' in opts ? `${key}:${String(opts.title)}` : key,
  }),
}));

const downloadMock = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    downloadArtifact: (...args: unknown[]) => downloadMock(...args),
  },
}));
const triggerMock = vi.fn();
vi.mock('./artifactViewUtils', () => ({
  triggerResponseDownload: (...args: unknown[]) => triggerMock(...args),
}));

import type { ArtifactCardItem } from '../conversation/artifactCards';
import { ArtifactCard, ArtifactCardList } from './ArtifactCard';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const item = (overrides: Partial<ArtifactCardItem> = {}): ArtifactCardItem => ({
  id: 'a1',
  title: 'Q3 QBR — Halvorsen Logistics',
  kind: 'page',
  version: 2,
  filename: 'qbr.html',
  toolName: 'artifact_generator',
  downloadable: true,
  ...overrides,
});

const makeStore = () =>
  configureStore({ reducer: { preference: () => ({ token: 't' }) } });

describe('ArtifactCard', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    downloadMock.mockReset();
    triggerMock.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (ui: React.ReactElement) => {
    await act(async () => {
      root.render(<Provider store={makeStore()}>{ui}</Provider>);
    });
  };

  // A clickable card that holds another control: the stretched open button
  // is named by the title alone; the kind line stays outside it.
  it('opens through a stretched button named by the title', async () => {
    const onOpen = vi.fn();
    await render(<ArtifactCard item={item()} onOpen={onOpen} />);
    const open = container.querySelector(
      '[data-artifact-open]',
    ) as HTMLButtonElement;
    expect(open.textContent).toBe('Q3 QBR — Halvorsen Logistics');
    expect(open.className).toContain('after:inset-0');
    expect(container.textContent).toContain(
      'conversation.artifacts.kind.page · conversation.artifacts.version',
    );
    await act(async () => open.click());
    expect(onOpen).toHaveBeenCalledWith(item());
  });

  it('downloads the current version from its own button', async () => {
    downloadMock.mockResolvedValue({ ok: true });
    triggerMock.mockResolvedValue(true);
    await render(<ArtifactCard item={item()} onOpen={() => undefined} />);
    const download = container.querySelector(
      'button[aria-label="conversation.artifacts.download:Q3 QBR — Halvorsen Logistics"]',
    ) as HTMLButtonElement;
    expect(download.className).toContain('z-10');
    await act(async () => download.click());
    // The version the card names, not whatever is current now.
    expect(downloadMock).toHaveBeenCalledWith('a1', 't', 2, 'url');
    expect(triggerMock).toHaveBeenCalledWith({ ok: true }, 'qbr.html');
  });

  it('has no download for a note', async () => {
    await render(
      <ArtifactCard
        item={item({ kind: 'note', downloadable: false, version: undefined })}
        onOpen={() => undefined}
      />,
    );
    expect(container.querySelectorAll('button')).toHaveLength(1);
  });

  // The open row rule: the card whose artifact the panel shows is bg-secondary.
  it('marks the card whose artifact is open', async () => {
    await render(<ArtifactCard item={item()} open onOpen={() => undefined} />);
    const card = container.querySelector(
      '[data-slot="artifact-card"]',
    ) as HTMLElement;
    expect(card.className).toContain('bg-secondary');
    expect(
      container
        .querySelector('[data-artifact-open]')
        ?.getAttribute('aria-current'),
    ).toBe('true');
  });
});

describe('ArtifactCardList', () => {
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

  // Two columns once its own column fits two cards, one below that.
  it('lays the cards out by the width of its column', async () => {
    await act(async () => {
      root.render(
        <Provider store={makeStore()}>
          <ArtifactCardList
            items={[item(), item({ id: 'a2' })]}
            onOpen={() => undefined}
          />
        </Provider>,
      );
    });
    const list = container.querySelector('ul') as HTMLElement;
    expect(list.parentElement?.className).toContain('@container');
    expect(list.parentElement?.parentElement?.className).toContain('w-full');
    expect(list.className).toContain('grid-cols-1');
    expect(list.className).toContain('@min-[33rem]:grid-cols-2');
    expect(list.querySelectorAll('[data-slot="artifact-card"]')).toHaveLength(
      2,
    );
  });

  // An earlier turn's card names an older version of the open artifact.
  it('marks open only the card naming the version the panel shows', async () => {
    await act(async () => {
      root.render(
        <Provider store={makeStore()}>
          <ArtifactCardList
            items={[item({ version: 1 }), item({ id: 'a2' })]}
            open={{ id: 'a1', version: 2 }}
            onOpen={() => undefined}
          />
        </Provider>,
      );
    });
    const cards = container.querySelectorAll('[data-slot="artifact-card"]');
    expect(cards[0].className).not.toContain('bg-secondary');
    expect(cards[1].className).not.toContain('bg-secondary');
  });

  const many = (n: number) =>
    Array.from({ length: n }, (_, i) =>
      item({ id: `a${i}`, title: `File ${i}` }),
    );
  const renderList = async (
    props: Partial<Parameters<typeof ArtifactCardList>[0]>,
  ) => {
    await act(async () => {
      root.render(
        <Provider store={makeStore()}>
          <ArtifactCardList
            items={many(4)}
            onOpen={() => undefined}
            {...props}
          />
        </Provider>,
      );
    });
  };
  const cards = () =>
    Array.from(container.querySelectorAll('[data-slot="artifact-card"]'));

  it('shows up to four artifacts as cards', async () => {
    await renderList({ items: many(4), onShowAll: () => undefined });
    expect(cards().map((c) => c.textContent)).toEqual(
      expect.arrayContaining([expect.stringContaining('File 3')]),
    );
    expect(cards()).toHaveLength(4);
    expect(container.textContent).not.toContain('conversation.artifacts.more');
  });

  // The Sources pattern: past four, three cards and one that opens the list.
  it('folds the rest into a fourth card that opens the full list', async () => {
    const onShowAll = vi.fn();
    await renderList({ items: many(9), onShowAll });
    expect(cards()).toHaveLength(4);
    const more = cards()[3];
    expect(more.textContent).toContain('conversation.artifacts.more');
    expect(container.textContent).not.toContain('File 3');
    await act(async () =>
      (more.querySelector('[data-artifact-open]') as HTMLButtonElement).click(),
    );
    expect(onShowAll).toHaveBeenCalledOnce();
  });

  it('marks the fourth card open while its list shows', async () => {
    await renderList({
      items: many(9),
      onShowAll: () => undefined,
      showAllOpen: true,
    });
    expect(cards()[3].className).toContain('bg-secondary');
  });

  // With nowhere to show a list, nothing is hidden.
  it('shows every card without a list to open', async () => {
    await renderList({ items: many(9) });
    expect(cards()).toHaveLength(9);
  });

  it('renders nothing without items', async () => {
    await act(async () => {
      root.render(
        <Provider store={makeStore()}>
          <ArtifactCardList items={[]} onOpen={() => undefined} />
        </Provider>,
      );
    });
    expect(container.innerHTML).toBe('');
  });
});
