import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));
vi.mock('../upload/Upload', () => ({ default: () => null }));
vi.mock('../modals/AddToolModal', () => ({ default: () => null }));
vi.mock('../connectors/SignInAgainNotice', () => ({
  default: () => null,
  useSignInAgain: () => ({ reconnect: vi.fn(), modals: null }),
}));
vi.mock('../api/services/payerService', () => ({
  default: { getQuota: vi.fn() },
}));

import payerService, { type QuotaResponse } from '../api/services/payerService';
import type { Agent } from '../agents/types';
import connectorsReducer from '../connectors/connectorsSlice';
import chatToolsReducer from '../conversation/chatToolsSlice';
import notificationsReducer, {
  sseHealthChanged,
} from '../notifications/notificationsSlice';
import usageReducer, { loadUsage } from '../payer/usageSlice';
import { prefSlice, setSelectedAgent } from '../preferences/preferenceSlice';
import uploadReducer from '../upload/uploadSlice';
import MessageInput from './MessageInput';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const getQuota = vi.mocked(payerService.getQuota);
const RESET = '2026-12-01T00:00:00+00:00';

// The person's agent allowance is used up; the overall one is not.
const agentSpent: QuotaResponse = {
  period: 'month',
  buckets: [
    {
      bucket: 'agent',
      tokens: { limit: null, used: 0 },
      cost: { limit: 10, used: 10 },
      resets_at: RESET,
    },
  ],
  notice: null,
  parts: null,
  paused: null,
};

const makeStore = () =>
  configureStore({
    reducer: {
      preference: prefSlice.reducer,
      upload: uploadReducer,
      notifications: notificationsReducer,
      connectors: connectorsReducer,
      chatTools: chatToolsReducer,
      usage: usageReducer,
    },
  });

describe('MessageInput and the person’s allowance', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;

  beforeEach(async () => {
    localStorage.clear();
    getQuota.mockReset();
    getQuota.mockResolvedValue(agentSpent);
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    store = makeStore();
    store.dispatch(sseHealthChanged('healthy'));
    await store.dispatch(loadUsage());
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (agent: Partial<Agent>) => {
    store.dispatch(setSelectedAgent({ id: 'a1', name: 'Helper', ...agent }));
    await act(async () => {
      root.render(
        <MemoryRouter>
          <Provider store={store}>
            <MessageInput
              onSubmit={vi.fn()}
              loading={false}
              showSourceButton={false}
              showToolButton={false}
              autoFocus={false}
              usageNotice
            />
          </Provider>
        </MemoryRouter>,
      );
    });
  };

  const type = async (text: string) => {
    const el = container.querySelector<HTMLTextAreaElement>('#message-input')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        'value',
      )!.set!.call(el, text);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  const sendButton = () =>
    container.querySelector<HTMLButtonElement>(
      'button[aria-label="conversation.send"]',
    );
  const stopCard = () =>
    container.querySelector('[data-testid="usage-reached"]');

  it('stops a chat with the person’s own agent', async () => {
    await render({ access: 'owner', workspace: { kind: 'personal' } });
    await type('hello');
    expect(stopCard()).not.toBeNull();
    expect(sendButton()?.disabled).toBe(true);
  });

  it('lets a chat with an agent reached by its link send: its publisher pays', async () => {
    await render({
      access: 'viewer',
      allowed_actions: ['pin', 'use'],
      origin: 'link',
    });
    await type('hello');
    expect(stopCard()).toBeNull();
    expect(sendButton()?.disabled).toBe(false);
  });
});
