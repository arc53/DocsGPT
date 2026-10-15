import { describe, expect, it, vi } from 'vitest';

const service = vi.hoisted(() => ({ remove: vi.fn() }));
vi.mock('../../api/services/schedulesService', () => ({ default: service }));

import {
  sseEventReceived,
  type SSEEvent,
} from '../../notifications/notificationsSlice';
import type { Schedule, ScheduleRun } from '../types/schedule';
import reducer, {
  resetSchedules,
  createSchedule,
  applyEvent,
  deleteSchedule,
  loadAllSchedules,
  selectAllSchedules,
  setSchedulePaused,
  loadRunsForSchedule,
  RUNS_PAGE_SIZE,
  selectRunsEnd,
  selectRunsForSchedule,
  selectSchedulesForAgent,
  type SchedulesState,
} from './schedulesSlice';

const sampleSchedule = (overrides: Partial<Schedule> = {}): Schedule => ({
  id: 'sched-1',
  user_id: 'alice',
  agent_id: 'agent-1',
  trigger_type: 'recurring',
  instruction: 'do it',
  status: 'active',
  timezone: 'UTC',
  tool_allowlist: [],
  created_via: 'ui',
  consecutive_failure_count: 0,
  created_at: '2026-05-19T12:00:00Z',
  updated_at: '2026-05-19T12:00:00Z',
  ...overrides,
});

const sampleRun = (overrides: Partial<ScheduleRun> = {}): ScheduleRun => ({
  id: 'run-1',
  schedule_id: 'sched-1',
  user_id: 'alice',
  agent_id: 'agent-1',
  status: 'pending',
  scheduled_for: '2026-05-19T12:00:00Z',
  trigger_source: 'cron',
  output_truncated: false,
  prompt_tokens: 0,
  generated_tokens: 0,
  created_at: '2026-05-19T12:00:00Z',
  updated_at: '2026-05-19T12:00:00Z',
  ...overrides,
});

const seedState = () => reducer(undefined, { type: '@@INIT' });

const seedWithSchedule = (): SchedulesState => {
  let state = seedState();
  state = reducer(
    state,
    applyEvent({ type: 'noop', scheduleId: 'sched-1', run: sampleRun() }),
  );
  return {
    ...state,
    byAgent: { 'agent-1': [sampleSchedule()] } as Record<string, Schedule[]>,
  };
};

