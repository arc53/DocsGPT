import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const confirm = vi.hoisted(() => ({
  handleSubmit: null as null | (() => void | Promise<unknown>),
}));
vi.mock('../modals/ConfirmationModal', () => ({
  default: ({
    variant,
    handleSubmit,
  }: {
    variant?: string;
    handleSubmit: () => void | Promise<unknown>;
  }) => {
    confirm.handleSubmit = handleSubmit;
    return <div data-testid="delete-confirm" data-variant={variant} />;
  },
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

  const render = (
    currentId: string | null,
    select = vi.fn(),
    onDelete: (id: string) => void | Promise<unknown> = () => undefined,
  ) => {
    act(() => {
      root.render(
        <Provider store={makeStore(currentId)}>
          <MemoryRouter>
            <ConversationTile
              conversation={{ id: 'c1', name: 'Halvorsen QBR prep' }}
              selectConversation={select}
              onConversationClick={() => undefined}
              onDeleteConversation={onDelete}
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

  it('shows the full conversation name on hover of its truncated label', () => {
    const link = render('c1');
    expect(link.querySelector('span.truncate')?.getAttribute('title')).toBe(
      'Halvorsen QBR prep',
    );
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

  it('confirms a delete with the destructive submit', () => {
    render('c1');
    const confirm = container.querySelector<HTMLElement>(
      '[data-testid="delete-confirm"]',
    );
    expect(confirm?.dataset.variant).toBe('destructive');
  });

  // ConfirmationModal stays pending on the promise and keeps a failure open.
  it('hands the delete request promise to the confirm', () => {
    const request = Promise.resolve();
    const onDelete = vi.fn(() => request);
    render('c1', vi.fn(), onDelete);
    expect(confirm.handleSubmit!()).toBe(request);
    expect(onDelete).toHaveBeenCalledWith('c1');
  });
});
