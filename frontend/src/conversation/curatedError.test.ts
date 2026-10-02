import { describe, expect, it } from 'vitest';

import { curatedErrorText, readStreamError } from './curatedError';

// Records the key and options it was asked for, so the test sees both.
const t = ((key: string, options?: Record<string, unknown>) =>
  options ? `${key} ${JSON.stringify(options)}` : key) as never;

describe('readStreamError', () => {
  it('keeps the text, code and params of a curated error event', () => {
    expect(
      readStreamError({
        type: 'error',
        error: 'Too large.',
        code: 'context_length_exceeded',
        params: { needed_tokens: 300000, available_tokens: 200000 },
      }),
    ).toEqual({
      message: 'Too large.',
      code: 'context_length_exceeded',
      params: { needed_tokens: 300000, available_tokens: 200000 },
    });
  });

  it('leaves out a code or params the event does not carry', () => {
    expect(readStreamError({ type: 'error', error: 'Blocked.' })).toEqual({
      message: 'Blocked.',
    });
    expect(
      readStreamError({ type: 'error', error: 'x', code: 7, params: 'no' }),
    ).toEqual({ message: 'x' });
  });
});

describe('curatedErrorText', () => {
  it('words an overflow with its sizes in the user language', () => {
    expect(
      curatedErrorText(t, 'server text', 'context_length_exceeded', {
        needed_tokens: 300000,
        available_tokens: 200000,
      }),
    ).toBe(
      'conversation.errors.contextLengthSized {"needed":300000,"available":200000}',
    );
  });

  it('points at Add to Knowledge only when the action is offered', () => {
    const params = { needed_tokens: 300000, available_tokens: 200000 };
    expect(
      curatedErrorText(t, 'x', 'context_length_exceeded', params, {
        offersKnowledge: true,
      }),
    ).toContain('conversation.errors.contextLengthSizedKnowledge ');
    expect(
      curatedErrorText(t, 'x', 'context_length_exceeded', undefined, {
        offersKnowledge: true,
      }),
    ).toBe('conversation.errors.contextLengthKnowledge');
    expect(curatedErrorText(t, 'x', 'context_length_exceeded')).toBe(
      'conversation.errors.contextLength',
    );
  });

  it('words the other known codes', () => {
    expect(curatedErrorText(t, 'x', 'server_error')).toBe(
      'conversation.errors.serverError',
    );
    expect(curatedErrorText(t, 'x', 'client_disconnect')).toBe(
      'conversation.errors.clientDisconnect',
    );
  });

  it("keeps the server's text for an unknown code or none", () => {
    expect(curatedErrorText(t, 'Quota used up.', 'quota_exceeded')).toBe(
      'Quota used up.',
    );
    expect(curatedErrorText(t, 'raw provider error')).toBe(
      'raw provider error',
    );
  });
});
