import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const confirm = vi.hoisted(() => ({
  props: null as null | { handleSubmit: () => void | Promise<unknown> },
}));
vi.mock('../modals/ConfirmationModal', () => ({
  default: (props: { handleSubmit: () => void | Promise<unknown> }) => {
    confirm.props = props;
    return null;
  },
}));
vi.mock('../modals/FolderManagementModal', () => ({ default: () => null }));

import FolderCard from './FolderCard';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('FolderCard', () => {
  let container: HTMLDivElement;
  let root: Root;
  const onToggleExpand = vi.fn();
  const onDelete = vi.fn(async (_id: string) => true);

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => {
      root.render(
        <FolderCard
          folder={{ id: 'f1', name: 'Carrier ops' } as never}
          agentCount={3}
          onDelete={onDelete}
          onRename={() => undefined}
          onToggleExpand={onToggleExpand}
        />,
      );
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    onToggleExpand.mockReset();
    onDelete.mockReset();
  });

  const card = () =>
    container.querySelector<HTMLElement>('[data-slot="card"]')!;
  const target = () =>
    card().querySelector<HTMLButtonElement>(':scope > button');
  const menu = () =>
    container.querySelector<HTMLButtonElement>(
      'button[aria-label="agents.folders.menuAriaLabel"]',
    )!;

  // DESIGN "A clickable card that holds a link": a stretched button is the
  // target and the menu is its sibling, never nested inside it.
  it('opens through a stretched button, not a role="button" card', () => {
    expect(container.querySelector('[role="button"]')).toBeNull();
    expect(card().dataset.interactive).toBe('within');
    const button = target();
    expect(button).not.toBeNull();
    expect(button!.type).toBe('button');
    expect(button!.className).toContain('after:absolute');
    expect(button!.className).toContain('after:inset-0');
    expect(button!.textContent).toContain('Carrier ops');
    act(() => button!.click());
    expect(onToggleExpand).toHaveBeenCalledWith('f1');
  });

  it('keeps the menu out of the target and above it', () => {
    expect(target()!.contains(menu())).toBe(false);
    // Not a direct child, so the card's ring follows the target only.
    expect(menu().parentElement).not.toBe(card());
    expect(menu().parentElement!.className).toContain('z-10');
    act(() => menu().click());
    expect(onToggleExpand).not.toHaveBeenCalled();
  });

  it('titles the truncated name', () => {
    const title = container.querySelector('[data-slot="card-title"]');
    expect(title?.getAttribute('title')).toBe('Carrier ops');
  });

  // ConfirmationModal stays pending on the returned promise and keeps a
  // failure open, so the delete hands it the request.
  it('returns the delete promise and rejects when it fails', async () => {
    onDelete.mockResolvedValueOnce(true);
    await expect(confirm.props!.handleSubmit()).resolves.toBeUndefined();
    expect(onDelete).toHaveBeenCalledWith('f1');
    onDelete.mockResolvedValueOnce(false);
    await expect(confirm.props!.handleSubmit()).rejects.toThrow();
  });
});
