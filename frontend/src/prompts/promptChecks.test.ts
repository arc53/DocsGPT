const client = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock('../api/client', () => ({ default: client }));

import { checkPrompt, readPromptChecks } from './promptChecks';

describe('readPromptChecks', () => {
  it('keeps each check with a code, its well-formed facts and nothing else', () => {
    expect(
      readPromptChecks([
        { code: 'placeholder', text: '[company]', line: 2 },
        { code: 'tool_variables', variables: ['{{ tools.a.b }}', 3] },
        { code: 'repeats_builtin', topic: 'date', line: 1.5 },
        { code: '' },
        { text: 'no code' },
        null,
      ]),
    ).toEqual([
      {
        code: 'placeholder',
        text: '[company]',
        topic: null,
        variables: [],
        line: 2,
      },
      {
        code: 'tool_variables',
        text: null,
        topic: null,
        variables: ['{{ tools.a.b }}'],
        line: null,
      },
      {
        code: 'repeats_builtin',
        text: null,
        topic: 'date',
        variables: [],
        line: null,
      },
    ]);
    expect(readPromptChecks({ checks: [] })).toEqual([]);
  });
});

describe('checkPrompt', () => {
  beforeEach(() => client.post.mockReset());

  it('posts the text and reads the checks', async () => {
    client.post.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ checks: [{ code: 'boundaries_missing' }] }),
    });
    const signal = new AbortController().signal;
    expect(await checkPrompt('Hi', 'tok', signal)).toEqual([
      {
        code: 'boundaries_missing',
        text: null,
        topic: null,
        variables: [],
        line: null,
      },
    ]);
    expect(client.post).toHaveBeenCalledWith(
      '/api/check_prompt',
      { content: 'Hi' },
      'tok',
      {},
      signal,
    );
  });

  it('is null when the check fails', async () => {
    client.post.mockResolvedValue({ ok: false, status: 400 });
    expect(await checkPrompt('Hi', 'tok')).toBeNull();
    // A body that isn't JSON (a vi.fn's own rejection reports as unhandled).
    client.post.mockResolvedValue({
      ok: true,
      json: () => Promise.reject(new SyntaxError('not JSON')),
    });
    expect(await checkPrompt('Hi', 'tok')).toBeNull();
  });
});
