import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => null,
  useDispatch: () => vi.fn(),
  useStore: () => ({ getState: () => ({}) }),
}));

vi.mock('../api/services/userService', () => ({
  default: {
    getConfig: () => Promise.resolve({ json: () => Promise.resolve({}) }),
  },
}));

import Upload from './Upload';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('Upload source-type tiles', () => {
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

  const render = async () => {
    await act(async () => {
      root.render(
        <Upload
          receivedFile={[]}
          setModalState={vi.fn()}
          isOnboarding={false}
          renderTab={null}
          close={vi.fn()}
        />,
      );
    });
  };

  const tiles = () =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>(
        '[data-slot="option-card"]',
      ),
    );

  it('renders each source type as a button tile', async () => {
    await render();
    const found = tiles();
    expect(found.length).toBeGreaterThan(0);
    for (const tile of found) {
      expect(tile.tagName).toBe('BUTTON');
      expect(tile.getAttribute('type')).toBe('button');
    }
    const crawler = found.find((tile) =>
      tile.textContent?.includes('modals.uploadDoc.ingestors.crawler.label'),
    );
    expect(crawler).toBeDefined();
    expect(crawler!.querySelector('img')?.className).toContain('size-6');
  });

  it('selects the clicked source type', async () => {
    await render();
    const crawler = tiles().find((tile) =>
      tile.textContent?.includes('modals.uploadDoc.ingestors.crawler.label'),
    )!;
    await act(async () => crawler.click());
    expect(tiles()).toHaveLength(0);
    expect(document.body.textContent).toContain(
      'modals.uploadDoc.ingestors.crawler.heading',
    );
  });

  it('leaves the disabled Train button on the default variant', async () => {
    await render();
    const crawler = tiles().find((tile) =>
      tile.textContent?.includes('modals.uploadDoc.ingestors.crawler.label'),
    )!;
    await act(async () => crawler.click());
    const train = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent === 'modals.uploadDoc.train');
    expect(train).toBeDefined();
    expect(train!.disabled).toBe(true);
    expect(train!.className).not.toContain('bg-gray-300');
    expect(train!.className).toContain('bg-primary');
  });
});
