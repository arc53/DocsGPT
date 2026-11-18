import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Messages read as their keys and values.
vi.mock('i18next', () => ({
  default: {
    t: (key: string, values?: Record<string, unknown>) =>
      values ? `${key}|${values.used}|${values.limit}` : key,
    language: 'en-US',
  },
}));

import {
  onWorkspaceLost,
  setRequestWorkspace,
  WORKSPACE_HEADER,
} from '../workspace/requestWorkspace';
import { handleFetchAnswerSteaming } from './conversationHandlers';

type Call = { url: string; init: RequestInit };
const calls: Call[] = [];
let answer: () => Response;

const sse = (frame: object, status = 200) =>
  new Response(`data: ${JSON.stringify(frame)}\n\n`, {
    status,
    headers: { 'Content-Type': 'text/event-stream' },
  });

const json = (body: object, status: number) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

/** Sends a new chat's first question and returns the frames it produced. */
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
  calls.length = 0;
  answer = () => sse({ type: 'end' });
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

describe('a chat request and its workspace', () => {
  it('a new chat names the workspace it is started in', async () => {
    await ask();
    expect(calls).toHaveLength(1);
    expect(
      (calls[0].init.headers as Record<string, string>)[WORKSPACE_HEADER],
    ).toBe('t1');
  });

  it("an agent from another workspace surfaces the mismatch's code", async () => {
    answer = () =>
      sse(
        {
          type: 'error',
          error: 'This agent belongs to another workspace than this chat',
          code: 'workspace_mismatch',
        },
        409,
      );
    const frames = await ask();
    expect(frames).toContainEqual(
      expect.objectContaining({ type: 'error', code: 'workspace_mismatch' }),
    );
  });

  it('a JSON mismatch refusal keeps its code too', async () => {
    answer = () =>
      json({ success: false, error: 'workspace_mismatch', message: 'x' }, 409);
    const frames = await ask();
    expect(frames).toEqual([
      expect.objectContaining({ type: 'error', code: 'workspace_mismatch' }),
    ]);
  });

  it('a team the caller left checks the workspace list again', async () => {
    const lost = vi.fn();
    const off = onWorkspaceLost(lost);
    answer = () =>
      sse(
        {
          type: 'error',
          error: 'Workspace not found',
          code: 'workspace_not_found',
        },
        404,
      );
    try {
      await ask();
    } finally {
      off();
    }
    expect(lost).toHaveBeenCalledWith('t1');
  });

  it("an agent over its own limit says so, not the user's quota", async () => {
    answer = () =>
      json(
        {
          success: false,
          error_code: 'agent-limit-exceeded',
          dimension: 'tokens',
          usage: 1200,
          limit: 1000,
          window_hours: 24,
        },
        429,
      );
    const frames = await ask();
    expect(frames).toEqual([
      {
        type: 'error',
        error: 'conversation.agentLimit.tokens|1,200|1,000',
        code: 'agent-limit-exceeded',
      },
    ]);
  });
});
