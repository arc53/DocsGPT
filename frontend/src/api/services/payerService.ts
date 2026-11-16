import type { TFunction } from 'i18next';

import type { Schedule } from '../../agents/types/schedule';
import { filenameFromContentDisposition } from '../../components/artifactViewUtils';
import type {
  OutsideAccess,
  OutsideAccessKind,
  PausedFor,
  PersonRef,
  SchedulePayerFields,
} from '../../payer/types';
import apiClient from '../client';
import endpoints from '../endpoints';

/** One budget of a quota bucket; `limit` null is unlimited. */
export type QuotaBudget = { limit: number | null; used: number };

/** A limited bucket of the caller's quota (`all`, `direct`, `agent`). */
export type QuotaBucket = {
  bucket: string;
  tokens: QuotaBudget;
  cost: QuotaBudget;
  resets_at: string;
};

/** The budget the caller has used most of, from 80%. */
export type QuotaNotice = {
  level: 'near' | 'reached';
  /** Whole percent, at most 100. */
  percent: number;
  bucket: string;
  budget: 'tokens' | 'cost';
  resets_at: string;
};

/** One part of this period's use, as the Settings meter shows it. */
export type QuotaPartKind = 'chat' | 'schedule' | 'published' | 'other';
export type QuotaPart = { kind: QuotaPartKind; tokens: number; cost: number };

/** What the caller pays for that their used-up allowance stopped. */
export type QuotaPaused = {
  schedules: number;
  published: { agent_id: string; name: string; access: OutsideAccessKind[] }[];
};

/**
 * `GET /api/user/quota`. An unlimited caller has no buckets and `notice`,
 * `parts` and `paused` null; `paused` is set only while `notice` is reached.
 */
export type QuotaResponse = {
  success?: boolean;
  period?: 'day' | 'week' | 'month' | string;
  buckets: QuotaBucket[];
  notice: QuotaNotice | null;
  parts: QuotaPart[] | null;
  paused: QuotaPaused | null;
};

type Amount = { tokens: number; cost: number };

/** A paused item in a team's Usage report. */
export type TeamUsagePausedItem =
  | {
      type: 'schedule';
      id: string;
      name?: string | null;
      agent: { id: string; name?: string | null } | null;
      paused_for: PausedFor;
      paid_by?: PersonRef | null;
    }
  | {
      type: 'outside_access';
      /** The agent's id. */
      id: string;
      agent: { id: string; name?: string | null };
      access: OutsideAccessKind[];
      paused_for: PausedFor;
      paid_by?: PersonRef | null;
    }
  | {
      type: 'source_sync';
      id: string;
      name?: string | null;
      paused_for: { reason: string; since?: string | null };
    };

/** `GET /api/teams/<id>/usage`: a report, never a limit. */
export type TeamUsage = {
  success?: boolean;
  period: {
    kind: 'day' | 'week' | 'month' | string;
    start: string;
    end: string;
    current: boolean;
  };
  totals: Amount & { people: number };
  split: { chats: Amount; runs: Amount };
  /** `role` null: the person left the team. */
  by_person: (Amount & {
    user_id: string;
    label?: string | null;
    role: string | null;
  })[];
  /** A deleted agent drops out; its spend stays in the totals. */
  by_agent: (Amount & {
    agent_id: string;
    name?: string | null;
    requests: number;
    people: number;
    limit_on: boolean;
    published: { paid_by: PersonRef | null } | null;
    /** The team no longer owns it: no name, limit or payer, only what it spent here. */
    moved_out: boolean;
  })[];
  paused: TeamUsagePausedItem[];
};

export type TakeOverScheduleResult = {
  schedule: Schedule & SchedulePayerFields;
  /** False when the caller already paid: nothing was written. */
  changed: boolean;
};

export type TakeOverOutsideAccessResult = {
  outside_access: OutsideAccess;
  changed: boolean;
};

/**
 * A non-2xx answer from a payer call: `code` is the server's `error` code
 * (`max_schedules`, `workspace_role_required`…), `message` its own text.
 */
export class PayerApiError extends Error {
  status: number;
  code?: string;
  body?: Record<string, unknown>;

