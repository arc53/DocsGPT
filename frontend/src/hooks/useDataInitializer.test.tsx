import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

const getConversations = vi.hoisted(() => vi.fn());
vi.mock('../preferences/preferenceApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../preferences/preferenceApi')>()),
  getConversations: (...args: unknown[]) => getConversations(...args),
  getDocs: async () => [],
}));
vi.mock('../api/services/userService', () => ({
  default: { getConfig: async () => ({ json: async () => ({}) }) },
}));
// The workspace list never answers: the test switches by hand.
vi.mock('../api/services/workspacesService', () => ({
  default: { list: () => new Promise(() => undefined) },
}));
vi.mock('../preferences/chatPrompt', () => ({
  initChatPrompt: () => async () => undefined,
}));
vi.mock('../utils/providerUtils', () => ({
  claimLegacySessionTokens: () => undefined,
}));
vi.mock('../connectors/connectorsSlice', () => ({
  loadConnectors: () => ({ type: 'test/noop' }),
  selectConnectorsEnabled: () => false,
  setConnectorsEnabled: () => ({ type: 'test/noop' }),
}));

import { prefSlice } from '../preferences/preferenceSlice';
import { setRequestWorkspace } from '../workspace/requestWorkspace';
import { workspaceListenerMiddleware } from '../workspace/workspaceListener';
import workspaceReducer, { switchWorkspace } from '../workspace/workspaceSlice';
import useDataInitializer from './useDataInitializer';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

const makeStore = () =>
  configureStore({
    reducer: { preference: prefSlice.reducer, workspace: workspaceReducer },
    middleware: (getDefault) =>
      getDefault({ serializableCheck: false }).prepend(
        workspaceListenerMiddleware.middleware,
      ),
  });

function Init() {
  useDataInitializer(false, 'none');
  return null;
}

const chat = (id: string) => ({ id, name: id, date: '2026-11-16' });

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  getConversations.mockReset();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  setRequestWorkspace('personal', 0);
  localStorage.clear();
});

describe('the sidebar chat list across a switch', () => {
  it('loads the new workspace when the switch comes before the first answer', async () => {
    let answerPersonal: (value: unknown) => void = () => undefined;
    getConversations
      .mockReturnValueOnce(new Promise((resolve) => (answerPersonal = resolve)))
      .mockResolvedValueOnce({ data: [chat('team-chat')], loading: false });
    const store = makeStore();
    await act(async () =>
      root.render(
        <Provider store={store}>
          <Init />
        </Provider>,
      ),
    );
    expect(getConversations).toHaveBeenCalledTimes(1);

    await act(async () => {
      store.dispatch(switchWorkspace('t1'));
    });
    await act(async () => {
      answerPersonal({ data: [chat('personal-chat')], loading: false });
    });

    expect(getConversations).toHaveBeenCalledTimes(2);
    expect(
      store.getState().preference.conversations.data?.map((c) => c.id),
    ).toEqual(['team-chat']);
  });
});
