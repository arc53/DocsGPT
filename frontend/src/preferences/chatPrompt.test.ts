import { configureStore } from '@reduxjs/toolkit';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const service = vi.hoisted(() => ({
  getPreferences: vi.fn(),
  updatePreferences: vi.fn(),
}));
vi.mock('../api/services/userService', () => ({ default: service }));

import type { Prompt } from '../models/misc';
import {
  chooseChatPrompt,
  DEFAULT_CHAT_PROMPT,
  fetchChatPromptId,
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
