import apiClient from '../client';
import endpoints from '../endpoints';
import type {
  ScheduleCreatePayload,
  ScheduleListResponse,
  ScheduleResponse,
  ScheduleRunListResponse,
  ScheduleRunResponse,
  ScheduleUpdatePayload,
} from '../../agents/types/schedule';

const json = async (response: Response | unknown) => {
  const r = response as Response;
  if (!('json' in r) || typeof r.json !== 'function') return r as unknown;
  return r.json();
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
    return (await json(r)) as ScheduleResponse;
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
    return (await json(r)) as ScheduleResponse;
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
    return (await json(r)) as ScheduleResponse;
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
    return (await json(r)) as ScheduleRunResponse;
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
