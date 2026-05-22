import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';

import schedulesService from '../../api/services/schedulesService';
import {
  sseEventReceived,
  type SSEEvent,
} from '../../notifications/notificationsSlice';
import type {
  Schedule,
  ScheduleCreatePayload,
  ScheduleRun,
  ScheduleUpdatePayload,
} from '../types/schedule';

export type SchedulesState = {
  byAgent: Record<string, Schedule[]>;
  runsBySchedule: Record<string, ScheduleRun[]>;
  loading: boolean;
  error: string | null;
};

const initialState: SchedulesState = {
  byAgent: {},
  runsBySchedule: {},
  loading: false,
  error: null,
};

export const loadSchedulesForAgent = createAsyncThunk<
  { agentId: string; schedules: Schedule[] },
  { agentId: string; token: string | null }
>('schedules/loadForAgent', async ({ agentId, token }) => {
  const r = await schedulesService.listForAgent(agentId, token);
  return { agentId, schedules: r.schedules };
});

export const createSchedule = createAsyncThunk<
  Schedule,
  {
    agentId: string;
    payload: ScheduleCreatePayload;
    token: string | null;
  }
>('schedules/create', async ({ agentId, payload, token }) => {
  const r = await schedulesService.create(agentId, payload, token);
  return r.schedule;
});

export const updateSchedule = createAsyncThunk<
  Schedule,
  {
    id: string;
    payload: ScheduleUpdatePayload;
    token: string | null;
  }
>('schedules/update', async ({ id, payload, token }) => {
  const r = await schedulesService.update(id, payload, token);
  return r.schedule;
});

export const setSchedulePaused = createAsyncThunk<
  Schedule,
  { id: string; action: 'pause' | 'resume'; token: string | null }
>('schedules/setPaused', async ({ id, action, token }) => {
  const r = await schedulesService.setPaused(id, action, token);
  return r.schedule;
});

export const deleteSchedule = createAsyncThunk<
  string,
  { id: string; token: string | null }
>('schedules/delete', async ({ id, token }) => {
  await schedulesService.remove(id, token);
  return id;
});

export const runScheduleNow = createAsyncThunk<
  { scheduleId: string; run: ScheduleRun },
  { id: string; token: string | null }
>('schedules/runNow', async ({ id, token }) => {
  const r = await schedulesService.runNow(id, token);
  return { scheduleId: id, run: r.run };
});

export const loadRunsForSchedule = createAsyncThunk<
  { scheduleId: string; runs: ScheduleRun[] },
  {
    id: string;
    limit?: number;
    offset?: number;
    token: string | null;
  }
>('schedules/loadRuns', async ({ id, limit, offset, token }) => {
  const r = await schedulesService.listRuns(id, limit, offset, token);
  return { scheduleId: id, runs: r.runs };
});

const upsert = (list: Schedule[], next: Schedule): Schedule[] => {
  const idx = list.findIndex((s) => s.id === next.id);
  if (idx === -1) return [next, ...list];
  const copy = list.slice();
  copy[idx] = next;
  return copy;
};

const removeFrom = (list: Schedule[], id: string): Schedule[] =>
  list.filter((s) => s.id !== id);

// SSE delivers a partial schedule_run; stub the missing fields so RunLog
// renders cleanly until the next list refetch.
const stubRunDefaults = (
  scheduleId: string,
  ts: string | undefined,
): Omit<ScheduleRun, 'id' | 'status'> => {
  const now = ts ?? new Date().toISOString();
  return {
    schedule_id: scheduleId,
    user_id: '',
    agent_id: null,
    scheduled_for: now,
    trigger_source: 'cron',
    started_at: now,
    finished_at: now,
    output: null,
    output_truncated: false,
    error: null,
    error_type: null,
    prompt_tokens: 0,
    generated_tokens: 0,
    conversation_id: null,
    message_id: null,
    celery_task_id: null,
    created_at: now,
    updated_at: now,
  };
};

const upsertRunDelta = (
  state: SchedulesState,
  scheduleId: string,
  delta: Partial<ScheduleRun> & { id: string; status: ScheduleRun['status'] },
  ts: string | undefined,
): void => {
  const list = state.runsBySchedule[scheduleId] ?? [];
  const idx = list.findIndex((r) => r.id === delta.id);
  if (idx === -1) {
    const stub: ScheduleRun = { ...stubRunDefaults(scheduleId, ts), ...delta };
    state.runsBySchedule[scheduleId] = [stub, ...list];
    return;
  }
  list[idx] = { ...list[idx], ...delta };
};

const findAgentForSchedule = (
  state: SchedulesState,
  scheduleId: string,
): { agentId: string; schedule: Schedule } | null => {
  for (const agentId of Object.keys(state.byAgent)) {
    const list = state.byAgent[agentId];
    const schedule = list.find((s) => s.id === scheduleId);
    if (schedule) return { agentId, schedule };
  }
  return null;
};

