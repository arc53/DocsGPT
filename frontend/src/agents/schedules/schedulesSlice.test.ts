import { describe, expect, it } from 'vitest';

import {
  sseEventReceived,
  type SSEEvent,
} from '../../notifications/notificationsSlice';
import type { Schedule, ScheduleRun } from '../types/schedule';
import reducer, {
  applyEvent,
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
