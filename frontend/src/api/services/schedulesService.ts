import apiClient from '../client';
import endpoints from '../endpoints';
import type {
  ScheduleCreatePayload,
  ScheduleListResponse,
  ScheduleResponse,
  ScheduleRunListResponse,
  ScheduleRunResponse,
  ScheduleStats,
  ScheduleUpdatePayload,
} from '../../agents/types/schedule';

const json = async (response: Response | unknown) => {
  const r = response as Response;
  if (!('json' in r) || typeof r.json !== 'function') return r as unknown;
  return r.json();
};

const jsonOrUndefined = async (response: Response | unknown) => {
  try {
    return (await json(response)) as { message?: string } | undefined;
  } catch {
    // A proxy's HTML error page (a 502, say) is not JSON.
    return undefined;
  }
};

/**
 * The body of a create or update, or an Error carrying the server's
 * `message` when it refused the change (a bad run time, a finished task).
 * Without one (an error page, a body that is not JSON) the Error has no
 * message, so the form shows only its own "couldn't save" text.
 */
const savedOrThrow = async (response: Response | unknown) => {
  const r = response as Response;
  if (r && r.ok === false) {
    const body = await jsonOrUndefined(r);
    throw new Error(body?.message || '');
  }
  const body = await jsonOrUndefined(r);
  if (body === undefined) throw new Error('');
  return body;
};

const schedulesService = {
  listForAgent: async (
    agentId: string,
    token: string | null,
  ): Promise<ScheduleListResponse> => {
    const r = await apiClient.get(
      endpoints.USER.AGENT_SCHEDULES(agentId),
      token,
    );
    return (await json(r)) as ScheduleListResponse;
  },

  statsForAgent: async (
    agentId: string,
    token: string | null,
    days = 30,
  ): Promise<ScheduleStats> => {
    const r = await apiClient.get(
      endpoints.USER.AGENT_SCHEDULE_STATS(agentId, days),
      token,
    );
    // The error body ({success: false, message}) is not stats: reject so the
    // caller shows "—" instead of empty totals.
    if (!(r as Response).ok) {
      throw new Error(`Schedule stats failed: ${(r as Response).status}`);
    }
    return (await json(r)) as ScheduleStats;
  },

  create: async (
    agentId: string,
    payload: ScheduleCreatePayload,
    token: string | null,
  ): Promise<ScheduleResponse> => {
    const r = await apiClient.post(
      endpoints.USER.AGENT_SCHEDULES(agentId),
      payload,
      token,
    );
    return (await savedOrThrow(r)) as ScheduleResponse;
  },

  get: async (id: string, token: string | null): Promise<ScheduleResponse> => {
    const r = await apiClient.get(endpoints.USER.SCHEDULE(id), token);
    return (await json(r)) as ScheduleResponse;
  },

  update: async (
    id: string,
    payload: ScheduleUpdatePayload,
    token: string | null,
  ): Promise<ScheduleResponse> => {
    const r = await apiClient.put(endpoints.USER.SCHEDULE(id), payload, token);
    return (await savedOrThrow(r)) as ScheduleResponse;
  },

  setPaused: async (
    id: string,
    action: 'pause' | 'resume',
    token: string | null,
  ): Promise<ScheduleResponse> => {
    const r = await apiClient.patch(
      endpoints.USER.SCHEDULE(id),
      { action },
      token,
    );
    return (await savedOrThrow(r)) as ScheduleResponse;
  },

  remove: async (
    id: string,
    token: string | null,
  ): Promise<{ success: boolean }> => {
    const r = await apiClient.delete(endpoints.USER.SCHEDULE(id), token);
    return (await json(r)) as { success: boolean };
  },

  runNow: async (
    id: string,
    token: string | null,
  ): Promise<ScheduleRunResponse> => {
    const r = await apiClient.post(
      endpoints.USER.SCHEDULE_RUN_NOW(id),
      {},
      token,
    );
    return (await savedOrThrow(r)) as ScheduleRunResponse;
  },

  listRuns: async (
    id: string,
    limit: number | undefined,
    offset: number | undefined,
    token: string | null,
  ): Promise<ScheduleRunListResponse> => {
    const r = await apiClient.get(
      endpoints.USER.SCHEDULE_RUNS(id, limit, offset),
      token,
    );
    return (await json(r)) as ScheduleRunListResponse;
  },

  getRun: async (
    id: string,
    runId: string,
    token: string | null,
  ): Promise<ScheduleRunResponse> => {
    const r = await apiClient.get(
      endpoints.USER.SCHEDULE_RUN(id, runId),
      token,
    );
    return (await json(r)) as ScheduleRunResponse;
  },
};

export default schedulesService;