  constructor(
    status: number,
    message: string,
    code?: string,
    body?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'PayerApiError';
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

/** The app's words for each refusal a Take over or a report can answer. */
export const PAYER_ERROR_KEYS: Readonly<Record<string, string>> = {
  agent_not_found: 'payer.common.errors.notFound',
  max_schedules: 'payer.common.errors.maxSchedules',
  no_outside_access: 'payer.common.errors.noOutsideAccess',
  not_available_to_tokens: 'payer.common.errors.notAvailableToTokens',
  schedule_not_found: 'payer.common.errors.notFound',
  take_over_team_only: 'payer.common.errors.teamOnly',
  team_not_found: 'payer.common.errors.notFound',
  workspace_role_required: 'payer.common.errors.roleRequired',
};

/**
 * What to say about a failed payer call: the app's words for a known code,
 * else `fallback` (the server's text is English and may be technical).
 *
 * Args:
 *   t: The translate function.
 *   error: What the call threw.
 *   fallback: The text for anything else (a network failure).
 *
 * Returns:
 *   The message to show.
 */
export function payerErrorMessage(
  t: TFunction | ((key: string) => string),
  error: unknown,
  fallback: string,
): string {
  const e = error as { name?: unknown; code?: unknown } | null;
  if (!e || typeof e !== 'object' || e.name !== 'PayerApiError')
    return fallback;
  const key = typeof e.code === 'string' ? PAYER_ERROR_KEYS[e.code] : null;
  return key ? (t as (key: string) => string)(key) : fallback;
}

const refusal = async (r: Response): Promise<PayerApiError> => {
  let message = `Request failed (${r.status})`;
  let code: string | undefined;
  let body: Record<string, unknown> | undefined;
  try {
    const parsed = await r.json();
    if (parsed && typeof parsed === 'object') body = parsed;
    if (typeof parsed?.error === 'string' && parsed.error) code = parsed.error;
    if (typeof parsed?.message === 'string' && parsed.message)
      message = parsed.message;
  } catch {
    // Not JSON (a proxy's page, a bare 404): keep the generic message.
  }
  return new PayerApiError(r.status, message, code, body);
};

const json = async <T>(r: Response): Promise<T> => {
  if (!r.ok) throw await refusal(r);
  return (await r.json()) as T;
};

const today = (): string => new Date().toISOString().slice(0, 10);

const payerService = {
  /** The caller's quota: buckets, the 80% notice, the meter's parts, what stopped. */
  getQuota: async (token: string | null): Promise<QuotaResponse> => {
    const body = await json<Partial<QuotaResponse>>(
      await apiClient.get(endpoints.USER.QUOTA, token),
    );
    return {
      ...body,
      buckets: Array.isArray(body.buckets) ? body.buckets : [],
      notice: body.notice ?? null,
      parts: Array.isArray(body.parts) ? body.parts : null,
      paused: body.paused ?? null,
    };
  },

  /** Makes the caller the payer of a team agent's schedule. */
  takeOverSchedule: async (
    scheduleId: string,
    token: string | null,
  ): Promise<TakeOverScheduleResult> => {
    const body = await json<TakeOverScheduleResult>(
      await apiClient.post(
        endpoints.USER.SCHEDULE_TAKE_OVER(scheduleId),
        {},
        token,
      ),
    );
    return { schedule: body.schedule, changed: body.changed };
  },

  /** Makes the caller the payer of a team agent's key, link and webhook. */
  takeOverOutsideAccess: async (
    agentId: string,
    token: string | null,
  ): Promise<TakeOverOutsideAccessResult> => {
    const body = await json<TakeOverOutsideAccessResult>(
      await apiClient.post(
        endpoints.USER.AGENT_OUTSIDE_ACCESS_TAKE_OVER(agentId),
        {},
        token,
      ),
    );
    return { outside_access: body.outside_access, changed: body.changed };
  },

  /** A team's Usage report for this period or the one before. */
  getTeamUsage: async (
    teamId: string,
    period: 'current' | 'previous',
    token: string | null,
  ): Promise<TeamUsage> =>
    json<TeamUsage>(
      await apiClient.get(endpoints.USER.TEAM_USAGE(teamId, period), token),
    ),

  /**
   * Every chat of a team workspace as one NDJSON file. The name is the
   * server's (`Content-Disposition`); when the browser can't read that header
   * (a cross-origin API that doesn't expose it) the app names it.
   */
  exportTeamChats: async (
    teamId: string,
    token: string | null,
  ): Promise<{ blob: Blob; filename: string }> => {
    const r: Response = await apiClient.get(
      endpoints.USER.TEAM_CHATS_EXPORT(teamId),
      token,
    );
    if (!r.ok) throw await refusal(r);
    const filename =
      filenameFromContentDisposition(r.headers.get('Content-Disposition')) ||
      `docsgpt-team-chats-${today()}.ndjson`;
    return { blob: await r.blob(), filename };
  },
};

export default payerService;
