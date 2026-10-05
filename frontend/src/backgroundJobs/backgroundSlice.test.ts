import { configureStore } from '@reduxjs/toolkit';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const service = vi.hoisted(() => ({
  getJob: vi.fn(),
  listJobs: vi.fn(),
  cancelJob: vi.fn(),
  getPushConfig: vi.fn(),
  markConversationRead: vi.fn(async () => undefined),
}));
vi.mock('../api/services/backgroundService', () => ({ default: service }));

import { sseEventReceived } from '../notifications/notificationsSlice';
import {
  appendConversations,
  receiveConversations,
} from '../preferences/preferenceSlice';
import backgroundReducer, {
  cancelBackgroundJob,
  closePushPrompt,
  dismissConversationNotification,
  fetchBackgroundJob,
  fetchConversationJobs,
  fetchPushConfig,
  JOB_LIST_MIN_INTERVAL_MS,
  markConversationRead,
  markConversationUnread,
  requestPushPrompt,
  selectBackgroundJob,
  selectDismissedNotifications,
  selectIsUnread,
  selectJobUnavailable,
  selectPushConfig,
  selectPushPromptOpen,
} from './backgroundSlice';

const makeStore = () =>
  configureStore({
    reducer: {
      background: backgroundReducer,
      preference: (state = { token: 'tok' }) => state,
    },
  });

const jobUpdated = (payload: Record<string, unknown>, id = 'e1') =>
  sseEventReceived({ id, type: 'job.updated', payload });

