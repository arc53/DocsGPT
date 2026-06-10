import { describe, expect, it } from 'vitest';

import { decodeJwtPayload, getJwtRemainingMs, isJwtExpired } from './jwtUtils';

const b64url = (value: object) =>
  btoa(JSON.stringify(value))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');

const makeToken = (payload: object) =>
  `${b64url({ alg: 'HS256', typ: 'JWT' })}.${b64url(payload)}.signature`;

describe('decodeJwtPayload', () => {
  it('decodes the payload of a well-formed token', () => {
    const token = makeToken({ sub: 'user-1', email: 'u@example.com' });
    expect(decodeJwtPayload(token)).toEqual({
      sub: 'user-1',
      email: 'u@example.com',
    });
  });

  it('returns null for garbage input', () => {
    expect(decodeJwtPayload('not-a-jwt')).toBeNull();
    expect(decodeJwtPayload('a.%%%.c')).toBeNull();
    expect(decodeJwtPayload('')).toBeNull();
  });
});

describe('isJwtExpired', () => {
  const now = Math.floor(Date.now() / 1000);

  it('returns true for an expired token', () => {
    expect(isJwtExpired(makeToken({ sub: 'u', exp: now - 3600 }))).toBe(true);
  });

  it('returns false for a token expiring well in the future', () => {
    expect(isJwtExpired(makeToken({ sub: 'u', exp: now + 3600 }))).toBe(false);
  });

  it('treats tokens inside the skew window as expired', () => {
    expect(isJwtExpired(makeToken({ sub: 'u', exp: now + 10 }))).toBe(true);
  });

  it('returns false when the exp claim is absent (legacy tokens)', () => {
    expect(isJwtExpired(makeToken({ sub: 'local' }))).toBe(false);
  });

  it('returns false for undecodable tokens', () => {
    expect(isJwtExpired('garbage')).toBe(false);
  });
});

describe('getJwtRemainingMs', () => {
  it('returns the milliseconds left until expiry', () => {
    const exp = Math.floor(Date.now() / 1000) + 3600;
    const remaining = getJwtRemainingMs(makeToken({ sub: 'u', exp }));
    expect(remaining).not.toBeNull();
    // exp is truncated to whole seconds, so allow up to 1s of slack.
    expect(remaining!).toBeGreaterThan(3599_000 - 1000);
    expect(remaining!).toBeLessThanOrEqual(3600_000);
  });

  it('returns a negative value for an already-expired token', () => {
    const exp = Math.floor(Date.now() / 1000) - 60;
    const remaining = getJwtRemainingMs(makeToken({ sub: 'u', exp }));
    expect(remaining).not.toBeNull();
    expect(remaining!).toBeLessThan(0);
  });

  it('returns null when the exp claim is absent', () => {
    expect(getJwtRemainingMs(makeToken({ sub: 'u' }))).toBeNull();
  });

  it('returns null when the exp claim is not a number', () => {
    expect(getJwtRemainingMs(makeToken({ sub: 'u', exp: 'soon' }))).toBeNull();
  });

  it('returns null for undecodable tokens', () => {
    expect(getJwtRemainingMs('garbage')).toBeNull();
    expect(getJwtRemainingMs('')).toBeNull();
  });
});
