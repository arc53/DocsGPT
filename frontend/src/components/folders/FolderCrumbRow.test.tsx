import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { count?: number }) =>
      options?.count !== undefined ? `${key}:${options.count}` : key,
  }),
}));

import workspaceReducer from '../../workspace/workspaceSlice';
import FolderCrumbRow from './FolderCrumbRow';
import type { Folder } from './types';

const store = configureStore({ reducer: { workspace: workspaceReducer } });

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

const onboarding: Folder = {
  id: 'f1',
  name: 'Carrier onboarding',
  parent_id: null,
  counts: { agent: 2, source: 4, tool: 3, prompt: 6 },
};

const render = async (trail: Folder[], alsoLinks?: boolean) =>
  act(async () =>
    root.render(
      <Provider store={store}>
        <MemoryRouter>
          <FolderCrumbRow
            kind="prompt"
            trail={trail}
            onNavigate={() => undefined}
            alsoLinks={alsoLinks}
          />
        </MemoryRouter>
      </Provider>,
    ),
  );

const alsoRow = () => container.querySelector('[data-slot="folder-also"]');

describe('FolderCrumbRow', () => {
  it('names the root by the kind', async () => {
    await render([onboarding]);
    expect(container.textContent).toContain('folders.root.prompt');
    expect(container.textContent).toContain('Carrier onboarding');
  });

  it('links what else the open folder holds to the other pages', async () => {
    await render([onboarding]);
    expect(alsoRow()?.textContent).toContain('workspace.folders.alsoInFolder');
    const links = Array.from(
      alsoRow()?.querySelectorAll<HTMLAnchorElement>('a') ?? [],
    ).map((a) => [a.getAttribute('href'), a.textContent]);
    expect(links).toEqual([
      ['/agents?folder=f1', 'folders.counts.agent:2'],
      ['/settings/knowledge?folder=f1', 'folders.counts.source:4'],
      ['/settings/tools?folder=f1', 'folders.counts.tool:3'],
    ]);
  });

  it('shows no such row at the root, for a folder of one kind, or when off', async () => {
    await render([]);
    expect(alsoRow()).toBeNull();
    await render([
      { ...onboarding, counts: { agent: 0, source: 0, tool: 0, prompt: 6 } },
    ]);
    expect(alsoRow()).toBeNull();
    await render([onboarding], false);
    expect(alsoRow()).toBeNull();
  });
});