describe('backgroundSlice', () => {
  beforeEach(() => {
    localStorage.clear();
    Object.values(service).forEach((fn) => fn.mockReset());
  });

  it('tracks a job from job.updated events', () => {
    const store = makeStore();
    store.dispatch(
      jobUpdated({
        job_id: 'j1',
        conversation_id: 'c1',
        status: 'working',
        progress: { percent: 40, last: 'step 4' },
        tool_name: 'code_executor',
        action_name: 'run_code',
      }),
    );
    const job = selectBackgroundJob('j1')(store.getState());
    expect(job).toMatchObject({
      job_id: 'j1',
      status: 'working',
      progress: { percent: 40, last: 'step 4' },
      tool_name: 'code_executor',
    });
    expect(job?.receivedAt).toBeGreaterThan(0);
  });

  it('ignores other events and events without a job id', () => {
    const store = makeStore();
    store.dispatch(
      sseEventReceived({ type: 'other', payload: { job_id: 'j' } }),
    );
    store.dispatch(jobUpdated({ status: 'working' }));
    expect(store.getState().background.jobs).toEqual({});
  });

  it('keeps what it knew when an update leaves fields out', () => {
    const store = makeStore();
    service.getJob.mockResolvedValue({
      job_id: 'j1',
      status: 'working',
      started_at: '2026-10-06T10:00:00Z',
      tool_name: 'code_executor',
    });
    return store.dispatch(fetchBackgroundJob('j1')).then(() => {
      store.dispatch(
        jobUpdated({
          job_id: 'j1',
          status: 'working',
          progress: { percent: 5 },
        }),
      );
      expect(selectBackgroundJob('j1')(store.getState())).toMatchObject({
        started_at: '2026-10-06T10:00:00Z',
        tool_name: 'code_executor',
        progress: { percent: 5 },
      });
    });
  });

  it('never revives a finished job from a late event or a stale fetch', async () => {
    const store = makeStore();
    store.dispatch(jobUpdated({ job_id: 'j1', status: 'completed' }));
    store.dispatch(jobUpdated({ job_id: 'j1', status: 'working' }, 'e2'));
    service.getJob.mockResolvedValue({ job_id: 'j1', status: 'working' });
    await store.dispatch(fetchBackgroundJob('j1'));
    expect(selectBackgroundJob('j1')(store.getState())?.status).toBe(
      'completed',
    );
  });

  it('treats an unknown status as no change', () => {
    const store = makeStore();
    store.dispatch(jobUpdated({ job_id: 'j1', status: 'failed' }));
    store.dispatch(jobUpdated({ job_id: 'j1', status: 'weird' }, 'e2'));
    expect(selectBackgroundJob('j1')(store.getState())?.status).toBe('failed');
  });

  it('marks a job the user cannot read, and only for that', async () => {
    const store = makeStore();
    service.getJob.mockRejectedValueOnce(new Error('HTTP 404'));
    await store.dispatch(fetchBackgroundJob('j1'));
    expect(selectJobUnavailable('j1')(store.getState())).toBe(true);
    service.getJob.mockRejectedValueOnce(new Error('HTTP 503'));
    await store.dispatch(fetchBackgroundJob('j2'));
    expect(selectJobUnavailable('j2')(store.getState())).toBe(false);
  });

  it('merges a cancel answer', async () => {
    const store = makeStore();
    service.cancelJob.mockResolvedValue({
      job_id: 'j1',
      status: 'working',
      cancel_requested: true,
    });
    await store.dispatch(cancelBackgroundJob('j1'));
    expect(selectBackgroundJob('j1')(store.getState())?.cancel_requested).toBe(
      true,
    );
  });

  describe('fetchConversationJobs', () => {
    it('merges every job of the conversation', async () => {
      const store = makeStore();
      service.listJobs.mockResolvedValue([
        { job_id: 'j1', status: 'working' },
        { job_id: 'j2', status: 'failed' },
      ]);
      await store.dispatch(fetchConversationJobs('c1'));
      expect(service.listJobs).toHaveBeenCalledWith('c1', 'tok');
      expect(selectBackgroundJob('j2')(store.getState())?.status).toBe(
        'failed',
      );
    });

    it('several cards asking at once share one request', async () => {
      const store = makeStore();
      service.listJobs.mockResolvedValue([]);
      await Promise.all([
        store.dispatch(fetchConversationJobs('c1')),
        store.dispatch(fetchConversationJobs('c1')),
        store.dispatch(fetchConversationJobs('c2')),
      ]);
      expect(service.listJobs).toHaveBeenCalledTimes(2);
    });

    it('asks again once the interval passed', async () => {
      vi.useFakeTimers();
      try {
        const store = makeStore();
        service.listJobs.mockResolvedValue([]);
        await store.dispatch(fetchConversationJobs('c1'));
        vi.advanceTimersByTime(JOB_LIST_MIN_INTERVAL_MS + 1);
        await store.dispatch(fetchConversationJobs('c1'));
        expect(service.listJobs).toHaveBeenCalledTimes(2);
      } finally {
        vi.useRealTimers();
      }
    });
  });

  describe('unread marks', () => {
    it('follow the sidebar listing', () => {
      const store = makeStore();
      store.dispatch(
        receiveConversations({
          data: [
            { id: 'c1', name: 'a', unread: true },
            { id: 'c2', name: 'b', unread: false },
          ],
          loading: false,
        }),
      );
      expect(selectIsUnread('c1')(store.getState())).toBe(true);
      expect(selectIsUnread('c2')(store.getState())).toBe(false);
      store.dispatch(
        appendConversations([{ id: 'c3', name: 'c', unread: true }]),
      );
      expect(selectIsUnread('c3')(store.getState())).toBe(true);
    });

    it('a listing without the flag (search results) changes nothing', () => {
      const store = makeStore();
      store.dispatch(markConversationUnread('c1'));
      store.dispatch(appendConversations([{ id: 'c1', name: 'a' }]));
      expect(selectIsUnread('c1')(store.getState())).toBe(true);
      store.dispatch(
        receiveConversations({
          data: [{ id: 'c1', name: 'a', unread: false }],
          loading: false,
        }),
      );
      expect(selectIsUnread('c1')(store.getState())).toBe(false);
    });

    it('clear at once when the conversation is opened, and tell the server', async () => {
      const store = makeStore();
      store.dispatch(markConversationUnread('c1'));
      const pending = store.dispatch(markConversationRead('c1'));
      expect(selectIsUnread('c1')(store.getState())).toBe(false);
      await pending;
      expect(service.markConversationRead).toHaveBeenCalledWith('c1', 'tok');
    });
  });

  it('opens and closes the push prompt', () => {
    const store = makeStore();
    expect(selectPushPromptOpen(store.getState())).toBe(false);
    store.dispatch(requestPushPrompt());
    expect(selectPushPromptOpen(store.getState())).toBe(true);
    store.dispatch(closePushPrompt());
    expect(selectPushPromptOpen(store.getState())).toBe(false);
  });

  it('reads the push config, and treats a failure as push off', async () => {
    const store = makeStore();
    service.getPushConfig.mockResolvedValueOnce({
      enabled: true,
      public_key: 'BKEY',
    });
    await store.dispatch(fetchPushConfig());
    expect(selectPushConfig(store.getState())).toEqual({
      enabled: true,
      public_key: 'BKEY',
    });
    service.getPushConfig.mockRejectedValueOnce(new Error('HTTP 500'));
    await store.dispatch(fetchPushConfig());
    expect(selectPushConfig(store.getState())).toEqual({
      enabled: false,
      public_key: null,
    });
  });

  it('remembers dismissed notifications across reloads, once each', () => {
    const store = makeStore();
    store.dispatch(dismissConversationNotification('n1'));
    store.dispatch(dismissConversationNotification('n1'));
    store.dispatch(dismissConversationNotification('n2'));
    expect(
      selectDismissedNotifications(store.getState()).map((e) => e.id),
    ).toEqual(['n1', 'n2']);
    const saved = JSON.parse(
      localStorage.getItem('docsgpt:dismissedConversationNotifications') ??
        '[]',
    );
    expect(saved.map((e: { id: string }) => e.id)).toEqual(['n1', 'n2']);
  });

  it('reads as empty from a store without the slice', () => {
    expect(selectBackgroundJob('j')({})).toBeUndefined();
    expect(selectIsUnread('c')({})).toBe(false);
    expect(selectPushPromptOpen({})).toBe(false);
    expect(selectDismissedNotifications({})).toEqual([]);
  });
});
