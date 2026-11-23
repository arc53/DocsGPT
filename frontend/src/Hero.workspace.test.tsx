import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

type Deferred = { resolve: (models: unknown[]) => void };
const calls = vi.hoisted(() => [] as Deferred[]);
vi.mock('./api/services/modelService', () => ({
  default: {
    getModels: vi.fn(
      () =>
        new Promise((resolve) => {
          calls.push({
            resolve: (models) =>
              resolve({
                ok: true,
                json: async () => ({ models, default_model_id: 'gpt' }),
              }),
          });
        }),
    ),
    transformModels: (models: unknown[]) => models,
  },
}));

import { HeroModelSelect } from './Hero';
import preferenceReducer from './preferences/preferenceSlice';
import { setRequestWorkspace } from './workspace/requestWorkspace';
import workspaceReducer, { switchWorkspace } from './workspace/workspaceSlice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const builtin = { id: 'gpt', display_name: 'GPT', source: 'builtin' };
const byom = { id: 'mine', display_name: 'My model', source: 'user' };

describe('HeroModelSelect across a switch', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    calls.length = 0;
    setRequestWorkspace('personal', 0);
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    setRequestWorkspace('personal', 0);
  });

  it("asks again on a switch and drops the old workspace's late answer", async () => {
    const store = configureStore({
      reducer: { preference: preferenceReducer, workspace: workspaceReducer },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <HeroModelSelect />
        </Provider>,
      );
    });
    expect(calls).toHaveLength(1);

    // The switch lands before Personal's list does.
    await act(async () => {
      store.dispatch(switchWorkspace('t1'));
      setRequestWorkspace('t1', 1);
    });
    expect(calls).toHaveLength(2);
    await act(async () => calls[1].resolve([builtin]));
    await act(async () => calls[0].resolve([builtin, byom]));

    expect(
      store.getState().preference.availableModels.map((m) => m.id),
    ).toEqual(['gpt']);
  });
});