describe('schedulesSlice SSE event handling', () => {
  it('schedule.run.completed upserts run + bumps last_run_at', () => {
    let state = seedWithSchedule();
    const envelope: SSEEvent = {
      id: 'evt-1',
      ts: '2026-05-19T12:05:00Z',
      type: 'schedule.run.completed',
      payload: {
        run_id: 'run-1',
        schedule_id: 'sched-1',
        status: 'success',
      },
    };
    state = reducer(state, sseEventReceived(envelope));
    const runs = selectRunsForSchedule({ schedules: state }, 'sched-1');
    expect(runs[0].status).toBe('success');
    const schedules = selectSchedulesForAgent({ schedules: state }, 'agent-1');
    expect(schedules[0].last_run_at).toBe('2026-05-19T12:05:00Z');
  });

  it('schedule.run.failed marks the run as failed and carries error_type', () => {
    let state = seedWithSchedule();
    const envelope: SSEEvent = {
      id: 'evt-2',
      ts: '2026-05-19T12:06:00Z',
      type: 'schedule.run.failed',
      payload: {
        run_id: 'run-1',
        schedule_id: 'sched-1',
        error_type: 'agent_error',
        error: 'LLM exploded',
      },
    };
    state = reducer(state, sseEventReceived(envelope));
    const runs = selectRunsForSchedule({ schedules: state }, 'sched-1');
    expect(runs[0].status).toBe('failed');
    expect(runs[0].error_type).toBe('agent_error');
    expect(runs[0].error).toBe('LLM exploded');
  });

  it('schedule.autopaused flips the schedule status to paused', () => {
    let state = seedWithSchedule();
    const envelope: SSEEvent = {
      id: 'evt-3',
      ts: '2026-05-19T12:07:00Z',
      type: 'schedule.autopaused',
      payload: { schedule_id: 'sched-1' },
    };
    state = reducer(state, sseEventReceived(envelope));
    const schedules = selectSchedulesForAgent({ schedules: state }, 'agent-1');
    expect(schedules[0].status).toBe('paused');
  });

  it('schedule.resumed flips a paused schedule back to active', () => {
    let state = seedState();
    state = {
      ...state,
      byAgent: {
        'agent-1': [sampleSchedule({ status: 'paused' })],
      } as Record<string, Schedule[]>,
    };
    state = reducer(
      state,
      sseEventReceived({
        id: 'evt-r',
        ts: '2026-05-19T12:07:30Z',
        type: 'schedule.resumed',
        payload: { schedule_id: 'sched-1', status: 'active' },
      }),
    );
    const schedules = selectSchedulesForAgent({ schedules: state }, 'agent-1');
    expect(schedules[0].status).toBe('active');
  });

  it('schedule.cancelled and schedule.completed set their terminal status', () => {
    for (const [type, expected] of [
      ['schedule.cancelled', 'cancelled'],
      ['schedule.completed', 'completed'],
    ] as const) {
      let state = seedWithSchedule();
      state = reducer(
        state,
        sseEventReceived({
          id: `evt-${type}`,
          ts: '2026-05-19T12:09:00Z',
          type,
          payload: { schedule_id: 'sched-1', status: expected },
        }),
      );
      const schedules = selectSchedulesForAgent(
        { schedules: state },
        'agent-1',
      );
      expect(schedules[0].status).toBe(expected);
    }
  });

  it('schedule.message.appended is acknowledged without mutating run state', () => {
    let state = seedWithSchedule();
    const envelope: SSEEvent = {
      id: 'evt-4',
      ts: '2026-05-19T12:08:00Z',
      type: 'schedule.message.appended',
      payload: {
        schedule_id: 'sched-1',
        run_id: 'run-1',
        conversation_id: 'conv-1',
        message_id: 'msg-1',
      },
    };
    const before = JSON.stringify(state);
    state = reducer(state, sseEventReceived(envelope));
    expect(JSON.stringify(state)).toBe(before);
  });

  it('ignores envelopes without a schedule_id payload', () => {
    let state = seedWithSchedule();
    const envelope: SSEEvent = {
      id: 'evt-5',
      type: 'schedule.run.completed',
      payload: { run_id: 'run-1' },
    };
    const before = JSON.stringify(state);
    state = reducer(state, sseEventReceived(envelope));
    expect(JSON.stringify(state)).toBe(before);
  });

  it('inserts a stub run row when the envelope arrives before the run log is loaded', () => {
    let state = seedState();
    state = {
      ...state,
      byAgent: { 'agent-1': [sampleSchedule()] } as Record<string, Schedule[]>,
    };
    const envelope: SSEEvent = {
      id: 'evt-6',
      ts: '2026-05-19T12:09:00Z',
      type: 'schedule.run.completed',
      payload: {
        run_id: 'run-new',
        schedule_id: 'sched-1',
      },
    };
    state = reducer(state, sseEventReceived(envelope));
    const runs = selectRunsForSchedule({ schedules: state }, 'sched-1');
    expect(runs[0].id).toBe('run-new');
    expect(runs[0].status).toBe('success');
  });

  it('seeds stub-insert run rows with safe defaults so RunLog never renders NaN', () => {
    let state = seedState();
    state = {
      ...state,
      byAgent: { 'agent-1': [sampleSchedule()] } as Record<string, Schedule[]>,
    };
    const envelope: SSEEvent = {
      id: 'evt-7',
      ts: '2026-05-19T12:10:00Z',
      type: 'schedule.run.completed',
      payload: { run_id: 'run-stub', schedule_id: 'sched-1' },
    };
    state = reducer(state, sseEventReceived(envelope));
    const stub = selectRunsForSchedule({ schedules: state }, 'sched-1')[0];

    expect(stub.prompt_tokens).toBe(0);
    expect(stub.generated_tokens).toBe(0);
    expect(stub.prompt_tokens + stub.generated_tokens).toBe(0);
    expect(Number.isNaN(stub.prompt_tokens + stub.generated_tokens)).toBe(
      false,
    );
    expect(stub.trigger_source).toBe('cron');
    expect(stub.output_truncated).toBe(false);
    expect(stub.scheduled_for).toBe('2026-05-19T12:10:00Z');
    expect(stub.started_at).toBe('2026-05-19T12:10:00Z');
    expect(stub.finished_at).toBe('2026-05-19T12:10:00Z');
    expect(stub.status).toBe('success');
    expect(stub.error).toBeNull();
    expect(stub.error_type).toBeNull();
    // Agentless schedules carry agent_id=null (migration 0011); the stub
    // must mirror that — the empty-string sentinel would fail any
    // type-guarded select on the agent record downstream.
    expect(stub.agent_id).toBeNull();
  });

  it('stub-insert seeds defaults for failed runs too', () => {
    let state = seedState();
    state = {
      ...state,
      byAgent: { 'agent-1': [sampleSchedule()] } as Record<string, Schedule[]>,
    };
    const envelope: SSEEvent = {
      id: 'evt-8',
      ts: '2026-05-19T12:11:00Z',
      type: 'schedule.run.failed',
      payload: {
        run_id: 'run-stub-failed',
        schedule_id: 'sched-1',
        error_type: 'agent_error',
        error: 'boom',
      },
    };
    state = reducer(state, sseEventReceived(envelope));
    const stub = selectRunsForSchedule({ schedules: state }, 'sched-1')[0];
    expect(stub.status).toBe('failed');
    expect(stub.error).toBe('boom');
    expect(stub.error_type).toBe('agent_error');
    expect(stub.prompt_tokens).toBe(0);
    expect(stub.generated_tokens).toBe(0);
    expect(stub.trigger_source).toBe('cron');
  });
});

