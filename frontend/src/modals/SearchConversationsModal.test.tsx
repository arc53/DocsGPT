import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const media = { isMobile: false, isDesktop: true };
vi.mock('../hooks', () => ({
  useMediaQuery: () => media,
}));

const searchConversations = vi.fn();
vi.mock('../preferences/preferenceApi', () => ({
  searchConversations: (...args: unknown[]) => searchConversations(...args),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import SearchConversationsModal from './SearchConversationsModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const conversations = [
  { id: 'c1', name: 'Fuel surcharge policy summary' },
  { id: 'c2', name: 'Q3 carrier rate negotiation' },
];

const serverResults = [
  {
    id: 'r1',
    name: 'Q3 carrier rate negotiation',
    match_field: 'response' as const,
    match_snippet: 'Halvorsen agreed to cap the fuel surcharge at 18%.',
  },
  {
    id: 'r2',
    name: 'Customs hold on Rotterdam shipment',
    match_field: 'prompt' as const,
    match_snippet: 'The broker added a demurrage surcharge.',
  },
];

describe('SearchConversationsModal', () => {
  let container: HTMLDivElement;
  let root: Root;
  let close: ReturnType<typeof vi.fn<() => void>>;
  let onSelect: ReturnType<typeof vi.fn<(id: string) => void>>;

  beforeEach(() => {
    vi.useFakeTimers();
    media.isMobile = false;
    media.isDesktop = true;
    searchConversations.mockReset();
    searchConversations.mockResolvedValue({ data: serverResults });
    close = vi.fn<() => void>();
    onSelect = vi.fn<(id: string) => void>();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  const render = async () => {
    await act(async () => {
      root.render(
        <SearchConversationsModal
          close={close}
          conversations={conversations}
          token="tok"
          onSelectConversation={onSelect}
        />,
      );
    });
  };

  const input = () =>
    document.body.querySelector<HTMLInputElement>(
      '[data-slot="command-input"]',
    )!;

  const items = () =>
    Array.from(
      document.body.querySelectorAll<HTMLElement>('[data-slot="command-item"]'),
    );

  const type = async (value: string) => {
    await act(async () => {
      const el = input();
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!;
      setter.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    await act(async () => {
      await Promise.resolve();
    });
  };

  const key = async (k: string) => {
    await act(async () => {
      input().dispatchEvent(
        new KeyboardEvent('keydown', { key: k, bubbles: true }),
      );
    });
  };

  it('renders a CommandDialog without a close button at desktop width', async () => {
    await render();
    const content = document.body.querySelector('[data-slot="dialog-content"]');
    expect(content).not.toBeNull();
    expect(content!.querySelector('[data-slot="command"]')).not.toBeNull();
    expect(document.body.querySelector('[data-slot="modal-content"]')).toBe(
      null,
    );
    expect(document.body.querySelector('[data-slot="dialog-close"]')).toBe(
      null,
    );
    expect(items().map((i) => i.textContent)).toEqual([
      'Fuel surcharge policy summary',
      'Q3 carrier rate negotiation',
    ]);
  });

  it('shows server results as returned, with snippets on desktop', async () => {
    await render();
    await type('surcharge');
    expect(searchConversations).toHaveBeenCalledWith('surcharge', 'tok');
    const rows = items();
    // r2's title does not contain the query: cmdk must not filter it out.
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain('Q3 carrier rate negotiation');
    expect(rows[0].textContent).toContain('Halvorsen agreed');
    expect(rows[1].textContent).toContain('demurrage');
    expect(rows[0].querySelector('mark')?.textContent).toBe('surcharge');
    expect(rows[0].getAttribute('role')).toBe('option');
  });

  it('opens the highlighted conversation on Enter and follows arrow keys', async () => {
    await render();
    await type('surcharge');
    expect(items()[0].getAttribute('data-selected')).toBe('true');
    await key('ArrowDown');
    expect(items()[1].getAttribute('data-selected')).toBe('true');
    await key('Enter');
    expect(onSelect).toHaveBeenCalledWith('r2');
    expect(close).toHaveBeenCalled();
  });

  it('opens a conversation on click', async () => {
    await render();
    await act(async () => {
      items()[1].click();
    });
    expect(onSelect).toHaveBeenCalledWith('c2');
    expect(close).toHaveBeenCalled();
  });

  it('shows the empty state when the search returns nothing', async () => {
    searchConversations.mockResolvedValue({ data: [] });
    await render();
    await type('zzz');
    expect(items()).toHaveLength(0);
    expect(document.body.textContent).toContain(
      'modals.searchConversations.noResults',
    );
  });

  it('renders a bottom sheet with title-only rows on phones', async () => {
    media.isMobile = true;
    media.isDesktop = false;
    await render();
    const sheet = document.body.querySelector('[data-slot="modal-content"]');
    expect(sheet).not.toBeNull();
    expect(sheet!.hasAttribute('data-mobile-sheet')).toBe(true);
    expect(sheet!.querySelector('[data-slot="command"]')).not.toBeNull();
    expect(document.body.querySelector('[data-slot="dialog-content"]')).toBe(
      null,
    );
    await type('surcharge');
    const rows = items();
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toBe('Q3 carrier rate negotiation');
    expect(rows[1].textContent).toBe('Customs hold on Rotterdam shipment');
    await key('Enter');
    expect(onSelect).toHaveBeenCalledWith('r1');
  });
});
