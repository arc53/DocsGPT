import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const service = vi.hoisted(() => ({
  getSinglePrompt: vi.fn(),
  updatePrompt: vi.fn(),
  createPrompt: vi.fn(),
}));
vi.mock('../api/services/userService', () => ({ default: service }));

import type { Prompt } from '../models/misc';
import actionToastReducer from '../notifications/actionToastSlice';
import preferenceReducer, { setToken } from '../preferences/preferenceSlice';
import { type PromptDetail, usePromptDetail } from './usePromptDetail';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const response = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

/** A response the test settles when it wants. */
function deferred() {
  let resolve: (body: unknown) => void = () => undefined;
  const promise = new Promise((done) => {
    resolve = (body) =>
      done({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
  return { promise, resolve };
}

const own: Prompt = {
  id: 'p1',
  name: 'Vendor checks',
  type: 'private',
  access: 'owner',
  allowed_actions: ['edit', 'duplicate'],
};
const other: Prompt = { ...own, id: 'p2', name: 'Escalation summary' };

describe('usePromptDetail', () => {
  let container: HTMLDivElement;
  let root: Root;
  const current = { detail: null as PromptDetail | null };

  function Host() {
    current.detail = usePromptDetail({
      prompts: [own, other],
      onSaved: () => undefined,
    });
    return null;
  }

  beforeEach(async () => {
    Object.values(service).forEach((fn) => fn.mockReset());
    const store = configureStore({
      reducer: {
        preference: preferenceReducer,
        actionToast: actionToastReducer,
      },
    });
    store.dispatch(setToken('tok'));
    container = document.createElement('div');
    root = createRoot(container);
    await act(async () =>
      root.render(
        <Provider store={store}>
          <Host />
        </Provider>,
      ),
    );
  });
  afterEach(() => act(() => root.unmount()));

  const detail = () => current.detail!;

  it('keeps the version a save left when the prompt reopens with drafted text', async () => {
    service.getSinglePrompt.mockImplementation(() =>
      response({ content: 'Hello.', updated_at: 'v1' }),
    );
    service.updatePrompt.mockImplementation(() => response({ success: true }));
    await act(async () => detail().open(own));
    await act(async () => detail().setContent('Hello there.'));
    // The save moves the prompt on to v2; reopening with the drafter's text
    // saves over v2, so someone else's later edit is still refused.
    service.getSinglePrompt.mockImplementation(() =>
      response({ content: 'Hello there.', updated_at: 'v2' }),
    );
    await act(async () => void (await detail().save()));
    await act(async () =>
      detail().openWith({ name: own.name, content: 'Hi.' }, own),
    );
    await act(async () => void (await detail().save()));
    expect(service.updatePrompt).toHaveBeenLastCalledWith(
      { id: 'p1', name: own.name, content: 'Hi.', expected_updated_at: 'v2' },
      'tok',
    );
  });

  it('reads the version of a prompt it never loaded when it opens with text', async () => {
    service.getSinglePrompt.mockImplementation(() =>
      response({ content: 'Saved.', updated_at: 'v7' }),
    );
    service.updatePrompt.mockImplementation(() => response({ success: true }));
    await act(async () =>
      detail().openWith({ name: own.name, content: 'Drafted.' }, own),
    );
    // The text stays the drafter's; only the version is read.
    expect(detail().content).toBe('Drafted.');
    await act(async () => void (await detail().save()));
    expect(service.updatePrompt).toHaveBeenCalledWith(
      {
        id: 'p1',
        name: own.name,
        content: 'Drafted.',
        expected_updated_at: 'v7',
      },
      'tok',
    );
  });

  it('drops a copy whose text lands after another prompt opened', async () => {
    const late = deferred();
    service.getSinglePrompt.mockImplementationOnce(() => late.promise);
    service.getSinglePrompt.mockImplementation(() =>
      response({ content: 'Tier 2.', updated_at: 'v1' }),
    );
    let copying: Promise<void> = Promise.resolve();
    await act(async () => {
      copying = detail().duplicate(own);
    });
    await act(async () => detail().open(other));
    await act(async () => {
      late.resolve({ content: 'Hello.', updated_at: 'v1' });
      await copying;
    });
    expect(detail().target).toEqual({ kind: 'edit', prompt: other });
    expect(detail().content).toBe('Tier 2.');
  });

  it('refuses a name of only spaces', async () => {
    await act(async () => detail().add());
    await act(async () => {
      detail().setName('   ');
      detail().setContent('Hello.');
    });
    expect(detail().canSave).toBe(false);
  });
});