describe('selectSchedulesForAgent', () => {
  it('returns a stable empty list for an agent that has not loaded', () => {
    // A fresh [] per call re-runs every effect that depends on the list.
    const state = { schedules: reducer(undefined, { type: '@@init' }) };
    expect(selectSchedulesForAgent(state, 'missing')).toBe(
      selectSchedulesForAgent(state, 'missing'),
    );
  });
});

describe('loadRunsForSchedule paging', () => {
  const wrap = (schedules: SchedulesState) => ({ schedules });
  const fulfilled = (
    runs: ScheduleRun[],
    offset: number,
    limit = RUNS_PAGE_SIZE,
  ) => ({
    type: loadRunsForSchedule.fulfilled.type,
    payload: { scheduleId: 'sched-1', runs, offset, limit },
  });
  const runs = (from: number, n: number) =>
    Array.from({ length: n }, (_, i) => sampleRun({ id: `run-${from + i}` }));

  it('the first page replaces the list; a full page is not the end', () => {
    const state = reducer(undefined, fulfilled(runs(0, RUNS_PAGE_SIZE), 0));
    expect(state.runsBySchedule['sched-1']).toHaveLength(RUNS_PAGE_SIZE);
    expect(selectRunsEnd(wrap(state), 'sched-1')).toBe(false);
  });

  it('an older page appends, skipping runs already listed', () => {
    let state = reducer(undefined, fulfilled(runs(0, RUNS_PAGE_SIZE), 0));
    // A run that arrived over SSE shifted the window by one.
    state = reducer(
      state,
      fulfilled(runs(RUNS_PAGE_SIZE - 1, 10), RUNS_PAGE_SIZE),
    );
    const ids = state.runsBySchedule['sched-1'].map((r) => r.id);
    expect(ids).toHaveLength(RUNS_PAGE_SIZE + 9);
    expect(new Set(ids).size).toBe(ids.length);
    // Shorter than a page: there are no older runs.
    expect(selectRunsEnd(wrap(state), 'sched-1')).toBe(true);
  });
});

// A refused delete rejects, so the row stays and the confirm shows the error.
describe('deleteSchedule', () => {
  const run = (result: unknown) => {
    service.remove.mockResolvedValue(result);
    const dispatch = vi.fn();
    return deleteSchedule({ id: 'sched-1', token: null })(
      dispatch,
      () => ({}),
      undefined,
    );
  };

  it('fulfils with the id when the server deletes it', async () => {
    const action = await run({ success: true });
    expect(action.type).toBe(deleteSchedule.fulfilled.type);
    expect(action.payload).toBe('sched-1');
  });

  it('rejects when the server refuses the delete', async () => {
    const action = await run({ success: false, error: 'Not allowed' });
    expect(action.type).toBe(deleteSchedule.rejected.type);
  });
});

