import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const service = vi.hoisted(() => ({ answerStream: vi.fn() }));
vi.mock('../api/services/conversationService', () => ({ default: service }));

import {
  handleFetchAnswerSteaming,
  STREAM_IDLE_TIMEOUT_MS,
} from './conversationHandlers';

const encoder = new TextEncoder();
const frame = (id: number, data: object) =>
  encoder.encode(`id: ${id}\ndata: ${JSON.stringify(data)}\n\n`);

const sse = (body: ReadableStream<Uint8Array>, status = 200) =>
  new Response(body, {
    status,
    headers: { 'Content-Type': 'text/event-stream' },
  });

/**
 * A live stream that sends ``frames`` and then, by ``then``: errors like a
 * dropped socket, or goes silent like a dead one (ending only on abort).
 */
function liveStream(
  frames: Uint8Array[],
  then: 'drop' | 'silent',
  signal?: AbortSignal,
): ReadableStream<Uint8Array> {
  let sent = 0;
  return new ReadableStream({
    start(controller) {
      signal?.addEventListener('abort', () =>
        controller.error(new DOMException('aborted', 'AbortError')),
      );
    },
    // One frame per read; erroring in ``start`` would discard the queue.
    pull(controller) {
      if (sent < frames.length) controller.enqueue(frames[sent++]);
      else if (then === 'drop')
        controller.error(new TypeError('network error'));
      else return new Promise<void>(() => {});
    },
  });
}

const ended = (id: number) =>
  sse(
    liveStream(
      [
        frame(id, { type: 'answer', answer: ' world' }),
        frame(id + 1, { type: 'end' }),
      ],
      'silent',
    ),
  );

const started = [
  frame(1, { type: 'message_id', message_id: 'msg-1' }),
  frame(2, { type: 'answer', answer: 'hello' }),
];

async function run(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock);
  const events: Record<string, unknown>[] = [];
  const done = handleFetchAnswerSteaming(
    'q',
    new AbortController().signal,
    'tok',
    [],
    'conv-1',
    null,
    (event) => events.push(JSON.parse(event.data)),
  );
  await vi.runAllTimersAsync();
  await done;
  return events;
}

describe('a chat stream that drops mid-answer', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    service.answerStream.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('resumes from the last event and finishes without an error', async () => {
    service.answerStream.mockImplementation(async () =>
      sse(liveStream(started, 'drop')),
    );
    const fetchMock = vi.fn<(url: string) => Promise<Response>>(async () =>
      ended(3),
    );
    const events = await run(fetchMock);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      '/api/messages/msg-1/events?last_event_id=2',
    );
    expect(events.map((e) => e.type)).toEqual([
      'message_id',
      'answer',
      'answer',
      'end',
    ]);
  });

  it('keeps retrying through the connection cap and server errors', async () => {
    service.answerStream.mockImplementation(async () =>
      sse(liveStream(started, 'drop')),
    );
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(new Response('{}', { status: 429 }))
      .mockResolvedValueOnce(new Response('{}', { status: 502 }))
      .mockImplementation(async () => ended(3));
    const events = await run(fetchMock);

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(events.at(-1)).toEqual({ type: 'end' });
    expect(events.some((e) => e.type === 'error')).toBe(false);
  });

  it('waits for the browser to come back online before resuming', async () => {
    service.answerStream.mockImplementation(async () =>
      sse(liveStream(started, 'drop')),
    );
    const onLine = vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
    const fetchMock = vi.fn(async () => ended(3));
    vi.stubGlobal('fetch', fetchMock);
    const events: Record<string, unknown>[] = [];
    const done = handleFetchAnswerSteaming(
      'q',
      new AbortController().signal,
      'tok',
      [],
      'conv-1',
      null,
      (event) => events.push(JSON.parse(event.data)),
    );
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetchMock).not.toHaveBeenCalled();

    onLine.mockReturnValue(true);
    window.dispatchEvent(new Event('online'));
    await vi.runAllTimersAsync();
    await done;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(events.at(-1)).toEqual({ type: 'end' });
  });

  it('cuts a stream gone silent and resumes it', async () => {
    service.answerStream.mockImplementation(
      async (_payload, _token, signal: AbortSignal) =>
        sse(liveStream(started, 'silent', signal)),
    );
    const fetchMock = vi.fn(async () => ended(3));
    vi.stubGlobal('fetch', fetchMock);
    const events: Record<string, unknown>[] = [];
    const done = handleFetchAnswerSteaming(
      'q',
      new AbortController().signal,
      'tok',
      [],
      'conv-1',
      null,
      (event) => events.push(JSON.parse(event.data)),
    );
    await vi.advanceTimersByTimeAsync(STREAM_IDLE_TIMEOUT_MS - 1_000);
    expect(fetchMock).not.toHaveBeenCalled();
    await vi.runAllTimersAsync();
    await done;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(events.at(-1)).toEqual({ type: 'end' });
  });

  it('gives up with a connection_lost error that names the message', async () => {
    service.answerStream.mockImplementation(async () =>
      sse(liveStream(started, 'drop')),
    );
    const fetchMock = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    const events = await run(fetchMock);

    expect(fetchMock).toHaveBeenCalledTimes(8);
    expect(events.at(-1)).toMatchObject({
      type: 'error',
      code: 'connection_lost',
      message_id: 'msg-1',
    });
  });

  it('stops at once when the server no longer has the message', async () => {
    service.answerStream.mockImplementation(async () =>
      sse(liveStream(started, 'drop')),
    );
    const fetchMock = vi.fn(async () => new Response('{}', { status: 404 }));
    const events = await run(fetchMock);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(events.at(-1)).toMatchObject({
      type: 'error',
      code: 'connection_lost',
    });
  });

  it('does not resume after the user stopped the answer', async () => {
    const controller = new AbortController();
    service.answerStream.mockImplementation(async () => {
      controller.abort();
      return sse(liveStream(started, 'drop'));
    });
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const events: Record<string, unknown>[] = [];
    const done = handleFetchAnswerSteaming(
      'q',
      controller.signal,
      'tok',
      [],
      'conv-1',
      null,
      (event) => events.push(JSON.parse(event.data)),
    );
    await vi.runAllTimersAsync();
    await done;
    expect(fetchMock).not.toHaveBeenCalled();
    expect(events.some((e) => e.type === 'error')).toBe(false);
  });
});
