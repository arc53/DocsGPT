import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import actionToastReducer from '../../notifications/actionToastSlice';
import foldersReducer from './foldersSlice';
import { useFolderParam } from './useFolderParam';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;
let navigate: ReturnType<typeof useNavigate>;

function Harness() {
  useFolderParam('agent');
  navigate = useNavigate();
  const location = useLocation();
  return <div data-testid="where">{location.search}</div>;
}

const makeStore = () =>
  configureStore({
    reducer: { folders: foldersReducer, actionToast: actionToastReducer },
    preloadedState: {
      folders: {
        tree: {
          items: [{ id: 'carriers', name: 'Carriers', parent_id: null }],
          loaded: true,
          loading: false,
          failed: false,
          latestRequestId: null,
          removedParents: {},
        },
      },
    },
  });

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

const where = () =>
  container.querySelector('[data-testid="where"]')?.textContent;

describe('useFolderParam', () => {
  it('sends a missing folder back to the root each time it is opened, toasting each visit', async () => {
    const store = makeStore();
    const toasts: unknown[] = [];
    store.subscribe(() => {
      const current = store.getState().actionToast.current;
      if (current && toasts[toasts.length - 1] !== current)
        toasts.push(current);
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={['/agents?folder=gone']}>
            <Harness />
          </MemoryRouter>
        </Provider>,
      );
    });
    expect(where()).toBe('');
    expect(toasts).toHaveLength(1);
    // Back to it in the same mount (history, a stale link).
    await act(async () => navigate('/agents?folder=gone'));
    expect(where()).toBe('');
    expect(toasts).toHaveLength(2);
  });
});
