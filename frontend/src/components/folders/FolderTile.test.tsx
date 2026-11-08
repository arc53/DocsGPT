import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { count?: number }) =>
      options?.count !== undefined ? `${key}:${options.count}` : key,
  }),
}));

import FolderTile from './FolderTile';
import type { Folder } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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

const render = async (
  folder: Folder,
  type: 'agent' | 'source',
  onOpen = vi.fn(),
  parentName?: string,
) => {
  await act(async () =>
    root.render(
      <MemoryRouter>
        <FolderTile
          folder={folder}
          type={type}
          onOpen={onOpen}
          menuOptions={[{ label: 'Rename', onClick: () => undefined }]}
          parentName={parentName}
        />
      </MemoryRouter>,
    ),
  );
  return onOpen;
};

describe('FolderTile', () => {
  it('opens from a stretched button that is the card’s direct child', async () => {
    const folder = {
      id: 'f1',
      name: 'Customer-facing',
      parent_id: null,
      item_count: 2,
    };
    const onOpen = await render(folder, 'agent');
    const card = container.querySelector('[data-folder-tile]') as HTMLElement;
    const open = card.querySelector(':scope > button') as HTMLButtonElement;
    expect(open.textContent).toBe('Customer-facing');
    await act(async () => open.click());
    expect(onOpen).toHaveBeenCalledWith(folder);
    // The count line, and the ⋯ outside the open button.
    expect(card.textContent).toContain('folders.counts.agent:2');
    expect(
      card.querySelector('button[aria-label="folders.menuLabel"]'),
    ).not.toBeNull();
    expect(open.querySelector('button')).toBeNull();
  });

  it('names the agents that read a source folder', async () => {
    await render(
      {
        id: 'f2',
        name: 'Carriers',
        parent_id: null,
        used_by: {
          agents: [{ id: 'a1', name: 'Support', can_edit: true }],
          others: 0,
        },
      },
      'source',
    );
    expect(container.textContent).toContain('folders.counts.empty');
    expect(container.textContent).toContain('settings.usage.agentsShort:1');
  });

  // A search across levels: a nested folder says where it sits first.
  it('names the parent of a folder found by a search', async () => {
    await render(
      { id: 'f3', name: 'Rate archive', parent_id: 'f2', item_count: 4 },
      'source',
      vi.fn(),
      'Carriers',
    );
    const items = Array.from(
      container.querySelectorAll('[data-slot="meta-item"]'),
    ).map((item) => item.textContent);
    expect(items).toEqual(['folders.inParent', 'folders.counts.source:4']);
  });
});
