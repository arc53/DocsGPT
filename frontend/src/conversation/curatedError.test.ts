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
    expect(curatedErrorText(t, 'x', 'stopped')).toBe(
      'conversation.errors.stopped',
    );
    expect(curatedErrorText(t, 'x', 'no_answer')).toBe(
      'conversation.errors.noAnswer',
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

  it('words an in-run quota stop from its values, with the reset date', () => {
    const text = curatedErrorText(t, 'Usage quota reached.', 'quota-exceeded', {
      dimension: 'cost',
      unit: 'usd',
      usage: 5.25,
      limit: 5,
      bucket: 'all',
      resets_at: '2026-12-01T00:00:00+00:00',
    });
    expect(text).toMatch(/^conversation\.quotaExceeded\.cost /);
    expect(text).toContain('"used":"$5.25"');
    expect(text).toContain('"limit":"$5.00"');
    expect(text).toMatch(/"resetsAt":"[^"]*2026[^"]*"/);
  });

  it('words a quota stop without values plainly', () => {
    expect(curatedErrorText(t, 'Usage quota reached.', 'quota-exceeded')).toBe(
      'conversation.quotaExceeded.reached',
    );
  });

  it("words the agent's own limit from its values", () => {
    expect(
      curatedErrorText(t, 'x', 'agent-limit-exceeded', {
        dimension: 'requests',
        usage: 120,
        limit: 100,
        window_hours: 24,
      }),
    ).toBe(
      'conversation.agentLimit.requests {"used":"120","limit":"100","hours":24}',
    );
    // A refusal before the run arrives already worded.
    expect(curatedErrorText(t, 'Worded already.', 'agent-limit-exceeded')).toBe(
      'Worded already.',
    );
  });

  it('words a paused agent without any numbers', () => {
    const text = curatedErrorText(t, 'This agent is paused.', 'agent_paused', {
      usage: 5,
      limit: 5,
    });
    expect(text).toBe('payer.notice.chat.agentPaused');
    expect(curatedErrorText(t, 'x', 'no_payer')).toBe(
      'payer.notice.chat.noPayer',
    );
  });

  it("says a team chat can't run on the caller's own custom model", () => {
    expect(
      curatedErrorText(t, 'server words', 'custom_model_personal_only'),
    ).toBe('settings.customModels.team.errors.chatPersonalOnly');
  });
});