describe('schedulesSlice cross-agent list', () => {
  const seedAll = (): SchedulesState => {
    const state = seedWithSchedule();
    return reducer(
      state,
      loadAllSchedules.fulfilled(
        [
          { ...sampleSchedule(), agent_name: 'Deal Desk' },
          {
            ...sampleSchedule({ id: 'sched-2', agent_id: null }),
            origin_conversation_name: 'QBR prep',
          },
        ],
        'req',
        { token: null },
      ),
    );
  };

  it('stores the loaded list', () => {
    const state = seedAll();
    expect(selectAllSchedules({ schedules: state })?.map((s) => s.id)).toEqual([
      'sched-1',
      'sched-2',
    ]);
  });

  it('keeps the names when a mutation answers with a bare schedule', () => {
    const state = reducer(
      seedAll(),
      setSchedulePaused.fulfilled(sampleSchedule({ status: 'paused' }), 'req', {
        id: 'sched-1',
        action: 'pause',
        token: null,
      }),
    );
    const row = state.all?.find((s) => s.id === 'sched-1');
    expect(row?.status).toBe('paused');
    expect(row?.agent_name).toBe('Deal Desk');
    expect(state.byAgent['agent-1'][0].status).toBe('paused');
  });

  it('updates an agentless schedule, which has no per-agent list', () => {
    const state = reducer(
      seedAll(),
      setSchedulePaused.fulfilled(
        sampleSchedule({ id: 'sched-2', agent_id: null, status: 'paused' }),
        'req',
        { id: 'sched-2', action: 'pause', token: null },
      ),
    );
    expect(state.all?.find((s) => s.id === 'sched-2')?.status).toBe('paused');
  });

  it('applies SSE status changes to the cross-agent list', () => {
    const state = reducer(
      seedAll(),
      sseEventReceived({
        id: 'evt-9',
        type: 'schedule.autopaused',
        payload: { schedule_id: 'sched-2' },
      } as SSEEvent),
    );
    expect(state.all?.find((s) => s.id === 'sched-2')?.status).toBe('paused');
  });

  describe('while the list is loading', () => {
    const loading = () =>
      reducer(
        seedWithSchedule(),
        loadAllSchedules.pending('load', { token: null }),
      );
    const answer = (requestId = 'load') =>
      loadAllSchedules.fulfilled(
        [{ ...sampleSchedule(), agent_name: 'Deal Desk' }],
        requestId,
        { token: null },
      );

    it('keeps a schedule created meanwhile, which its answer predates', () => {
      let state = reducer(
        loading(),
        createSchedule.fulfilled(sampleSchedule({ id: 'sched-new' }), 'c', {
          agentId: 'agent-1',
          token: null,
        } as never),
      );
      state = reducer(state, answer());
      expect(state.all?.map((s) => s.id)).toEqual(['sched-new', 'sched-1']);
    });

    it('keeps a schedule deleted meanwhile deleted', () => {
      let state = reducer(
        loading(),
        deleteSchedule.fulfilled('sched-1', 'd', {
          id: 'sched-1',
          token: null,
        }),
      );
      state = reducer(state, answer());
      expect(state.all).toEqual([]);
    });

    it('drops a load sent before a reset', () => {
      let state = reducer(loading(), resetSchedules());
      state = reducer(state, answer());
      expect(state.all).toBeNull();
    });

    it('applies only the latest load', () => {
      let state = reducer(
        loading(),
        loadAllSchedules.pending('newer', { token: null }),
      );
      state = reducer(
        state,
        loadAllSchedules.fulfilled([], 'newer', { token: null }),
      );
      state = reducer(state, answer('load'));
      expect(state.all).toEqual([]);
    });
  });

  it('drops a deleted schedule from the cross-agent list', () => {
    const state = reducer(
      seedAll(),
      deleteSchedule.fulfilled('sched-2', 'req', {
        id: 'sched-2',
        token: null,
      }),
    );
    expect(state.all?.map((s) => s.id)).toEqual(['sched-1']);
  });
});
