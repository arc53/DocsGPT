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
  ScheduleStatus,
  ScheduleUpdatePayload,
  UserSchedule,
} from '../types/schedule';

/** Runs per request; a shorter page means the log has reached its oldest run. */
export const RUNS_PAGE_SIZE = 50;

export type SchedulesState = {
  byAgent: Record<string, Schedule[]>;
  /** The caller's schedules across agents (Activity › Schedules); null until loaded. */
  all: UserSchedule[] | null;
  allLoading: boolean;
  allError: boolean;
  /** The latest cross-agent load: only its answer is applied. */
  allRequestId: string | null;
  /**
   * The token `all` was loaded with. A load with another one (an account
   * switch without a page reload) clears it, so a failed load can't leave
   * the last account's schedules on screen.
   */
  allToken: string | null;
  /**
   * Schedules saved or deleted while that load was out. Its answer was read
   * before them, so they are applied on top of it.
   */
  allChangedSinceRequest: { saved: Schedule[]; deleted: string[] };
  runsBySchedule: Record<string, ScheduleRun[]>;
  /** True once a schedule's oldest run is loaded. */
  runsEndBySchedule: Record<string, boolean>;
  loading: boolean;
  error: string | null;
};

const initialState: SchedulesState = {
  byAgent: {},
  all: null,
  allLoading: false,
  allError: false,
  allRequestId: null,
  allToken: null,
  allChangedSinceRequest: { saved: [], deleted: [] },
  runsBySchedule: {},
  runsEndBySchedule: {},
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

export const loadAllSchedules = createAsyncThunk<
  UserSchedule[],
  { token: string | null }
>('schedules/loadAll', async ({ token }) => {
  const r = await schedulesService.listAll(token);
  return r.schedules;
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
  const result = await schedulesService.remove(id, token);
  // A refused delete answers `success: false`; reject so the row stays.
  if (result?.success === false) throw new Error('Failed to delete schedule');
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
  { scheduleId: string; runs: ScheduleRun[]; offset: number; limit: number },
  {
    id: string;
    limit?: number;
    offset?: number;
    token: string | null;
  }
>('schedules/loadRuns', async ({ id, limit, offset, token }) => {
  const pageLimit = limit ?? RUNS_PAGE_SIZE;
  const pageOffset = offset ?? 0;
  const r = await schedulesService.listRuns(id, pageLimit, pageOffset, token);
  return {
    scheduleId: id,
    runs: r.runs,
    offset: pageOffset,
    limit: pageLimit,
  };
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

/**
 * Puts a schedule's new state in every list that holds it. A row of the
 * cross-agent list keeps its names, which a mutation response doesn't carry.
 */
const applyToLists = (state: SchedulesState, next: Schedule): void => {
  if (next.agent_id) {
    state.byAgent[next.agent_id] = upsert(
      state.byAgent[next.agent_id] ?? [],
      next,
    );
  }
  if (state.allLoading) state.allChangedSinceRequest.saved.push(next);
  upsertInAll(state, next);
};

/** Whether a cross-agent load's answer is the latest one's (or none is tracked). */
const isLatestAll = (state: SchedulesState, requestId: string): boolean =>
  state.allRequestId === null || state.allRequestId === requestId;

/** Puts a schedule in the cross-agent list, keeping a listed row's names. */
const upsertInAll = (state: SchedulesState, next: Schedule): void => {
  if (!state.all) return;
  const idx = state.all.findIndex((s) => s.id === next.id);
  if (idx === -1) state.all = [next, ...state.all];
  else state.all[idx] = { ...state.all[idx], ...next };
};

/** Changes fields of a schedule wherever it is listed (an SSE update). */
const patchSchedule = (
  state: SchedulesState,
  scheduleId: string,
  patch: Partial<Schedule>,
): void => {
  const found = findAgentForSchedule(state, scheduleId);
  if (found) {
    state.byAgent[found.agentId] = upsert(state.byAgent[found.agentId], {
      ...found.schedule,
      ...patch,
    });
  }
  const idx = state.all?.findIndex((s) => s.id === scheduleId) ?? -1;
  if (state.all && idx !== -1) state.all[idx] = { ...state.all[idx], ...patch };
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
    // An answer to a load sent before (no request id matches this) is the
    // last account's.
    resetSchedules: () => ({ ...initialState, allRequestId: 'reset' }),
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
      .addCase(loadAllSchedules.pending, (state, action) => {
        if (action.meta.arg.token !== state.allToken) state.all = null;
        state.allToken = action.meta.arg.token;
        state.allLoading = true;
        state.allError = false;
        state.allRequestId = action.meta.requestId;
        state.allChangedSinceRequest = { saved: [], deleted: [] };
      })
      .addCase(loadAllSchedules.fulfilled, (state, action) => {
        if (!isLatestAll(state, action.meta.requestId)) return;
        const { saved, deleted } = state.allChangedSinceRequest;
        const gone = new Set(deleted);
        state.all = action.payload.filter((s) => !gone.has(s.id));
        saved
          .filter((s) => !gone.has(s.id))
          .forEach((s) => upsertInAll(state, s));
        state.allChangedSinceRequest = { saved: [], deleted: [] };
        state.allLoading = false;
      })
      .addCase(loadAllSchedules.rejected, (state, action) => {
        if (!isLatestAll(state, action.meta.requestId)) return;
        state.allLoading = false;
        state.allError = true;
      })
      // Agentless schedules (``agent_id === null``) have no byAgent home:
      // they are listed only in the cross-agent list.
      .addCase(createSchedule.fulfilled, (state, action) => {
        applyToLists(state, action.payload);
      })
      .addCase(updateSchedule.fulfilled, (state, action) => {
        applyToLists(state, action.payload);
      })
      .addCase(setSchedulePaused.fulfilled, (state, action) => {
        applyToLists(state, action.payload);
      })
      .addCase(deleteSchedule.fulfilled, (state, action) => {
        const id = action.payload;
        Object.keys(state.byAgent).forEach((agentId) => {
          state.byAgent[agentId] = removeFrom(state.byAgent[agentId], id);
        });
        if (state.allLoading) state.allChangedSinceRequest.deleted.push(id);
        if (state.all) state.all = state.all.filter((s) => s.id !== id);
        delete state.runsBySchedule[id];
        delete state.runsEndBySchedule[id];
      })
      .addCase(runScheduleNow.fulfilled, (state, action) => {
        const { scheduleId, run } = action.payload;
        const list = state.runsBySchedule[scheduleId] ?? [];
        state.runsBySchedule[scheduleId] = [run, ...list];
      })
      .addCase(loadRunsForSchedule.fulfilled, (state, action) => {
        const { scheduleId, runs, offset, limit } = action.payload;
        if (offset === 0) {
          state.runsBySchedule[scheduleId] = runs;
        } else {
          // Runs that arrived over SSE shift the window, so an older page
          // can repeat the last rows already listed.
          const list = state.runsBySchedule[scheduleId] ?? [];
          const seen = new Set(list.map((run) => run.id));
          state.runsBySchedule[scheduleId] = [
            ...list,
            ...runs.filter((run) => !seen.has(run.id)),
          ];
        }
        state.runsEndBySchedule[scheduleId] = runs.length < limit;
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
              if (envelope.ts) {
                patchSchedule(state, scheduleId, { last_run_at: envelope.ts });
              }
              break;
            }
            case 'schedule.autopaused':
              patchSchedule(state, scheduleId, { status: 'paused' });
              break;
            // Schedule-level status transitions. These revoke a stale
            // ``schedule.autopaused`` (resumed/cancelled) or surface a
            // reconciler/once-schedule finish (completed) that the run
            // deltas above don't carry — otherwise the schedule reads
            // 'active' (or 'paused') until a manual refresh.
            case 'schedule.resumed':
            case 'schedule.cancelled':
            case 'schedule.completed': {
              const status: ScheduleStatus =
                envelope.type === 'schedule.resumed'
                  ? 'active'
                  : envelope.type === 'schedule.cancelled'
                    ? 'cancelled'
                    : 'completed';
              patchSchedule(state, scheduleId, { status });
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

// Shared fallbacks: a fresh [] per call would change identity on every render
// and re-run any effect that depends on the selected list.
const NO_SCHEDULES: Schedule[] = [];
const NO_RUNS: ScheduleRun[] = [];

export const selectSchedulesForAgent = (
  state: { schedules: SchedulesState },
  agentId: string,
): Schedule[] => state.schedules.byAgent[agentId] ?? NO_SCHEDULES;

/** The cross-agent list (null until loaded) and its load state. */
export const selectAllSchedules = (state: {
  schedules: SchedulesState;
}): UserSchedule[] | null => state.schedules.all;

export const selectAllSchedulesLoading = (state: {
  schedules: SchedulesState;
}): boolean => state.schedules.allLoading;

export const selectAllSchedulesError = (state: {
  schedules: SchedulesState;
}): boolean => state.schedules.allError;

export const selectRunsForSchedule = (
  state: { schedules: SchedulesState },
  scheduleId: string,
): ScheduleRun[] => state.schedules.runsBySchedule[scheduleId] ?? NO_RUNS;

/** Whether a schedule's run log has loaded its oldest run. */
export const selectRunsEnd = (
  state: { schedules: SchedulesState },
  scheduleId: string,
): boolean => state.schedules.runsEndBySchedule?.[scheduleId] ?? false;
