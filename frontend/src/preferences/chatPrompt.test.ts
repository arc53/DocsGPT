import { configureStore } from '@reduxjs/toolkit';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const service = vi.hoisted(() => ({
  getPreferences: vi.fn(),
  updatePreferences: vi.fn(),
  getPrompts: vi.fn(),
}));
vi.mock('../api/services/userService', () => ({ default: service }));

import type { Prompt } from '../models/misc';
import {
  chooseChatPrompt,
  DEFAULT_CHAT_PROMPT,
  fetchChatPromptId,
  initChatPrompt,
  LEGACY_PROMPT_KEY,
  loadChatPrompt,
} from './chatPrompt';
import reducer, {
  prefListenerMiddleware,
  setPrompt,
  setPrompts,
} from './preferenceSlice';

const response = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

/** A request the test answers when it chooses. */
function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

/** Lets pending promise callbacks run. */
const settle = () => new Promise((done) => setTimeout(done, 0));

const presets: Prompt[] = [
  { id: 'default', name: 'default', type: 'public' },
  { id: 'creative', name: 'creative', type: 'public' },
  { id: 'strict', name: 'strict', type: 'public' },
];
const own: Prompt = { id: 'p-own', name: 'Vendor checks', type: 'private' };
const listed = [...presets, own];

const makeStore = () =>
  configureStore({
    reducer: { preference: reducer },
    middleware: (getDefault) =>
      getDefault().prepend(prefListenerMiddleware.middleware),
  });

const chatPromptOf = (store: ReturnType<typeof makeStore>) =>
  store.getState().preference.prompt;

