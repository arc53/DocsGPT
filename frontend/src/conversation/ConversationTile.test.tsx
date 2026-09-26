import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import ConversationTile from './ConversationTile';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const makeStore = (conversationId: string | null) =>
  configureStore({
    reducer: {
      conversation: () => ({ conversationId }),
      preference: () => ({ token: null }),
    },
  });

describe('ConversationTile', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = (currentId: string | null, select = vi.fn()) => {
    act(() => {
      root.render(
        <Provider store={makeStore(currentId)}>
          <MemoryRouter>
            <ConversationTile
              conversation={{ id: 'c1', name: 'Halvorsen QBR prep' }}
              selectConversation={select}
              onConversationClick={() => undefined}
              onDeleteConversation={() => undefined}
              onSave={() => undefined}
            />
          </MemoryRouter>
        </Provider>,
      );
    });
    return container.querySelector('a') as HTMLAnchorElement;
  };

  it('is a sidebar-item link, marked current on its conversation', () => {
    const link = render('c1');
    expect(link.getAttribute('href')).toBe('/c/c1');
    expect(link.dataset.variant).toBe('sidebar-item');
    expect(link.getAttribute('aria-current')).toBe('page');
    expect(link.querySelector('span')?.className).toContain('truncate');
  });

  it('keeps the actions menu outside the link', () => {
    const link = render('c1');
    const menu = container.querySelector('button[aria-label="convTile.menu"]');
    expect(menu).not.toBeNull();
    expect(link.contains(menu)).toBe(false);
  });

  it('selects another conversation on click', () => {
    const select = vi.fn();
    const link = render('other', select);
    expect(link.hasAttribute('aria-current')).toBe(false);
    act(() => link.click());
    expect(select).toHaveBeenCalledWith('c1');
  });
});
