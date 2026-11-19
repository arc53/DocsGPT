import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  setRequestWorkspace,
  WORKSPACE_HEADER,
} from '../../workspace/requestWorkspace';
import payerService, { PayerApiError, payerErrorMessage } from './payerService';

type Call = { url: string; init: RequestInit };
const calls: Call[] = [];
let answer: () => Response;

const json = (body: unknown, status = 200, headers = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });

beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve(answer());
    }),
  );
  setRequestWorkspace('t1', 1);
});

afterEach(() => {
  vi.unstubAllGlobals();
  setRequestWorkspace('personal', 0);
});

const header = (call: Call, name: string) =>
  (call.init.headers as Record<string, string>)[name];

describe('payerService', () => {
  it('reads the quota with its notice, parts and paused items', async () => {
    answer = () =>
      json({
        success: true,
        period: 'month',
        buckets: [],
        notice: { level: 'near', percent: 82 },
        parts: null,
        paused: null,
      });
    const quota = await payerService.getQuota('tok');
    expect(calls[0].url).toMatch(/\/api\/user\/quota$/);
    expect(header(calls[0], 'Authorization')).toBe('Bearer tok');
    expect(quota.notice?.percent).toBe(82);
  });

  it('takes over a schedule with a POST that names the workspace', async () => {
    answer = () =>
      json({ success: true, schedule: { id: 's1' }, changed: true });
    const result = await payerService.takeOverSchedule('s1', 'tok');
    expect(calls[0].url).toMatch(/\/api\/schedules\/s1\/take_over$/);
    expect(calls[0].init.method).toBe('POST');
    expect(header(calls[0], WORKSPACE_HEADER)).toBe('t1');
    expect(result).toEqual({ schedule: { id: 's1' }, changed: true });
  });

  it('takes over outside access', async () => {
    answer = () =>
      json({
        success: true,
        outside_access: { api_key: true, public_link: false, webhook: false },
        changed: false,
      });
    const result = await payerService.takeOverOutsideAccess('a1', 'tok');
    expect(calls[0].url).toMatch(
      /\/api\/agents\/a1\/outside_access\/take_over$/,
    );
    expect(result.changed).toBe(false);
  });

  it('rejects a refusal with its code', async () => {
    answer = () =>
      json(
        { success: false, error: 'max_schedules', message: 'Too many.' },
        429,
      );
    const error = await payerService
      .takeOverSchedule('s1', 'tok')
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(PayerApiError);
    expect((error as PayerApiError).code).toBe('max_schedules');
    expect((error as PayerApiError).status).toBe(429);
    const t = (key: string) => `t:${key}`;
    expect(payerErrorMessage(t, error, 'fallback')).toBe(
      't:payer.common.errors.maxSchedules',
    );
    expect(payerErrorMessage(t, new Error('x'), 'fallback')).toBe('fallback');
  });

  it('asks for the previous period of a team usage report', async () => {
    answer = () => json({ success: true, period: { kind: 'month' } });
    await payerService.getTeamUsage('t9', 'previous', 'tok');
    expect(calls[0].url).toMatch(/\/api\/teams\/t9\/usage\?period=previous$/);
  });

  it('exports chats as a file named by the server', async () => {
    answer = () =>
      new Response('{"type":"export"}\n', {
        status: 200,
        headers: {
          'Content-Type': 'application/x-ndjson',
          'Content-Disposition':
            'attachment; filename="docsgpt-ops-chats-2026-11-16.ndjson"',
        },
      });
    const { blob, filename } = await payerService.exportTeamChats('t9', 'tok');
    expect(calls[0].url).toMatch(/\/api\/teams\/t9\/chats\/export$/);
    expect(header(calls[0], WORKSPACE_HEADER)).toBe('t1');
    expect(filename).toBe('docsgpt-ops-chats-2026-11-16.ndjson');
    expect(await blob.text()).toBe('{"type":"export"}\n');
  });

  it('names the file itself when the header is not readable', async () => {
    answer = () => new Response('x', { status: 200 });
    const { filename } = await payerService.exportTeamChats('t9', 'tok');
    expect(filename).toMatch(/^docsgpt-team-chats-\d{4}-\d{2}-\d{2}\.ndjson$/);
  });

  it('rejects an export that is switched off', async () => {
    answer = () => new Response('Not found', { status: 404 });
    const error = await payerService
      .exportTeamChats('t9', 'tok')
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(PayerApiError);
    expect((error as PayerApiError).status).toBe(404);
  });
});
