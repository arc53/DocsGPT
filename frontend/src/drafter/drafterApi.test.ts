const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../api/client', () => ({ default: client }));

import {
  type DrafterEvent,
  getDrafterConfig,
  parseDrafterEvent,
  streamDrafter,
} from './drafterApi';

/** A Response whose body streams the given chunks. */
const sseResponse = (chunks: string[], init: ResponseInit = {}) => {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { 'content-type': 'text/event-stream' },
    ...init,
  });
};

const frame = (event: object) => `data: ${JSON.stringify(event)}\n\n`;

const run = async () => {
  const events: DrafterEvent[] = [];
  await streamDrafter(
    {
      recipe: 'agent',
      messages: [{ role: 'user', content: 'Hi' }],
      context: {},
    },
    'tok',
    (event) => events.push(event),
    new AbortController().signal,
  );
  return events;
};

describe('drafterApi', () => {
  afterEach(() => {
    client.get.mockReset();
    client.post.mockReset();
  });

  it('reads the config, and an unreadable one as disabled', async () => {
    client.get.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          enabled: true,
          model: { id: 'm', display_name: 'Model' },
          reason: null,
        }),
      ),
    );
    await expect(getDrafterConfig('tok')).resolves.toEqual({
      enabled: true,
      model: { id: 'm', display_name: 'Model' },
      reason: null,
    });
    client.get.mockResolvedValueOnce(new Response('nope', { status: 404 }));
    expect((await getDrafterConfig('tok')).enabled).toBe(false);
    client.get.mockRejectedValueOnce(new Error('offline'));
    expect((await getDrafterConfig('tok')).enabled).toBe(false);
  });

  it('posts the request and hands over each event, split across chunks', async () => {
    const questions = {
      type: 'questions',
      questions: [
        {
          id: 'q1',
          text: 'Where?',
          note: null,
          multi: false,
          options: [{ id: 'a', label: 'Email' }],
        },
      ],
    };
    const raw =
      frame({ type: 'status', step: 'reading', counts: { tools: 2 } }) +
      ': keepalive\n\n' +
      frame(questions) +
      frame({ type: 'end' });
    client.post.mockResolvedValueOnce(
      sseResponse([raw.slice(0, 30), raw.slice(30, 90), raw.slice(90)]),
    );
    const events = await run();
    expect(client.post).toHaveBeenCalledWith(
      '/api/drafter/stream',
      {
        recipe: 'agent',
        messages: [{ role: 'user', content: 'Hi' }],
        context: {},
      },
      'tok',
      {},
      expect.any(AbortSignal),
    );
    expect(events.map((event) => event.type)).toEqual([
      'status',
      'questions',
      'end',
    ]);
    expect(events[1]).toEqual(questions);
  });

  it('turns a refused request into an error event and an end', async () => {
    client.post.mockResolvedValueOnce(
      new Response(JSON.stringify({ message: 'Slow down' }), {
        status: 429,
        headers: { 'content-type': 'application/json' },
      }),
    );
    expect(await run()).toEqual([
      { type: 'error', code: 'rate_limited', message: 'Slow down' },
      { type: 'end' },
    ]);
    client.post.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ error_code: 'quota-exceeded', limit: 1, usage: 2 }),
        { status: 429, headers: { 'content-type': 'application/json' } },
      ),
    );
    expect((await run())[0]).toMatchObject({ type: 'error', code: 'quota' });
  });

  it('ends a stream that broke off with a model error', async () => {
    client.post.mockResolvedValueOnce(
      sseResponse([frame({ type: 'message', text: 'Working' })]),
    );
    expect(await run()).toEqual([
      { type: 'message', text: 'Working' },
      { type: 'error', code: 'model_error', message: undefined },
      { type: 'end' },
    ]);
  });

  it('keeps the error a broken stream already sent, adding only the end', async () => {
    client.post.mockResolvedValueOnce(
      sseResponse([frame({ type: 'error', code: 'invalid_output' })]),
    );
    expect(await run()).toEqual([
      { type: 'error', code: 'invalid_output' },
      { type: 'end' },
    ]);
  });

  it('stops quietly when aborted', async () => {
    const controller = new AbortController();
    client.post.mockImplementationOnce(() => {
      controller.abort();
      return Promise.reject(new DOMException('Aborted', 'AbortError'));
    });
    const events: DrafterEvent[] = [];
    await streamDrafter(
      { recipe: 'agent', messages: [], context: {} },
      null,
      (event) => events.push(event),
      controller.signal,
    );
    expect(events).toEqual([]);
  });

  it('ignores frames it does not know', () => {
    expect(parseDrafterEvent('{"type":"thought"}')).toBeNull();
    expect(parseDrafterEvent('not json')).toBeNull();
    expect(parseDrafterEvent('{"type":"end"}')).toEqual({ type: 'end' });
  });
});
