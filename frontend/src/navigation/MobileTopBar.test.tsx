import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
// Both read the store; the bar only decides when they appear.
vi.mock('../components/ProfileButton', () => ({
  default: () => <span data-testid="profile" />,
}));
vi.mock('../modals/ShareConversationModal', () => ({
  ShareConversationModal: ({ conversationId }: { conversationId: string }) => (
    <div data-testid="share-modal">{conversationId}</div>
  ),
}));

import MobileTopBar from './MobileTopBar';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const openMenu = (trigger: Element) =>
  act(() => {
    trigger.dispatchEvent(
      new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
    );
    (trigger as HTMLElement).click();
  });

const menuItem = (label: string) =>
  Array.from(document.querySelectorAll('[role="menuitem"]')).find(
    (el) => el.textContent === label,
  ) as HTMLElement | undefined;

describe('MobileTopBar', () => {
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

  const render = (props: Partial<Parameters<typeof MobileTopBar>[0]>) =>
    act(() => {
      root.render(
        <MemoryRouter>
          <MobileTopBar onOpenSidebar={() => {}} {...props} />
        </MemoryRouter>,
      );
    });

  const button = (label: string) =>
    container.querySelector(
      `button[aria-label="${label}"]`,
    ) as HTMLButtonElement | null;

  it('shows the sidebar toggle, new chat and profile on an empty chat, with no title', () => {
    const onOpenSidebar = vi.fn();
    const onNewChat = vi.fn();
    render({ onOpenSidebar, onNewChat });

    act(() => button('navigation.openSidebar')!.click());
    act(() => button('newChat')!.click());
    expect(onOpenSidebar).toHaveBeenCalledOnce();
    expect(onNewChat).toHaveBeenCalledOnce();
    expect(container.querySelector('[data-testid="profile"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="mobile-title"]')).toBeNull();
  });

  it('shows no title and no new chat in a section (settings, admin)', () => {
    render({});

    expect(container.querySelector('[data-testid="mobile-title"]')).toBeNull();
    expect(button('newChat')).toBeNull();
    expect(button('navigation.openSidebar')).not.toBeNull();
  });

  it('shows a shared agent name as plain text: it has no actions', () => {
    render({ title: 'Support Assistant', agentImage: '', onNewChat: () => {} });

    const title = container.querySelector('[data-testid="mobile-title"]');
    expect(title?.textContent).toBe('Support Assistant');
    expect(title?.tagName).not.toBe('BUTTON');
  });

  it('opens share, rename and delete from the conversation title', () => {
    render({
      title: 'Router drops',
      conversationId: 'c1',
      onNewChat: () => {},
      onRename: () => {},
      onDelete: () => {},
    });

    const title = container.querySelector('[data-testid="mobile-title"]')!;
    expect(title.tagName).toBe('BUTTON');
    expect(title.textContent).toContain('Router drops');
    openMenu(title);
    expect(menuItem('convTile.share')).toBeDefined();
    expect(menuItem('convTile.rename')).toBeDefined();
    expect(menuItem('convTile.delete')).toBeDefined();
    expect(menuItem('navigation.editAgent')).toBeUndefined();

    act(() => menuItem('convTile.share')!.click());
    expect(
      document.querySelector('[data-testid="share-modal"]')?.textContent,
    ).toBe('c1');
  });

  it('renames the conversation in place', () => {
    const onRename = vi.fn();
    render({
      title: 'Router drops',
      conversationId: 'c1',
      onRename,
      onDelete: () => {},
    });

    openMenu(container.querySelector('[data-testid="mobile-title"]')!);
    act(() => menuItem('convTile.rename')!.click());
    const input = container.querySelector('input') as HTMLInputElement;
    expect(input.value).toBe('Router drops');

    act(() => {
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!;
      setValue.call(input, 'TP-Link fix');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    act(() => button('convTile.save')!.click());
    expect(onRename).toHaveBeenCalledWith({ id: 'c1', name: 'TP-Link fix' });
    expect(container.querySelector('input')).toBeNull();
  });

  it('adds Edit agent for an owned agent, even before the chat has a title', () => {
    render({
      title: 'Music score analyst',
      agentImage: '/robot.svg',
      editAgentPath: '/agents/edit/a1',
    });

    const title = container.querySelector('[data-testid="mobile-title"]')!;
    expect(title.querySelector('img')).not.toBeNull();
    openMenu(title);
    expect(menuItem('navigation.editAgent')).toBeDefined();
    expect(menuItem('convTile.share')).toBeUndefined();
  });
});
