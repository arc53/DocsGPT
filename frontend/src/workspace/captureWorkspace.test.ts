import { configureStore } from '@reduxjs/toolkit';

import {
  captureWorkspace,
  requestWorkspace,
  setRequestWorkspace,
  WORKSPACE_HEADER,
  workspaceHeader,
} from './requestWorkspace';
import { workspaceListenerMiddleware } from './workspaceListener';
import workspaceReducer, { switchWorkspace } from './workspaceSlice';

afterEach(() => setRequestWorkspace('personal', 0));

describe('captureWorkspace', () => {
  it('is current until the workspace changes', () => {
    setRequestWorkspace('personal', 0);
    const captured = captureWorkspace();
    expect(captured).toMatchObject({ id: 'personal', epoch: 0 });
    expect(captured.isCurrent()).toBe(true);
    setRequestWorkspace('t1', 1);
    expect(captured.isCurrent()).toBe(false);
  });

  it('stays stale after switching away and back', () => {
    setRequestWorkspace('personal', 0);
    const captured = captureWorkspace();
    setRequestWorkspace('t1', 1);
    setRequestWorkspace('personal', 2);
    // Same id, but the lists it would land in were reset in between.
    expect(captured.isCurrent()).toBe(false);
    expect(captureWorkspace().isCurrent()).toBe(true);
  });

  it('follows a switch dispatched to the store', () => {
    const store = configureStore({
      reducer: { workspace: workspaceReducer },
      middleware: (getDefault) =>
        getDefault().prepend(workspaceListenerMiddleware.middleware),
    });
    const captured = captureWorkspace();
    store.dispatch(switchWorkspace('t1'));
    expect(captured.isCurrent()).toBe(false);
    const now = captureWorkspace();
    expect(now.id).toBe('t1');
    expect(now.epoch).toBe(store.getState().workspace.epoch);
    expect(now.isCurrent()).toBe(true);
  });
});

describe('workspaceHeader', () => {
  it('names the current workspace by default', () => {
    setRequestWorkspace('t1', 1);
    expect(requestWorkspace()).toBe('t1');
    expect(workspaceHeader()).toEqual({ [WORKSPACE_HEADER]: 't1' });
  });

  it('names the workspace it is given', () => {
    setRequestWorkspace('t1', 1);
    expect(workspaceHeader('personal')).toEqual({
      'X-DocsGPT-Workspace': 'personal',
    });
  });
});
