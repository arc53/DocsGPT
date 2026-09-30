import { describe, expect, it } from 'vitest';

import {
  isReader,
  personLabel,
  readerIdFromToken,
  truncateSub,
} from './personLabel';

const b64url = (value: object) =>
  btoa(JSON.stringify(value))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');

const LONG_SUB = '0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0';

describe('truncateSub', () => {
  it('keeps a short id whole', () => {
    expect(truncateSub('bob')).toBe('bob');
  });

  it('cuts the middle of a long OIDC sub, keeping both ends', () => {
    expect(truncateSub(LONG_SUB)).toBe('0f1e2d3c-4b5…c3d2e1f0');
  });
});

describe('personLabel', () => {
  it('says "you" for the reader', () => {
    expect(
      personLabel(
        { user_id: 'me', label: 'me@example.com' },
        { readerId: 'me', you: 'You' },
      ),
    ).toBe('You');
  });

  it('uses the email of anyone else', () => {
    expect(
      personLabel(
        { user_id: 'bob', email: 'bob@example.com' },
        { readerId: 'me', you: 'You' },
      ),
    ).toBe('bob@example.com');
    expect(personLabel({ user_id: 'bob', label: 'bob@example.com' })).toBe(
      'bob@example.com',
    );
  });

  it('falls back to a truncated sub, never the full one', () => {
    expect(personLabel({ user_id: LONG_SUB, email: '  ' })).toBe(
      truncateSub(LONG_SUB),
    );
    // A read's label is the user id when no email is on file.
    expect(personLabel({ user_id: LONG_SUB, label: LONG_SUB })).toBe(
      truncateSub(LONG_SUB),
    );
  });

  it('names nobody the reader does not know', () => {
    expect(personLabel({ user_id: null, label: null })).toBeNull();
    expect(personLabel(null)).toBeNull();
  });

  it('does not call someone "you" without a reader id', () => {
    expect(
      personLabel({ user_id: 'me', label: 'me@example.com' }, { you: 'You' }),
    ).toBe('me@example.com');
    expect(isReader({ user_id: 'me' }, undefined)).toBe(false);
    expect(isReader({ user_id: 'me' }, 'me')).toBe(true);
  });
});

describe('readerIdFromToken', () => {
  it("reads the token's subject", () => {
    const token = `${b64url({ alg: 'HS256' })}.${b64url({ sub: 'me' })}.sig`;
    expect(readerIdFromToken(token)).toBe('me');
  });

  it('returns undefined without a usable token', () => {
    expect(readerIdFromToken(null)).toBeUndefined();
    expect(readerIdFromToken('garbage')).toBeUndefined();
  });
});
