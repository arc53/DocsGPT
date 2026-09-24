import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isTablet: false, isDesktop: true }),
}));

const getAgentFolders = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    getAgentFolders: (...args: unknown[]) => getAgentFolders(...args),
    createAgentFolder: vi.fn(),
    moveAgentToFolder: vi.fn(),
  },
}));

vi.mock('react-redux', () => ({
  useDispatch: () => vi.fn(),
  useSelector: () => 'token',
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import MoveToFolderModal from './MoveToFolderModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const folders = [
  { id: 'f1', name: 'Carriers', parent_id: null },
  { id: 'f2', name: 'Customs', parent_id: null },
  { id: 'f3', name: 'Rotterdam', parent_id: 'f1' },
];

describe('MoveToFolderModal', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getAgentFolders.mockReset();
    getAgentFolders.mockResolvedValue({
      ok: true,
      json: async () => ({ folders }),
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (currentFolderId?: string) => {
    await act(async () => {
      root.render(
        <MoveToFolderModal
          modalState="ACTIVE"
          setModalState={() => undefined}
          agentName="Vendor Due Diligence"
          agentId="a1"
          currentFolderId={currentFolderId}
          onMoveSuccess={() => undefined}
        />,
      );
    });
  };

  const trail = () =>
    document.body.querySelector('nav[aria-label="breadcrumb"]');
  const rowFor = (name: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('[data-slot="button"]'),
    ).find((b) => b.textContent?.includes(name));

  it('shows the root as the current breadcrumb page, not a button', async () => {
    await render();
    const page = trail()?.querySelector('[data-slot="breadcrumb-page"]');
    expect(page?.textContent).toBe('agents.filters.byMe');
    expect(page?.getAttribute('title')).toBe('agents.filters.byMe');
    expect(trail()?.querySelector('button')).toBeNull();
  });

  const items = () =>
    Array.from(
      document.body.querySelectorAll<HTMLElement>('[data-slot="command-item"]'),
    );
  const itemFor = (name: string) =>
    items().find((el) => el.textContent?.includes(name));
  const chevronOf = (name: string) =>
    itemFor(name)?.querySelector<HTMLButtonElement>('[data-slot="button"]');

  it('turns ancestors into breadcrumb link buttons after navigating in', async () => {
    await render();
    await act(async () => chevronOf('Carriers')?.click());

    const page = trail()?.querySelector('[data-slot="breadcrumb-page"]');
    expect(page?.textContent).toBe('Carriers');
    expect(page?.getAttribute('title')).toBe('Carriers');
    const link = trail()?.querySelector<HTMLButtonElement>(
      '[data-slot="breadcrumb-link"]',
    );
    expect(link?.tagName).toBe('BUTTON');
    expect(link?.getAttribute('type')).toBe('button');
    expect(link?.textContent).toBe('agents.filters.byMe');
    expect(itemFor('Rotterdam')).toBeDefined();

    await act(async () => link?.click());
    expect(
      trail()?.querySelector('[data-slot="breadcrumb-page"]')?.textContent,
    ).toBe('agents.filters.byMe');
  });

  it('renders the folder rows as cmdk items in a focusable Command', async () => {
    await render('f2');
    const rows = items();
    expect(rows.map((r) => r.textContent)).toEqual([
      'agents.folders.noFolder',
      'Carriers',
      'Customs',
    ]);
    rows.forEach((r) => {
      expect(r.hasAttribute('cmdk-item')).toBe(true);
      expect(r.getAttribute('role')).toBe('option');
    });
    const cmd = document.body.querySelector('[data-slot="command"]');
    expect(cmd?.getAttribute('tabindex')).toBe('0');
    // No nested role="button" span inside a row any more.
    expect(
      document.body.querySelector('[cmdk-item] [role="button"]'),
    ).toBeNull();
  });

  it('marks the chosen folder with CommandItem checked and aria-checked', async () => {
    await render('f2');
    expect(itemFor('Customs')?.getAttribute('data-checked')).toBe('true');
    expect(itemFor('Customs')?.getAttribute('aria-checked')).toBe('true');
    for (const name of ['Carriers', 'agents.folders.noFolder']) {
      expect(itemFor(name)?.hasAttribute('data-checked')).toBe(false);
      expect(itemFor(name)?.getAttribute('aria-checked')).toBe('false');
      expect(itemFor(name)?.hasAttribute('aria-pressed')).toBe(false);
    }

    await act(async () => itemFor('Carriers')?.click());
    expect(itemFor('Carriers')?.getAttribute('data-checked')).toBe('true');
    expect(itemFor('Carriers')?.getAttribute('aria-checked')).toBe('true');
    expect(itemFor('Customs')?.hasAttribute('data-checked')).toBe(false);

    await act(async () => itemFor('agents.folders.noFolder')?.click());
    expect(
      itemFor('agents.folders.noFolder')?.getAttribute('aria-checked'),
    ).toBe('true');
    expect(itemFor('Carriers')?.getAttribute('aria-checked')).toBe('false');
  });

  it('highlights no row on open, not even "No folder (root)"', async () => {
    await render('f2');
    expect(items().length).toBe(3);
    expect(
      items().filter((r) => r.getAttribute('data-selected') === 'true'),
    ).toHaveLength(0);
  });

  it('keys rows by folder id, so same-named folders highlight separately', async () => {
    getAgentFolders.mockResolvedValue({
      ok: true,
      json: async () => ({
        folders: [
          { id: 'd1', name: 'Archive', parent_id: null },
          { id: 'd2', name: 'Archive', parent_id: null },
        ],
      }),
    });
    await render();
    const [first, second] = items();
    await act(async () => {
      first.dispatchEvent(new PointerEvent('pointermove', { bubbles: true }));
    });
    expect(first.getAttribute('data-selected')).toBe('true');
    expect(second.getAttribute('data-selected')).toBe('false');

    await act(async () => second.click());
    expect(second.getAttribute('data-checked')).toBe('true');
    expect(first.hasAttribute('data-checked')).toBe(false);
  });

  it('drills in from the chevron without changing the chosen folder', async () => {
    await render('f2');
    const chevron = chevronOf('Carriers');
    expect(chevron?.getAttribute('type')).toBe('button');
    expect(chevron?.getAttribute('data-variant')).toBe('ghost-muted');
    expect(chevron?.getAttribute('data-size')).toBe('icon-xs');
    expect(chevron?.getAttribute('aria-label')).toBe(
      'agents.folders.openFolder',
    );
    // The folder icon is decorative; the row's text names it.
    expect(itemFor('Carriers')?.querySelector('img')?.getAttribute('alt')).toBe(
      '',
    );
    expect(chevron?.querySelector('svg')).not.toBeNull();
    // The chevron is the row's last child, and only rows with subfolders get one.
    expect(itemFor('Carriers')?.lastElementChild).toBe(chevron);
    expect(chevronOf('Customs')).toBeNull();

    await act(async () => chevron?.click());
    expect(itemFor('Rotterdam')).toBeDefined();
    expect(itemFor('Rotterdam')?.getAttribute('aria-checked')).toBe('false');

    await act(async () =>
      trail()
        ?.querySelector<HTMLButtonElement>('[data-slot="breadcrumb-link"]')
        ?.click(),
    );
    expect(itemFor('Customs')?.getAttribute('data-checked')).toBe('true');
    expect(itemFor('Carriers')?.hasAttribute('data-checked')).toBe(false);
  });

  it('does not choose the row when Enter is pressed on its chevron', async () => {
    await render('f2');
    const row = itemFor('Carriers')!;
    // Highlight the row, as the pointer does on the way to the chevron, so
    // cmdk's root Enter handler would select it if the key reached it.
    await act(async () => {
      row.dispatchEvent(new PointerEvent('pointermove', { bubbles: true }));
    });
    expect(row.getAttribute('data-selected')).toBe('true');

    await act(async () => {
      chevronOf('Carriers')?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    expect(itemFor('Carriers')?.hasAttribute('data-checked')).toBe(false);
    expect(itemFor('Customs')?.getAttribute('data-checked')).toBe('true');
  });

  it('renders the footer actions as pill buttons', async () => {
    await render();
    const newFolder = rowFor('agents.folders.newFolder');
    expect(newFolder?.getAttribute('data-variant')).toBe('outline-primary');
    // New Folder swaps in place with the 42px new-folder Input, so it is the
    // field height too and the footer row doesn't jump.
    expect(newFolder?.getAttribute('data-size')).toBe('field');
    expect(newFolder?.getAttribute('data-shape')).toBe('pill');
    expect(rowFor('agents.folders.move')?.getAttribute('data-shape')).toBe(
      'pill',
    );
    expect(rowFor('cancel')?.getAttribute('data-shape')).toBe('pill');
  });
});
