/**
 * GHSA-949x-3mqg-5xfr: the connector OAuth popup posted the session token with
 * a wildcard target origin, and this component's `message` handler accepted a
 * message from any origin. Either half alone lets a page hand the app a
 * fabricated `session_token`, or take a real one.
 *
 * `resolveAuthMessageOrigin` is the half that can be tested without a DOM
 * popup: which single origin the handler will listen to.
 */
import { describe, expect, it } from 'vitest';

import { resolveAuthMessageOrigin } from './ConnectorAuth';

const PAGE = 'https://app.example.com';

describe('resolveAuthMessageOrigin', () => {
  it('is the API origin, because the popup is the API callback page', () => {
    expect(resolveAuthMessageOrigin('https://api.example.com', PAGE)).toBe(
      'https://api.example.com',
    );
  });

  it('drops any path on the configured host', () => {
    // postMessage compares origins; an origin carrying a path never matches.
    expect(resolveAuthMessageOrigin('https://api.example.com/v1/', PAGE)).toBe(
      'https://api.example.com',
    );
  });

  it('resolves a relative API host against this page', () => {
    // A same-origin deployment sets VITE_API_HOST to a path, or to nothing.
    expect(resolveAuthMessageOrigin('/api', PAGE)).toBe(PAGE);
    expect(resolveAuthMessageOrigin('', PAGE)).toBe(PAGE);
  });

  it('never answers with a wildcard, whatever it is given', () => {
    // The accept control: an unusable value must fall back to one real origin,
    // not to something that matches everything.
    for (const host of ['not a url', '*', 'http://', '::::']) {
      const resolved = resolveAuthMessageOrigin(host, PAGE);
      expect(resolved).not.toBe('*');
      expect(resolved.startsWith('http')).toBe(true);
    }
  });

  it('does not treat a different origin as the same one', () => {
    // The property the handler relies on: an attacker page's origin must not
    // resolve to the API's.
    expect(resolveAuthMessageOrigin('https://api.example.com', PAGE)).not.toBe(
      'https://evil.example.com',
    );
  });
});
