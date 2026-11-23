import { configureStore } from '@reduxjs/toolkit';

import activityReducer from '../activity/activitySlice';
import schedulesReducer from '../agents/schedules/schedulesSlice';
import foldersReducer, {
  loadFolders,
} from '../components/folders/foldersSlice';
import chatToolsReducer, {
  loadChatTools,
} from '../conversation/chatToolsSlice';
import { conversationSlice } from '../conversation/conversationSlice';
import {
  prefListenerMiddleware,
  prefSlice,
} from '../preferences/preferenceSlice';
import { presetPrompts } from '../prompts/promptAccess';
import { workspaceListenerMiddleware } from './workspaceListener';
import workspaceReducer, { switchWorkspace } from './workspaceSlice';

const agent = { id: 'a1', name: 'Carrier desk' };
const doc = { id: 's1', name: 'Rates', date: '2026-11-01' };

const makeStore = () =>
  configureStore({
    reducer: {
      workspace: workspaceReducer,
      preference: prefSlice.reducer,
      conversation: conversationSlice.reducer,
      folders: foldersReducer,
      chatTools: chatToolsReducer,
      activity: activityReducer,
      schedules: schedulesReducer,
    },
    middleware: (getDefault) =>
      getDefault({ serializableCheck: false }).concat(
        workspaceListenerMiddleware.middleware,
        prefListenerMiddleware.middleware,
      ),
  });

/** A store with something in every list a switch must clear. */
const filledStore = () => {
  const store = makeStore();
  const p = prefSlice.actions;
  store.dispatch(p.setToken('tok'));
  store.dispatch(p.setAgents([agent]));
  store.dispatch(p.setSharedAgents([agent]));
  store.dispatch(p.setSelectedAgent(agent));
  store.dispatch(p.setSourceDocs([doc]));
  store.dispatch(p.setSelectedDocs([doc]));
  store.dispatch(p.setSelectedFolders([{ id: 'f1', name: 'Rates' }]));
  store.dispatch(p.setPaginatedDocuments([doc]));
  store.dispatch(
    p.setPrompts([
      ...presetPrompts(),
      { id: 'p1', name: 'Team voice', type: 'private' },
    ]),
  );
  store.dispatch(
    p.setConversations({
      data: [{ id: 'c1', name: 'Late carrier', agent_id: null }],
      loading: false,
    }),
  );
  store.dispatch(
    p.setAvailableModels([{ id: 'm1', provider: 'openai' } as never]),
  );
  store.dispatch(conversationSlice.actions.setConversation([{ prompt: 'hi' }]));
  store.dispatch(
    conversationSlice.actions.updateConversationId({
      query: { conversationId: 'c1' },
    }),
  );
  store.dispatch({
    type: loadFolders.fulfilled.type,
    payload: [{ id: 'f1', name: 'Rates' }],
    meta: { arg: { type: 'source', token: 'tok' }, requestId: 'r1' },
  });
  store.dispatch({
    type: loadChatTools.fulfilled.type,
    payload: [{ id: 'tool1', name: 'search' }],
    meta: { arg: { token: 'tok' }, requestId: null },
  });
  return store;
};

beforeEach(() => localStorage.clear());

