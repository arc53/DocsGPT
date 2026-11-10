const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../api/client', () => ({ default: client }));

import {
  cancelDrafterTurn,
  type DrafterEvent,
  getAgentGaps,
  getDrafterConfig,
  newDrafterTurnId,
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

  it('reads the config, and an unreadable one as unavailable', async () => {
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
    // A failed read is off but says so, unlike a server with drafting off.
    const unread = { enabled: false, model: null, reason: 'unavailable' };
    client.get.mockResolvedValueOnce(new Response('nope', { status: 404 }));
    await expect(getDrafterConfig('tok')).resolves.toEqual(unread);
    client.get.mockRejectedValueOnce(new Error('offline'));
    await expect(getDrafterConfig('tok')).resolves.toEqual(unread);
    client.get.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ enabled: false, model: null, reason: 'disabled' }),
      ),
    );
    await expect(getDrafterConfig('tok')).resolves.toEqual({
      enabled: false,
      model: null,
      reason: 'disabled',
    });
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
    // A refused key keeps its own code (decision 105).
    client.post.mockResolvedValueOnce(
      new Response(JSON.stringify({ code: 'model_auth', message: 'Refused' }), {
        status: 502,
        headers: { 'content-type': 'application/json' },
      }),
    );
    expect((await run())[0]).toMatchObject({
      type: 'error',
      code: 'model_auth',
    });
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

  it('ends a stream that broke off after its draft as a finished turn', async () => {
    // The proposal or questions are the turn's answer, already applied: only `end` was lost.
    const proposal = { type: 'proposal', proposal: { fields: {} } };
    client.post.mockResolvedValueOnce(sseResponse([frame(proposal)]));
    expect(await run()).toEqual([proposal, { type: 'end' }]);
    const questions = { type: 'questions', questions: [] };
    client.post.mockResolvedValueOnce(
      sseResponse([
        frame({ type: 'message', text: 'First:' }),
        frame(questions),
      ]),
    );
    expect(await run()).toEqual([
      { type: 'message', text: 'First:' },
      questions,
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

  it('cancels a turn by its id, and shrugs off a failure', async () => {
    client.post.mockResolvedValueOnce(new Response('{}', { status: 202 }));
    await cancelDrafterTurn('abc', 'tok');
    expect(client.post).toHaveBeenCalledWith(
      '/api/drafter/turns/abc/cancel',
      {},
      'tok',
    );
    client.post.mockRejectedValueOnce(new Error('offline'));
    await expect(cancelDrafterTurn('abc', 'tok')).resolves.toBeUndefined();
  });

  it('picks a turn id the server takes, and sends it with the turn', async () => {
    const id = newDrafterTurnId();
    expect(id).toMatch(/^[0-9a-f]{32}$/);
    expect(newDrafterTurnId()).not.toBe(id);
    client.post.mockResolvedValueOnce(sseResponse([frame({ type: 'end' })]));
    const request = { recipe: 'agent' as const, messages: [], context: {} };
    await streamDrafter(
      request,
      'tok',
      () => undefined,
      new AbortController().signal,
      id,
    );
    expect(client.post.mock.calls[0][1]).toEqual({ ...request, turn_id: id });
  });

  it('ignores frames it does not know', () => {
    expect(parseDrafterEvent('{"type":"turn","id":"abc"}')).toEqual({
      type: 'turn',
      id: 'abc',
    });
    expect(parseDrafterEvent('{"type":"turn"}')).toBeNull();
    expect(parseDrafterEvent('{"type":"thought"}')).toBeNull();
    expect(parseDrafterEvent('not json')).toBeNull();
    expect(parseDrafterEvent('{"type":"end"}')).toEqual({ type: 'end' });
  });

  it('reads an error code it does not know as a model error', () => {
    expect(
      parseDrafterEvent('{"type":"error","code":"quota","message":"Out"}'),
    ).toEqual({ type: 'error', code: 'quota', message: 'Out' });
    expect(parseDrafterEvent('{"type":"error","code":"overheated"}')).toEqual({
      type: 'error',
      code: 'model_error',
    });
    expect(parseDrafterEvent('{"type":"error","code":7}')).toEqual({
      type: 'error',
      code: 'model_error',
    });
  });

  it('reads what a read tool showed, keeping only the question text', () => {
    expect(
      parseDrafterEvent(
        JSON.stringify({
          type: 'read',
          kind: 'questions',
          items: ['How long do I have?', 7, '  ', 'Can I return it?'],
        }),
      ),
    ).toEqual({
      type: 'read',
      kind: 'questions',
      items: ['How long do I have?', 'Can I return it?'],
    });
    expect(
      parseDrafterEvent('{"type":"read","kind":"answers","items":[]}'),
    ).toBeNull();
    expect(parseDrafterEvent('{"type":"read","kind":"questions"}')).toBeNull();
  });

  it("reads an agent's gap summary, leaving malformed rows out", async () => {
    client.get.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          available: true,
          reason: null,
          conversations: 412,
          needed: 10,
          days: 30,
          rows: [
            {
              topic: 'Returns & claims',
              gap_type: 'docs missing',
              expected: 23,
              turns: 160,
              previous: 19,
            },
            {
              topic: null,
              gap_type: 'out of scope',
              expected: 4,
              turns: 412,
              previous: null,
            },
            { topic: 'Broken', gap_type: '', expected: 1, turns: 2 },
            { topic: 'NaN', gap_type: 'docs missing', expected: 'x', turns: 2 },
          ],
        }),
      ),
    );
    const gaps = await getAgentGaps('agent-1', 'tok');
    expect(client.get.mock.calls[0][0]).toBe(
      '/api/drafter/agent_gaps?agent_id=agent-1',
    );
    expect(gaps).toEqual({
      available: true,
      reason: null,
      conversations: 412,
      needed: 10,
      days: 30,
      rows: [
        {
          topic: 'Returns & claims',
          gap_type: 'docs missing',
          expected: 23,
          turns: 160,
          previous: 19,
        },
        {
          topic: null,
          gap_type: 'out of scope',
          expected: 4,
          turns: 412,
          previous: null,
        },
      ],
    });
  });

  it('reads a gap summary that is off, or unreadable, as unavailable', async () => {
    client.get.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          available: false,
          reason: 'not_enough',
          conversations: 4,
          needed: 10,
          days: 30,
          rows: [],
        }),
      ),
    );
    expect(await getAgentGaps('agent-1', 'tok')).toMatchObject({
      available: false,
      reason: 'not_enough',
      conversations: 4,
      needed: 10,
    });
    client.get.mockResolvedValueOnce(new Response('{}', { status: 404 }));
    expect(await getAgentGaps('agent-1', 'tok')).toMatchObject({
      available: false,
      reason: 'unavailable',
      rows: [],
    });
    client.get.mockRejectedValueOnce(new Error('offline'));
    expect((await getAgentGaps('agent-1', 'tok')).reason).toBe('unavailable');
  });
});
