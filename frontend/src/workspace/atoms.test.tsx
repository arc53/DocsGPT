import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts
        ? `${key}(${Object.entries(opts)
            .filter(([k]) => k !== 'interpolation')
            .map(([k, v]) => `${k}=${String(v)}`)
            .join(',')})`
        : key,
  }),
}));

import { prefSlice } from '../preferences/preferenceSlice';
import CreatorMeta, { showsCreator } from './CreatorMeta';
import { splitByOrigin, type ItemOrigin } from './itemOrigin';
import workspaceReducer, {
  loadWorkspaces,
  switchWorkspace,
} from './workspaceSlice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// A JWT whose payload is {"sub":"me"}.
const TOKEN = `x.${btoa(JSON.stringify({ sub: 'me' }))}.y`;

const ROWS = [
  { id: 'personal', kind: 'personal', name: 'Personal' },
  {
    id: 't1',
    kind: 'team',
    name: 'Operations',
    role: 'editor',
    member_count: 12,
  },
];

const makeStore = (current: 'personal' | 't1') => {
  const store = configureStore({
    reducer: { workspace: workspaceReducer, preference: prefSlice.reducer },
  });
  store.dispatch(prefSlice.actions.setToken(TOKEN));
  store.dispatch({
    type: loadWorkspaces.fulfilled.type,
    payload: ROWS,
    meta: { requestId: null, arg: { token: TOKEN } },
  });
  if (current !== 'personal') store.dispatch(switchWorkspace(current));
  return store;
};

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

const render = (store: ReturnType<typeof makeStore>, node: React.ReactNode) =>
  act(() => {
    root.render(<Provider store={store}>{node}</Provider>);
  });

describe('CreatorMeta', () => {
  it('names who added a team item', () => {
    render(
      makeStore('t1'),
      <CreatorMeta
        item={{
          origin: 'team',
          created_by: { user_id: 'dana', label: 'Dana' },
        }}
      />,
    );
    expect(container.textContent).toBe('Dana');
    expect(container.querySelector('[data-slot="meta-item"]')).not.toBeNull();
  });

  it('says You for the reader', () => {
    render(
      makeStore('t1'),
      <CreatorMeta
        item={{ origin: 'team', created_by: { user_id: 'me', label: 'me@x' } }}
      />,
    );
    expect(container.textContent).toBe('workspace.common.you');
  });

  it('names the owner of an item shared with the reader', () => {
    render(
      makeStore('personal'),
      <CreatorMeta
        item={{
          origin: 'shared',
          created_by: { user_id: 'tomas', label: 'tomas@x' },
        }}
      />,
    );
    expect(container.textContent).toBe('tomas@x');
  });

  it("draws nothing on the reader's own item", () => {
    const own = { origin: 'own' as const, created_by: { user_id: 'me' } };
    expect(showsCreator(own)).toBe(false);
    expect(showsCreator({ origin: 'team' })).toBe(false);
    render(makeStore('personal'), <CreatorMeta item={own} />);
    expect(container.innerHTML).toBe('');
  });
});

describe('splitByOrigin', () => {
  it('partitions by origin, never by ownership or type', () => {
    type Row = {
      id: string;
      origin?: ItemOrigin;
      ownership?: string;
      type?: string;
    };
    const rows: Row[] = [
      { id: 'a', origin: 'own', ownership: 'team' },
      { id: 'b', origin: 'team', type: 'private' },
      { id: 'c', origin: 'shared' },
      { id: 'd' },
    ];
    const { own, team, shared } = splitByOrigin(rows);
    expect(own.map((r) => r.id)).toEqual(['a', 'd']);
    expect(team.map((r) => r.id)).toEqual(['b']);
    expect(shared.map((r) => r.id)).toEqual(['c']);
  });

  it("keeps another team's items apart from the team's own", () => {
    const rows: { id: string; origin?: ItemOrigin }[] = [
      { id: 'a', origin: 'team' },
      { id: 'b', origin: 'team_shared' },
    ];
    const { own, team, teamShared } = splitByOrigin(rows);
    expect(own).toEqual([]);
    expect(team.map((r) => r.id)).toEqual(['a']);
    expect(teamShared.map((r) => r.id)).toEqual(['b']);
  });
});