describe('workspace/switched resets what belongs to the old workspace', () => {
  it('clears the preference lists and selections', () => {
    const store = filledStore();
    store.dispatch(switchWorkspace('t1'));
    const pref = store.getState().preference;
    expect(pref.agents).toBeNull();
    expect(pref.sharedAgents).toBeNull();
    expect(pref.selectedAgent).toBeNull();
    expect(pref.sourceDocs).toBeNull();
    expect(pref.sourceDocsFailed).toBe(false);
    expect(pref.paginatedDocuments).toBeNull();
    expect(pref.selectedDocs).toEqual([]);
    expect(pref.selectedFolders).toEqual([]);
    expect(pref.prompts).toEqual(presetPrompts());
    expect(pref.conversations).toEqual({ data: null, loading: false });
  });

  it('keeps the session; the model list loads again', () => {
    const store = filledStore();
    store.dispatch(switchWorkspace('t1'));
    const pref = store.getState().preference;
    // Custom models are the workspace's, so the list is read again there.
    expect(pref.availableModels).toEqual([]);
    expect(pref.token).toBe('tok');
  });

  it('forgets the stored chat selections, so a reload does not bring them back', () => {
    const store = filledStore();
    expect(localStorage.getItem('DocsGPTRecentDocs')).not.toBeNull();
    expect(localStorage.getItem('DocsGPTRecentFolders')).not.toBeNull();
    store.dispatch(switchWorkspace('t1'));
    expect(localStorage.getItem('DocsGPTRecentDocs')).toBeNull();
    expect(localStorage.getItem('DocsGPTRecentFolders')).toBeNull();
  });

  it('closes the open chat', () => {
    const store = filledStore();
    expect(store.getState().conversation.conversationId).toBe('c1');
    store.dispatch(switchWorkspace('t1'));
    const conversation = store.getState().conversation;
    expect(conversation.conversationId).toBeNull();
    expect(conversation.queries).toEqual([]);
    expect(conversation.status).toBe('idle');
  });

  it('clears the folders and drops an answer still out', () => {
    const store = filledStore();
    // A load sent in the old workspace…
    store.dispatch({
      type: loadFolders.pending.type,
      meta: { arg: { type: 'agent', token: 'tok' }, requestId: 'old' },
    });
    store.dispatch(switchWorkspace('t1'));
    expect(store.getState().folders.tree.items).toEqual([]);
    expect(store.getState().folders.tree.loaded).toBe(false);
    // …answers after the switch: it is not applied.
    store.dispatch({
      type: loadFolders.fulfilled.type,
      payload: [{ id: 'f9', name: 'Old' }],
      meta: { arg: { type: 'agent', token: 'tok' }, requestId: 'old' },
    });
    expect(store.getState().folders.tree.items).toEqual([]);
  });

  it('clears the chat tools and drops an answer still out', () => {
    const store = filledStore();
    store.dispatch({
      type: loadChatTools.pending.type,
      meta: { arg: { token: 'tok' }, requestId: 'old' },
    });
    store.dispatch(switchWorkspace('t1'));
    expect(store.getState().chatTools.tools).toEqual([]);
    expect(store.getState().chatTools.loaded).toBe(false);
    store.dispatch({
      type: loadChatTools.fulfilled.type,
      payload: [{ id: 'tool9' }],
      meta: { arg: { token: 'tok' }, requestId: 'old' },
    });
    expect(store.getState().chatTools.tools).toEqual([]);
  });

  it('clears Activity and drops an answer still out', () => {
    const store = filledStore();
    store.dispatch({
      type: 'activity/loadNow/pending',
      meta: { requestId: 'old' },
    });
    store.dispatch(switchWorkspace('t1'));
    expect(store.getState().activity.now).toBeNull();
    store.dispatch({
      type: 'activity/loadNow/fulfilled',
      payload: { running: [], recent: [] },
      meta: { requestId: 'old' },
    });
    expect(store.getState().activity.now).toBeNull();
  });

  it('clears the schedules and drops an answer still out', () => {
    const store = filledStore();
    store.dispatch({
      type: 'schedules/loadAll/pending',
      meta: { arg: { token: 'tok' }, requestId: 'old' },
    });
    store.dispatch(switchWorkspace('t1'));
    expect(store.getState().schedules.all).toBeNull();
    store.dispatch({
      type: 'schedules/loadAll/fulfilled',
      payload: [{ id: 'sch1' }],
      meta: { arg: { token: 'tok' }, requestId: 'old' },
    });
    expect(store.getState().schedules.all).toBeNull();
  });
});
