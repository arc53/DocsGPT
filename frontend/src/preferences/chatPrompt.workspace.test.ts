import { configureStore } from '@reduxjs/toolkit';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const service = vi.hoisted(() => ({
  getPreferences: vi.fn(),
  updatePreferences: vi.fn(),
  getPrompts: vi.fn(),
}));
vi.mock('../api/services/userService', () => ({ default: service }));

import type { Prompt } from '../models/misc';
import { setRequestWorkspace } from '../workspace/requestWorkspace';
import {
  chatPromptDeleted,
  chooseChatPrompt,
  initChatPrompt,
  teamChatPromptKey,
} from './chatPrompt';
import reducer, { prefListenerMiddleware } from './preferenceSlice';

const response = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

const settle = () => new Promise((done) => setTimeout(done, 0));

const presets: Prompt[] = [
  { id: 'default', name: 'default', type: 'public' },
  { id: 'strict', name: 'strict', type: 'public' },
];
const teamPrompt: Prompt = {
  id: 'p-team',
  name: 'Carrier tone',
  type: 'private',
};
const ownPrompt: Prompt = {
  id: 'p-own',
  name: 'Vendor checks',
  type: 'private',
};

const jwtFor = (sub: string) =>
  `e30.${btoa(JSON.stringify({ sub })).replace(/=+$/, '')}.sig`;
const TOKEN = jwtFor('lena');

const makeStore = () =>
  configureStore({
    reducer: { preference: reducer },
    middleware: (getDefault) =>
      getDefault().prepend(prefListenerMiddleware.middleware),
  });

const init = (store: ReturnType<typeof makeStore>) =>
  store.dispatch(
    initChatPrompt(TOKEN, { signedOut: false, cancelled: () => false }),
  );

beforeEach(() => {
  localStorage.clear();
  service.getPreferences.mockReset();
  service.updatePreferences.mockReset();
  service.getPrompts.mockReset();
  service.updatePreferences.mockReturnValue(response({ success: true }));
});

afterEach(() => setRequestWorkspace('personal', 0));

describe('the chat prompt in a team', () => {
  it('a pick is kept for that team in this browser and never sent', async () => {
    setRequestWorkspace('t1', 1);
    const store = makeStore();
    const saved = await store.dispatch(chooseChatPrompt(teamPrompt, TOKEN));
    expect(saved).toBe(true);
    expect(store.getState().preference.prompt.id).toBe('p-team');
    expect(JSON.parse(localStorage.getItem(teamChatPromptKey('t1'))!)).toEqual(
      teamPrompt,
    );
    expect(service.updatePreferences).not.toHaveBeenCalled();
  });

  it("start-up reads the team's pick, not the server's", async () => {
    setRequestWorkspace('t1', 1);
    localStorage.setItem(teamChatPromptKey('t1'), JSON.stringify(teamPrompt));
    service.getPrompts.mockReturnValue(response([...presets, teamPrompt]));
    const store = makeStore();
    await init(store);
    expect(store.getState().preference.prompt.id).toBe('p-team');
    expect(service.getPreferences).not.toHaveBeenCalled();
  });

  it('a team with no pick uses default', async () => {
    setRequestWorkspace('t2', 1);
    service.getPrompts.mockReturnValue(response(presets));
    const store = makeStore();
    await init(store);
    expect(store.getState().preference.prompt.id).toBe('default');
  });

  it('a pick deleted since falls back to default', async () => {
    setRequestWorkspace('t1', 1);
    localStorage.setItem(teamChatPromptKey('t1'), JSON.stringify(teamPrompt));
    service.getPrompts.mockReturnValue(response(presets));
    const store = makeStore();
    await init(store);
    expect(store.getState().preference.prompt.id).toBe('default');
  });

  it('each team keeps its own pick', async () => {
    const store = makeStore();
    setRequestWorkspace('t1', 1);
    await store.dispatch(chooseChatPrompt(teamPrompt, TOKEN));
    setRequestWorkspace('t2', 2);
    service.getPrompts.mockReturnValue(response(presets));
    await init(store);
    expect(store.getState().preference.prompt.id).toBe('default');
  });

  it("deleting the team's pick forgets it", async () => {
    setRequestWorkspace('t1', 1);
    const store = makeStore();
    await store.dispatch(chooseChatPrompt(teamPrompt, TOKEN));
    store.dispatch(chatPromptDeleted('p-team', TOKEN));
    expect(store.getState().preference.prompt.id).toBe('default');
    expect(localStorage.getItem(teamChatPromptKey('t1'))).toBeNull();
  });

  it("back in Personal, the person's own pick shows again", async () => {
    const store = makeStore();
    service.getPreferences.mockReturnValue(
      response({ chat_prompt_id: 'default', chat_prompt_set: true }),
    );
    service.getPrompts.mockReturnValue(response([...presets, ownPrompt]));
    await init(store);
    await store.dispatch(chooseChatPrompt(ownPrompt, TOKEN));
    await settle();
    expect(service.updatePreferences).toHaveBeenCalledTimes(1);

    setRequestWorkspace('t1', 1);
    service.getPrompts.mockReturnValue(response([...presets, teamPrompt]));
    await store.dispatch(chooseChatPrompt(teamPrompt, TOKEN));
    expect(store.getState().preference.prompt.id).toBe('p-team');

    setRequestWorkspace('personal', 2);
    service.getPrompts.mockReturnValue(response([...presets, ownPrompt]));
    service.getPreferences.mockReturnValue(
      response({ chat_prompt_id: 'p-own', chat_prompt_set: true }),
    );
    await init(store);
    expect(store.getState().preference.prompt.id).toBe('p-own');
    // The team's pick never reached the server.
    expect(service.updatePreferences).toHaveBeenCalledTimes(1);
  });
});