const schedulesSlice = createSlice({
  name: 'schedules',
  initialState,
  reducers: {
    applyEvent: (
      state,
      action: PayloadAction<{
        type: string;
        scheduleId: string;
        run?: ScheduleRun;
      }>,
    ) => {
      const { scheduleId, run } = action.payload;
      if (run) {
        const existing = state.runsBySchedule[scheduleId] ?? [];
        const idx = existing.findIndex((r) => r.id === run.id);
        if (idx === -1) {
          state.runsBySchedule[scheduleId] = [run, ...existing];
        } else {
          existing[idx] = run;
        }
      }
    },
    resetSchedules: () => initialState,
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadSchedulesForAgent.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(loadSchedulesForAgent.fulfilled, (state, action) => {
        state.byAgent[action.payload.agentId] = action.payload.schedules;
        state.loading = false;
      })
      .addCase(loadSchedulesForAgent.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'failed to load schedules';
      })
      // Agentless schedules (``agent_id === null``) skip the byAgent cache —
      // they have no Schedules tab home. The inline ⏰ card is the only UI.
      .addCase(createSchedule.fulfilled, (state, action) => {
        const next = action.payload;
        if (!next.agent_id) return;
        const list = state.byAgent[next.agent_id] ?? [];
        state.byAgent[next.agent_id] = upsert(list, next);
      })
      .addCase(updateSchedule.fulfilled, (state, action) => {
        const next = action.payload;
        if (!next.agent_id) return;
        const list = state.byAgent[next.agent_id] ?? [];
        state.byAgent[next.agent_id] = upsert(list, next);
      })
      .addCase(setSchedulePaused.fulfilled, (state, action) => {
        const next = action.payload;
        if (!next.agent_id) return;
        const list = state.byAgent[next.agent_id] ?? [];
        state.byAgent[next.agent_id] = upsert(list, next);
      })
      .addCase(deleteSchedule.fulfilled, (state, action) => {
        const id = action.payload;
        Object.keys(state.byAgent).forEach((agentId) => {
          state.byAgent[agentId] = removeFrom(state.byAgent[agentId], id);
        });
        delete state.runsBySchedule[id];
      })
      .addCase(runScheduleNow.fulfilled, (state, action) => {
        const { scheduleId, run } = action.payload;
        const list = state.runsBySchedule[scheduleId] ?? [];
        state.runsBySchedule[scheduleId] = [run, ...list];
      })
      .addCase(loadRunsForSchedule.fulfilled, (state, action) => {
        const { scheduleId, runs } = action.payload;
        state.runsBySchedule[scheduleId] = runs;
      })
      // SSE envelopes from scheduler_worker.py; unknown shapes are no-ops.
      .addMatcher(
        (action) => action.type === sseEventReceived.type,
        (state, action: PayloadAction<SSEEvent>) => {
          const envelope = action.payload;
          const payload = (envelope.payload || {}) as Record<string, unknown>;
          const scheduleId = (payload.schedule_id as string | undefined) || '';
          if (!scheduleId) return;
          switch (envelope.type) {
            case 'schedule.run.completed':
            case 'schedule.run.failed': {
              const runId = (payload.run_id as string | undefined) || '';
              if (runId) {
                const status =
                  envelope.type === 'schedule.run.completed'
                    ? 'success'
                    : 'failed';
                upsertRunDelta(
                  state,
                  scheduleId,
                  {
                    id: runId,
                    schedule_id: scheduleId,
                    status: status as ScheduleRun['status'],
                    error_type:
                      (payload.error_type as ScheduleRun['error_type']) ?? null,
                    error: (payload.error as string | undefined) ?? null,
                    finished_at: envelope.ts ?? null,
                  },
                  envelope.ts,
                );
              }
              const found = findAgentForSchedule(state, scheduleId);
              if (found && envelope.ts) {
                const next: Schedule = {
                  ...found.schedule,
                  last_run_at: envelope.ts,
                };
                state.byAgent[found.agentId] = upsert(
                  state.byAgent[found.agentId],
                  next,
                );
              }
              break;
            }
            case 'schedule.autopaused': {
              const found = findAgentForSchedule(state, scheduleId);
              if (found) {
                const next: Schedule = { ...found.schedule, status: 'paused' };
                state.byAgent[found.agentId] = upsert(
                  state.byAgent[found.agentId],
                  next,
                );
              }
              break;
            }
            case 'schedule.message.appended':
              // Handled by conversationSlice; nothing to mutate here.
              break;
            default:
              break;
          }
        },
      );
  },
});

export const { applyEvent, resetSchedules } = schedulesSlice.actions;
export default schedulesSlice.reducer;

export const selectSchedulesForAgent = (
  state: { schedules: SchedulesState },
  agentId: string,
): Schedule[] => state.schedules.byAgent[agentId] ?? [];

export const selectRunsForSchedule = (
  state: { schedules: SchedulesState },
  scheduleId: string,
): ScheduleRun[] => state.schedules.runsBySchedule[scheduleId] ?? [];