describe('fetchChatPromptId', () => {
  beforeEach(() => service.getPreferences.mockReset());

  it("returns the server's chat prompt", async () => {
    service.getPreferences.mockReturnValue(
      response({ success: true, chat_prompt_id: 'p-own' }),
    );
    await expect(fetchChatPromptId('tok')).resolves.toBe('p-own');
    expect(service.getPreferences).toHaveBeenCalledWith('tok');
  });

  it('returns null when the server refuses or is unreachable', async () => {
    service.getPreferences.mockReturnValueOnce(response({}, false, 401));
    await expect(fetchChatPromptId(null)).resolves.toBeNull();
    service.getPreferences.mockImplementationOnce(() =>
      Promise.reject(new Error('offline')),
    );
    await expect(fetchChatPromptId('tok')).resolves.toBeNull();
  });

  // A start-up blip shouldn't leave the session on default: an unreachable
  // server or a 5xx is asked again; a refusal is final.
  it('asks again after a failure, on the delays given', async () => {
    vi.useFakeTimers();
    try {
      service.getPreferences
        .mockImplementationOnce(() => Promise.reject(new Error('offline')))
        .mockReturnValueOnce(response({}, false, 502))
        .mockReturnValueOnce(response({ chat_prompt_id: 'strict' }));
      const id = fetchChatPromptId('tok', [100, 200]);
      await vi.advanceTimersByTimeAsync(300);
      await expect(id).resolves.toBe('strict');
      expect(service.getPreferences).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not ask again after a refusal', async () => {
    service.getPreferences.mockReturnValue(response({}, false, 403));
    await expect(fetchChatPromptId('tok', [0, 0])).resolves.toBeNull();
    expect(service.getPreferences).toHaveBeenCalledTimes(1);
  });
});

describe('loadChatPrompt', () => {
  beforeEach(() => {
    localStorage.clear();
    service.updatePreferences.mockReset();
    service.updatePreferences.mockReturnValue(response({ success: true }));
  });

  it("uses the server's prompt and forgets this browser's old one", async () => {
    localStorage.setItem(LEGACY_PROMPT_KEY, JSON.stringify(presets[1]));
    const store = makeStore();
    await store.dispatch(loadChatPrompt('p-own', listed, 'tok'));
    expect(chatPromptOf(store)).toEqual(own);
    expect(service.updatePreferences).not.toHaveBeenCalled();
    expect(localStorage.getItem(LEGACY_PROMPT_KEY)).toBeNull();
  });

  it('moves a prompt picked in this browser to the server once', async () => {
    localStorage.setItem(LEGACY_PROMPT_KEY, JSON.stringify(own));
    const store = makeStore();
    await store.dispatch(loadChatPrompt('default', listed, 'tok'));
    expect(service.updatePreferences).toHaveBeenCalledTimes(1);
    expect(service.updatePreferences).toHaveBeenCalledWith(
      { chat_prompt_id: 'p-own' },
      'tok',
    );
    expect(chatPromptOf(store)).toEqual(own);
    expect(localStorage.getItem(LEGACY_PROMPT_KEY)).toBeNull();
  });

  it('keeps the old choice for the next start when the move fails', async () => {
    localStorage.setItem(LEGACY_PROMPT_KEY, JSON.stringify(own));
    service.updatePreferences.mockReturnValue(response({}, false, 500));
    const store = makeStore();
    await store.dispatch(loadChatPrompt('default', listed, 'tok'));
    expect(chatPromptOf(store)).toEqual(own);
    expect(localStorage.getItem(LEGACY_PROMPT_KEY)).not.toBeNull();
  });

  it('drops an old choice that no longer exists without moving it', async () => {
    localStorage.setItem(
      LEGACY_PROMPT_KEY,
      JSON.stringify({ id: 'gone', name: 'Gone', type: 'private' }),
    );
    const store = makeStore();
    await store.dispatch(loadChatPrompt('default', listed, 'tok'));
    expect(service.updatePreferences).not.toHaveBeenCalled();
    expect(chatPromptOf(store)).toEqual(presets[0]);
    expect(localStorage.getItem(LEGACY_PROMPT_KEY)).toBeNull();
  });

  it("keeps this browser's choice when the prompt list didn't load", async () => {
    localStorage.setItem(LEGACY_PROMPT_KEY, JSON.stringify(own));
    const store = makeStore();
    await store.dispatch(loadChatPrompt('default', [], 'tok'));
    expect(service.updatePreferences).not.toHaveBeenCalled();
    expect(localStorage.getItem(LEGACY_PROMPT_KEY)).not.toBeNull();
  });

  it('keeps default and sends nothing when there is no server answer', async () => {
    const store = makeStore();
    store.dispatch(setPrompt(own));
    await store.dispatch(loadChatPrompt(null, listed, null));
    expect(chatPromptOf(store)).toEqual(DEFAULT_CHAT_PROMPT);
    expect(service.updatePreferences).not.toHaveBeenCalled();
  });

  it("falls back to this browser's choice while the server can't answer", async () => {
    localStorage.setItem(LEGACY_PROMPT_KEY, JSON.stringify(own));
    const store = makeStore();
    await store.dispatch(loadChatPrompt(null, listed, 'tok'));
    expect(chatPromptOf(store)).toEqual(own);
    expect(service.updatePreferences).not.toHaveBeenCalled();
    expect(localStorage.getItem(LEGACY_PROMPT_KEY)).not.toBeNull();
  });
});

describe('chooseChatPrompt', () => {
  beforeEach(() => {
    localStorage.clear();
    service.updatePreferences.mockReset();
  });

  it('switches at once and saves the choice on the server', async () => {
    service.updatePreferences.mockReturnValue(response({ success: true }));
    const store = makeStore();
    const saved = store.dispatch(chooseChatPrompt(own, 'tok'));
    expect(chatPromptOf(store)).toEqual(own);
    await expect(saved).resolves.toBe(true);
    expect(service.updatePreferences).toHaveBeenCalledWith(
      { chat_prompt_id: 'p-own' },
      'tok',
    );
    // The browser no longer keeps its own copy.
    expect(localStorage.getItem(LEGACY_PROMPT_KEY)).toBeNull();
  });

  it('switches back when the server refuses', async () => {
    service.updatePreferences.mockReturnValue(response({}, false, 404));
    const store = makeStore();
    store.dispatch(setPrompt(presets[2]));
    await expect(store.dispatch(chooseChatPrompt(own, 'tok'))).resolves.toBe(
      false,
    );
    expect(chatPromptOf(store)).toEqual(presets[2]);
  });

  it('switches back when the request fails', async () => {
    service.updatePreferences.mockImplementation(() =>
      Promise.reject(new Error('offline')),
    );
    const store = makeStore();
    await expect(store.dispatch(chooseChatPrompt(own, 'tok'))).resolves.toBe(
      false,
    );
    expect(chatPromptOf(store).id).toBe('default');
  });
});

describe('chat prompt saves', () => {
  beforeEach(() => {
    localStorage.clear();
    service.updatePreferences.mockReset();
  });

  const sent = () =>
    service.updatePreferences.mock.calls.map(([body]) => body.chat_prompt_id);

  // Out-of-order answers could keep an older pick on the server.
  it('saves one pick at a time, and only the latest of those waiting', async () => {
    const first = deferred<unknown>();
    service.updatePreferences
      .mockReturnValueOnce(first.promise)
      .mockReturnValue(response({ success: true }));
    const store = makeStore();
    const picks = [presets[1], presets[2], own].map((prompt) =>
      store.dispatch(chooseChatPrompt(prompt, 'tok')),
    );
    expect(sent()).toEqual(['creative']);
    first.resolve({ ok: true, json: async () => ({}) });
    await expect(Promise.all(picks)).resolves.toEqual([true, true, true]);
    expect(sent()).toEqual(['creative', 'p-own']);
    expect(chatPromptOf(store)).toEqual(own);
  });

  it('switches back only to what the server confirmed', async () => {
    service.updatePreferences.mockReturnValue(response({}, false, 500));
    const store = makeStore();
    await store.dispatch(loadChatPrompt('strict', listed, 'tok'));
    const picks = [presets[1], own].map((prompt) =>
      store.dispatch(chooseChatPrompt(prompt, 'tok')),
    );
    // The first failed while the second waited: only the last one reports.
    await expect(Promise.all(picks)).resolves.toEqual([true, false]);
    expect(chatPromptOf(store)).toEqual(presets[2]);
  });

  it("compares a pick with the server's value, not the one shown", async () => {
    service.updatePreferences.mockReturnValue(response({ success: true }));
    const store = makeStore();
    await store.dispatch(loadChatPrompt('strict', listed, 'tok'));
    store.dispatch(setPrompt(own));
    await store.dispatch(chooseChatPrompt(own, 'tok'));
    expect(sent()).toEqual(['p-own']);
    // Picking the saved one sends nothing.
    await store.dispatch(chooseChatPrompt(own, 'tok'));
    expect(sent()).toEqual(['p-own']);
  });

  it('keeps a pick made while the start-up load was pending', async () => {
    service.updatePreferences.mockReturnValue(response({ success: true }));
    const store = makeStore();
    const pick = store.dispatch(chooseChatPrompt(own, 'tok'));
    await store.dispatch(loadChatPrompt('strict', listed, 'tok'));
    await pick;
    expect(chatPromptOf(store)).toEqual(own);
  });

  it("shows the server's prompt when it answers after a pick failed", async () => {
    service.updatePreferences.mockReturnValue(response({}, false, 500));
    const store = makeStore();
    await store.dispatch(chooseChatPrompt(own, 'tok'));
    expect(chatPromptOf(store)).toEqual(DEFAULT_CHAT_PROMPT);
    await store.dispatch(loadChatPrompt('strict', listed, 'tok'));
    expect(chatPromptOf(store)).toEqual(presets[2]);
  });

  // Arrow keys over the radios: each card shows at once, one save follows.
  it('waits out a delayed pick, and a newer one restarts the wait', async () => {
    vi.useFakeTimers();
    try {
      service.updatePreferences.mockReturnValue(response({ success: true }));
      const store = makeStore();
      const first = store.dispatch(chooseChatPrompt(presets[1], 'tok', 500));
      await vi.advanceTimersByTimeAsync(400);
      const second = store.dispatch(chooseChatPrompt(presets[2], 'tok', 500));
      expect(chatPromptOf(store)).toEqual(presets[2]);
      await vi.advanceTimersByTimeAsync(400);
      expect(sent()).toEqual([]);
      await vi.advanceTimersByTimeAsync(100);
      await expect(Promise.all([first, second])).resolves.toEqual([true, true]);
      expect(sent()).toEqual(['strict']);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('initChatPrompt', () => {
  beforeEach(() => {
    localStorage.clear();
    service.getPreferences.mockReset();
    service.getPrompts.mockReset();
    service.updatePreferences.mockReset();
  });

  // A chat started before the prompt list loads uses the user's prompt.
  it("applies the server's prompt before the prompt list arrives", async () => {
    const list = deferred<unknown>();
    service.getPrompts.mockReturnValue(list.promise);
    service.getPreferences.mockReturnValue(
      response({ chat_prompt_id: 'creative' }),
    );
    const store = makeStore();
    const done = store.dispatch(
      initChatPrompt('tok', { signedOut: false, cancelled: () => false }),
    );
    await settle();
    expect(chatPromptOf(store)).toEqual(presets[1]);
    list.resolve({ ok: true, json: async () => listed });
    await done;
    expect(chatPromptOf(store)).toEqual(presets[1]);
    expect(store.getState().preference.prompts).toEqual(listed);
  });

  it('names an own prompt once the list arrives', async () => {
    const list = deferred<unknown>();
    service.getPrompts.mockReturnValue(list.promise);
    service.getPreferences.mockReturnValue(
      response({ chat_prompt_id: 'p-own' }),
    );
    const store = makeStore();
    const done = store.dispatch(
      initChatPrompt('tok', { signedOut: false, cancelled: () => false }),
    );
    await settle();
    expect(chatPromptOf(store).id).toBe('p-own');
    list.resolve({ ok: true, json: async () => listed });
    await done;
    expect(chatPromptOf(store)).toEqual(own);
  });

  it('asks the server nothing about the user while signed out', async () => {
    service.getPrompts.mockReturnValue(response(presets));
    const store = makeStore();
    await store.dispatch(
      initChatPrompt(null, { signedOut: true, cancelled: () => false }),
    );
    expect(service.getPreferences).not.toHaveBeenCalled();
    expect(chatPromptOf(store)).toEqual(DEFAULT_CHAT_PROMPT);
  });
});

describe('the prompt list', () => {
  it('falls back to default when the chat prompt leaves the list', () => {
    const store = makeStore();
    store.dispatch(setPrompt(own));
    store.dispatch(setPrompts(presets));
    expect(chatPromptOf(store)).toEqual(presets[0]);
  });

  it('follows a rename of the chat prompt', () => {
    const store = makeStore();
    store.dispatch(setPrompt(own));
    store.dispatch(setPrompts([...presets, { ...own, name: 'Renamed' }]));
    expect(chatPromptOf(store).name).toBe('Renamed');
  });

  it('never writes the chat prompt to this browser', () => {
    localStorage.clear();
    const store = makeStore();
    store.dispatch(setPrompt(own));
    expect(localStorage.getItem(LEGACY_PROMPT_KEY)).toBeNull();
  });
});
