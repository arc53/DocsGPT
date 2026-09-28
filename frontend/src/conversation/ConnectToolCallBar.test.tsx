import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { name?: string }) =>
      opts?.name ? `${key}:${opts.name}` : key,
  }),
}));

vi.mock('../api/services/connectorsService', () => ({
  default: {
    getCatalog: vi.fn().mockResolvedValue({ success: true, connectors: [] }),
    listConnections: vi
      .fn()
      .mockResolvedValue({ success: true, connections: [] }),
  },
}));

import connectorsReducer from '../connectors/connectorsSlice';
import ConnectToolCallBar from './ConnectToolCallBar';
import type { ToolCallsType } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const call = (status: string): ToolCallsType => ({
  tool_name: 'mcp_tool',
  action_name: 'search_pages',
  call_id: 'call-1',
  arguments: {},
  status: 'awaiting_approval',
  connection_required: {
    connector_key: 'mcp:notion',
    connector_name: 'Notion',
    status,
  },
});

describe('ConnectToolCallBar', () => {
  let root: Root;
  let container: HTMLDivElement;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (toolCall: ToolCallsType, onToolAction = vi.fn()) => {
    const store = configureStore({
      reducer: {
        connectors: connectorsReducer,
        preference: (state = { token: null }) => state,
      },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={['/c/1']}>
            <Routes>
              <Route
                path="/c/1"
                element={
                  <ConnectToolCallBar
                    toolCall={toolCall}
                    onToolAction={onToolAction}
                  />
                }
              />
              <Route path="/settings/connectors" element={<div>DRAWER</div>} />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
    return onToolAction;
  };

  const button = (text: string) =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === text,
    )!;

  it('names the service it needs', async () => {
    await render(call('missing'));
    expect(container.textContent).toContain(
      'conversation.toolApproval.connectTitle:Notion',
    );
    expect(button('conversation.toolApproval.connect:Notion')).toBeDefined();
  });

  it('skipping denies the pending call', async () => {
    const onToolAction = await render(call('missing'));
    await act(async () => button('conversation.toolApproval.skip').click());
    expect(onToolAction).toHaveBeenCalledWith('call-1', 'denied');
  });

  it('an account that needs signing in again is healed from its drawer', async () => {
    await render(call('reconnect_needed'));
    await act(async () =>
      button('conversation.toolApproval.connect:Notion').click(),
    );
    expect(document.body.textContent).toContain('DRAWER');
  });
});
