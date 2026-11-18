import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('i18next', () => ({
  default: {
    t: (key: string, values?: Record<string, unknown>) =>
      values ? `${key}|${values.used}|${values.limit}` : key,
    language: 'en-US',
  },
}));

const usage = vi.hoisted(() => ({
  noteTurnFinished: vi.fn(),
  noteQuotaError: vi.fn(),
}));
vi.mock('../payer/usageSlice', () => usage);

import { handleFetchAnswerSteaming } from './conversationHandlers';

let answer: () => Response;

const sse = (...frames: object[]) =>
  new Response(frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join(''), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  });

const json = (body: object, status: number) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

async function ask(): Promise<Record<string, unknown>[]> {
  const frames: Record<string, unknown>[] = [];
  await handleFetchAnswerSteaming(
    'hello',
    new AbortController().signal,
    'tok',
    [],
    null,
    null,
    '2',
    (event) => frames.push(JSON.parse(event.data)),
  );
  return frames;
}

beforeEach(() => {
  usage.noteTurnFinished.mockReset();
  usage.noteQuotaError.mockReset();
  answer = () => sse({ type: 'answer', answer: 'hi' }, { type: 'end' });
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(answer())),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('a chat turn and the usage meter', () => {
  it('tells the usage slice once when a turn ends', async () => {
    await ask();
    expect(usage.noteTurnFinished).toHaveBeenCalledTimes(1);
    expect(usage.noteQuotaError).not.toHaveBeenCalled();
  });

  it('reports an in-run quota stop as a quota error', async () => {
    answer = () =>
      sse(
        { type: 'answer', answer: 'partial' },
        {
          type: 'error',
          error: 'Usage quota reached.',
          code: 'quota-exceeded',
          params: { usage: 5, limit: 5 },
        },
      );
    await ask();
    expect(usage.noteQuotaError).toHaveBeenCalledTimes(1);
    expect(usage.noteTurnFinished).not.toHaveBeenCalled();
  });

  it('gives a refused turn its quota code and values', async () => {
    answer = () =>
      json(
        {
          success: false,
          error_code: 'quota-exceeded',
          message: 'Usage quota reached.',
          limit_scope: 'user_quota',
          dimension: 'cost',
          unit: 'usd',
          usage: 5.25,
          limit: 5,
          bucket: 'all',
          source: 'user',
          resets_at: '2026-12-01T00:00:00+00:00',
        },
        429,
      );
    const frames = await ask();
    expect(frames).toEqual([
      {
        type: 'error',
        error: 'conversation.quotaExceeded.cost|$5.25|$5.00',
        code: 'quota-exceeded',
        params: {
          dimension: 'cost',
          unit: 'usd',
          usage: 5.25,
          limit: 5,
          bucket: 'all',
          resets_at: '2026-12-01T00:00:00+00:00',
        },
      },
    ]);
    expect(usage.noteQuotaError).toHaveBeenCalledTimes(1);
  });

  it('keeps the paused code of an agent whose payer can’t pay', async () => {
    answer = () =>
      json(
        {
          success: false,
          error_code: 'agent_paused',
          code: 'agent_paused',
          message: "This agent is paused, so it can't answer right now.",
        },
        429,
      );
    const frames = await ask();
    expect(frames).toEqual([
      {
        type: 'error',
        error: "This agent is paused, so it can't answer right now.",
        code: 'agent_paused',
      },
    ]);
  });
});
